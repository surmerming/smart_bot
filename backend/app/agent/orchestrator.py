"""Agent 管线主编排器：串联 情绪分级 → 检索 → 置信度决策 → 生成 → 输出校验 → 转人工。

产出的 SSE 事件流（dict）：
    {"type": "meta", "data": {...}}   会话元信息（状态/情绪/意图/置信度/快捷按钮）
    {"type": "text", "data": {"content": "..."}}   流式增量文本
    {"type": "done", "data": {...}}   结束（含转人工标记、摘要）
"""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Optional

from app.agent import prompts
from app.agent.emotion import classify_emotion
from app.agent.humor import extract_key_facts
from app.agent.intent import can_answer, classify_intent, decide, nli_check
from app.agent.llm import llm
from app.agent.prompts import (
    HANDOVER_HARD_MSG,
    HANDOVER_SOFT_MSG,
    RED_LIGHT_MSG,
    UNKNOWN_FALLBACK_MSG,
    build_system_prompt,
    format_context,
    format_history,
)
from app.config import settings
from app.storage.kb import (
    FAQItem,
    KnowledgeBase,
    has_negation,
    has_risk_keyword,
    is_confirmation,
    is_denial,
    wants_human,
)

logger = logging.getLogger(__name__)

# 情绪 → 是否允许幽默
_SERIOUS_EMOTIONS = {"LEVEL_2", "LEVEL_3"}
# 不允许幽默的分类（设计稿 6.4：交易/售后/账户/投诉 不玩梗；售前/闲聊可适度）
_HUMOR_ALLOWED_CATEGORIES = {"presales"}


# ---------- 输出校验（5.9 第三层，生成后轻量版）----------
def verify_facts(answer: str, results: list[dict]) -> bool:
    """回答中出现的数字/金额/时间必须能在检索上下文里找到依据，否则视为疑似幻觉。"""
    facts_in_answer = extract_key_facts(answer)
    if not facts_in_answer:
        return True
    context_text = format_context(results)
    facts_in_context = extract_key_facts(context_text)
    return facts_in_answer.issubset(facts_in_context)


def _shorten(text: str, limit: int = 14) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


# ---------- 转人工摘要（规则化 MVP 版，V1.5 换 LLM 摘要）----------
def build_handover_summary(query: str, history: list[dict], results: list[dict]) -> str:
    lines = [f"用户最新问题：{query}"]
    if history:
        recent = history[-4:]
        lines.append("最近对话：" + " / ".join(f"{'用户' if m['role'] == 'user' else '客服'}：{m['content'][:40]}" for m in recent))
    if results:
        top = results[0]["faq"]
        lines.append(f"Bot 已检索到：{top.id}（{top.category}），已尝试解答“{top.standard_question}”")
    return "；".join(lines)


