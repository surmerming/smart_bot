"""意图识别与语义校验：置信度分级（2.3 方案 A）+ LLM 布尔判断（5.9 第二层）+ NLI 蕴含校验（5.2）。

决策矩阵（plan 5.9 两级判断）：
- 最高相似度 < SIM_THRESHOLD_LOW      → 不能回答（转人工），零 LLM 调用
- 最高相似度 SIM_THRESHOLD_LOW~HIGH   → LLM can_answer 布尔判断
- 最高相似度 > SIM_THRESHOLD_HIGH     → 高置信直接生成
- 检测到否定词 → 强制 NLI 校验，CONTRADICTION 转人工
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agent.llm import llm
from app.agent.prompts import CAN_ANSWER_PROMPT, INTENT_PROMPT, NLI_PROMPT
from app.config import settings
from app.storage.kb import FAQItem, has_negation, has_risk_keyword, wants_human

logger = logging.getLogger(__name__)


@dataclass
class RetrievalVerdict:
    """检索后的决策结论。"""
    decision: str  # answer / ask_llm / handover / confirming
    faqs: list[dict] = None
    confidence: float = 0.0
    reason: str = ""


def decide(query: str, results: list[dict]) -> RetrievalVerdict:
    """基于相似度两级阈值 + 否定词检测 做快速决策（零 LLM 调用路径）。"""
    if not results:
        return RetrievalVerdict("handover", results, 0.0, "no_candidate")

    top = results[0]
    score = top["dense_score"]
    low = settings.SIM_THRESHOLD_LOW
    high = settings.SIM_THRESHOLD_HIGH

    # 否定句：词面重合但语义可能相反 → 强制走 LLM NLI 校验
    if has_negation(query):
        return RetrievalVerdict("ask_llm", results, score, "negation_nli")

    if score < low:
        return RetrievalVerdict("handover", results, score, "low_confidence")
    if score <= high:
        return RetrievalVerdict("ask_llm", results, score, "mid_confidence")
    return RetrievalVerdict("answer", results, score, "high_confidence")


async def can_answer(query: str, results: list[dict]) -> bool:
    """第二层：快速模型布尔判断知识库能否回答。"""
    from app.agent.prompts import format_context

    ctx = format_context(results)
    try:
        out = await llm.complete(
            [{"role": "user", "content": CAN_ANSWER_PROMPT.format(query=query, context=ctx)}],
            temperature=0.0,
            max_tokens=8,
        )
        return out.strip().lower().startswith("true")
    except Exception as exc:
        logger.warning("can_answer 调用失败，按可回答处理：%s", exc)
        return True


async def nli_check(query: str, faq: FAQItem) -> str:
    """NLI 蕴含判断：ENTAILMENT / CONTRADICTION / NEUTRAL。"""
    try:
        out = await llm.complete(
            [{"role": "user", "content": NLI_PROMPT.format(query=query, answer=faq.answer)}],
            temperature=0.0,
            max_tokens=8,
        )
        label = out.strip().upper()
        if label.startswith("ENTAILMENT"):
            return "ENTAILMENT"
        if label.startswith("CONTRADICTION"):
            return "CONTRADICTION"
        return "NEUTRAL"
    except Exception as exc:
        logger.warning("NLI 校验失败，按 ENTAILMENT 处理：%s", exc)
        return "ENTAILMENT"


async def classify_intent(query: str) -> str:
    """意图分类（可选叠加）：IN_KNOWLEDGE / OUT_OF_SCOPE / HIGH_RISK。"""
    try:
        out = await llm.complete(
            [{"role": "user", "content": INTENT_PROMPT.format(query=query)}],
            temperature=0.0,
            max_tokens=8,
        )
        label = out.strip().upper()
        for k in ("IN_KNOWLEDGE", "OUT_OF_SCOPE", "HIGH_RISK"):
            if label.startswith(k):
                return k
    except Exception as exc:
        logger.warning("意图分类调用失败：%s", exc)
    # 兜底：风险词 → HIGH_RISK；主动转人工 → HANDOVER；否则 IN_KNOWLEDGE
    if has_risk_keyword(query):
        return "HIGH_RISK"
    if wants_human(query):
        return "HANDOVER"
    return "IN_KNOWLEDGE"