class Orchestrator:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    # ================= 主入口 =================
    async def process_turn(
        self,
        *,
        query: str,
        history: list[dict],
        session_status: str = "AGENT_ACTIVE",
        session_meta: Optional[dict] = None,
        message_id: str = "",
    ) -> AsyncGenerator[dict, None]:
        meta = session_meta or {}
        handover_summary = build_handover_summary(query, history, [])

        # ---- 1. 用户主动要求转人工：立即转，不挽留 ----
        if wants_human(query):
            async for ev in self._hard_handover(query, history, reason="user_request", message_id=message_id):
                yield ev
            return

        # ---- 2. 确认状态机：可中断，不阻塞（5.3）----
        pending_faq_id = meta.get("pending_faq_id")
        if pending_faq_id and session_status == "CONFIRMING":
            if is_confirmation(query):
                faq = self.kb.get_faq(pending_faq_id)
                if faq:
                    async for ev in self._answer_flow(faq, history, query, emotion="LEVEL_0", confirmed=True, message_id=message_id):
                        yield ev
                    return
            elif is_denial(query):
                yield {
                    "type": "meta",
                    "data": {"status": "answering", "emotion": "LEVEL_0", "intent": "CONFIRM_NO",
                             "confidence": 1.0, "faq_ids": [], "handover": False, "quick_replies": []},
                }
                yield {"type": "text", "data": {"content": "好的，那您想了解什么，随时问我～"}}
                yield {"type": "done", "data": {"message_id": message_id, "handover": False, "handover_reason": "", "clear_pending": True}}
                return
            # 其他输入：打断确认状态，进入新意图流程

        # ---- 3. 情绪分级（5.6）----
        emotion = await classify_emotion(query)

        # ---- 4. 红灯熔断：情绪极差 / 命中风险词 ----
        if emotion == "LEVEL_3" or has_risk_keyword(query):
            async for ev in self._hard_handover(query, history, reason="emotion_red", emotion=emotion, message_id=message_id):
                yield ev
            return

        # ---- 5. 混合检索 ----
        results = self.kb.search(query, top_k=settings.RETRIEVE_TOP_K)
        verdict = decide(query, results)
        top_faq: Optional[FAQItem] = results[0]["faq"] if results else None

        # ---- 6. 决策 ----
        if verdict.decision == "handover":
            async for ev in self._soft_handover(query, history, results, emotion=emotion, message_id=message_id):
                yield ev
            return

        if verdict.decision == "ask_llm":
            if has_negation(query) and top_faq:
                # 否定句：NLI 语义方向校验（5.2）
                nli = await nli_check(query, top_faq)
                if nli == "CONTRADICTION":
                    async for ev in self._hard_handover(query, history, reason="negation_contradiction", emotion=emotion, message_id=message_id):
                        yield ev
                    return
                if nli == "NEUTRAL":
                    async for ev in self._soft_handover(query, history, results, emotion=emotion, message_id=message_id):
                        yield ev
                    return
                # ENTAILMENT → 继续生成
            else:
                # 中置信：LLM 布尔判断（5.9 第二层）
                if not await can_answer(query, results):
                    async for ev in self._soft_handover(query, history, results, emotion=emotion, reason="cannot_answer", message_id=message_id):
                        yield ev
                    return

        # ---- 7. 高风险 FAQ：不直接答，转人工（红线清单）----
        if top_faq and top_faq.risk_level == "high":
            async for ev in self._hard_handover(query, history, reason="high_risk_faq", emotion=emotion, faq=top_faq, message_id=message_id):
                yield ev
            return

        # ---- 8. 生成回答（流式）+ 输出校验 ----
        if top_faq is None:
            async for ev in self._soft_handover(query, history, results, emotion=emotion, message_id=message_id):
                yield ev
            return

        async for ev in self._answer_flow(top_faq, history, query, emotion=emotion, results=results, message_id=message_id):
            yield ev

    # ================= 生成流程 =================
    async def _answer_flow(
        self,
        faq: FAQItem,
        history: list[dict],
        query: str,
        emotion: str,
        results: Optional[list[dict]] = None,
        confirmed: bool = False,
        message_id: str = "",
    ) -> AsyncGenerator[dict, None]:
        results = results or [{"faq": faq, "dense_score": 1.0, "bm25_score": 0.0, "combined": 1.0}]
        confidence = results[0]["dense_score"]

        # 幽默开关：只有售前类 + 情绪绿灯 才允许幽默点缀（设计稿 6.4）
        humor_on = faq.category in _HUMOR_ALLOWED_CATEGORIES and emotion == "LEVEL_0"
        # 严肃场景（售后/交易/账户）强制正经：humor_rule 视同情绪不佳处理
        system = build_system_prompt("LEVEL_0" if humor_on else "LEVEL_2")

        ctx = format_context(results)
        hist = format_history(history)
        user_prompt = (
            f"（用户刚确认了上面的问题，请直接给出完整答案）{query}" if confirmed else query
        )
        system = system.format(context=ctx, history=hist, query=user_prompt)
        messages = [{"role": "system", "content": system}]
        # 注意：历史只注入 system 的 history 字段（供理解上下文），
        # 不再追加独立 assistant 历史消息——避免 LLM 紧邻生成位复读上一条回复
        messages.append({"role": "user", "content": user_prompt})

        yield {
            "type": "meta",
            "data": {
                "status": "answering",
                "emotion": emotion,
                "intent": "IN_KNOWLEDGE",
                "confidence": round(confidence, 3),
                "faq_ids": [r["faq"].id for r in results],
                "faqs": [
                    {"id": r["faq"].id, "title": r["faq"].category_zh, "score": round(r["dense_score"], 2)}
                    for r in results[:1]
                ],
                "handover": False,
                "quick_replies": [],
                "humor": humor_on,
            },
        }

        full = ""
        try:
            async for token in llm.stream_chat(messages, temperature=0.4 if humor_on else 0.2):
                full += token
                yield {"type": "text", "data": {"content": token}}
        except Exception as exc:
            logger.error("生成失败：%s", exc)
            full = UNKNOWN_FALLBACK_MSG
            yield {"type": "text", "data": {"content": full}}

        # 输出校验：关键事实必须能在知识库找到依据
        if not verify_facts(full, results):
            logger.warning("疑似幻觉，回退兜底话术：%s", full[:80])
            full = UNKNOWN_FALLBACK_MSG
            yield {"type": "text", "data": {"content": full}}
            yield {"type": "done", "data": {"message_id": message_id, "handover": True,
                                             "handover_reason": "hallucination_fallback",
                                             "handover_summary": build_handover_summary(query, history, results)}}
            return

        yield {
            "type": "done",
            "data": {
                "message_id": message_id,
                "handover": False,
                "handover_reason": "",
                "handover_summary": build_handover_summary(query, history, results),
                "clear_pending": True,
            },
        }

    # ================= 软转人工（澄清式挽留，5.7/6.2）=================
    async def _soft_handover(
        self,
        query: str,
        history: list[dict],
        results: list[dict],
        emotion: str = "LEVEL_0",
        reason: str = "low_confidence",
        message_id: str = "",
    ) -> AsyncGenerator[dict, None]:
        confidence = results[0]["dense_score"] if results else 0.0
        quick_replies: list[dict] = []
        if len(results) >= 2:
            a = _shorten(results[0]["faq"].standard_question)
            b = _shorten(results[1]["faq"].standard_question)
            text = HANDOVER_SOFT_MSG.format(brand=settings.BRAND_NAME, topic_a=a, topic_b=b)
            quick_replies = [
                {"label": a, "value": results[0]["faq"].standard_question},
                {"label": "直接找人工", "value": "转人工"},
            ]
        else:
            text = UNKNOWN_FALLBACK_MSG

        yield {
            "type": "meta",
            "data": {
                "status": "confirming",
                "emotion": emotion,
                "intent": "OUT_OF_SCOPE" if not results else "LOW_CONFIDENCE",
                "confidence": round(confidence, 3),
                "faq_ids": [r["faq"].id for r in results],
                "handover": False,
                "quick_replies": quick_replies,
                "handover_reason": reason,
            },
        }
        for chunk in _chunk_text(text):
            yield {"type": "text", "data": {"content": chunk}}
        yield {
            "type": "done",
            "data": {
                "message_id": message_id,
                "handover": True,
                "handover_reason": reason,
                "handover_summary": build_handover_summary(query, history, results),
            },
        }

    # ================= 硬转人工（红灯 / 高风险 / 主动要求）=================
    async def _hard_handover(
        self,
        query: str,
        history: list[dict],
        reason: str,
        emotion: str = "LEVEL_0",
        faq: Optional[FAQItem] = None,
        message_id: str = "",
    ) -> AsyncGenerator[dict, None]:
        if reason == "emotion_red":
            text = RED_LIGHT_MSG
        elif reason == "high_risk_faq":
            text = faq.answer if faq else RED_LIGHT_MSG
        elif reason == "user_request":
            text = HANDOVER_HARD_MSG
        else:
            text = UNKNOWN_FALLBACK_MSG

        quick_replies = settings.HANDOVER_QUICK_REPLIES
        yield {
            "type": "meta",
            "data": {
                "status": "handover",
                "emotion": emotion,
                "intent": "HIGH_RISK" if reason in ("emotion_red", "high_risk_faq") else "HANDOVER_REQUEST",
                "confidence": 0.0,
                "faq_ids": [faq.id] if faq else [],
                "handover": True,
                "quick_replies": quick_replies,
                "handover_reason": reason,
            },
        }
        for chunk in _chunk_text(text):
            yield {"type": "text", "data": {"content": chunk}}
        yield {
            "type": "done",
            "data": {
                "message_id": message_id,
                "handover": True,
                "handover_reason": reason,
                "handover_summary": build_handover_summary(query, history, [{"faq": faq}] if faq else []),
            },
        }


def _chunk_text(text: str, size: int = 12) -> list[str]:
    """把固定话术切成小块，模拟流式（无 LLM 调用时前端打字机仍有动效）。"""
    return [text[i:i + size] for i in range(0, len(text), size)]
