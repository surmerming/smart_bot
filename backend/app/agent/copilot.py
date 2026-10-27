"""坐席 AI Copilot（plan V2.0 / 6.6）：

1. 结构化工单卡片：转人工后异步用 LLM 把会话压缩成 {user_intent, order_info, bot_answered, issue}
2. 快捷回复模板：坐席点击时按诉求 + 知识库生成 3 个模板，一键复制
3. 内部系统查询（演示）：提取订单号 → Mock 查物流/订单，标注开发期数据

Mock 模式下全部规则化返回，离线可跑通。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.agent.llm import llm
from app.agent.prompts import COPILOT_TEMPLATES_PROMPT, SUMMARY_PROMPT
from app.storage.kb import kb

logger = logging.getLogger(__name__)

_TICKET_KEYS = ("user_intent", "order_info", "bot_answered", "issue")


async def extract_ticket(messages: list[dict]) -> dict:
    """工单卡片：LLM 结构化摘要。解析失败返回最小可用卡片。"""
    history = "\n".join(
        f"{'用户' if m['role'] == 'user' else '客服'}：{m['content'][:80]}" for m in messages[-12:]
    ) or "（无）"
    try:
        out = await llm.complete(
            [{"role": "user", "content": SUMMARY_PROMPT.format(history=history)}],
            temperature=0.0,
            max_tokens=160,
        )
        data = json.loads(out.strip().strip("`").replace("```json", "").replace("```", "").strip() or "{}")
        if not isinstance(data, dict):
            raise ValueError("ticket 不是 JSON")
        ticket = {}
        for k in _TICKET_KEYS:
            v = str(data.get(k, "")).strip()
            if v and v != "无":
                ticket[k] = v[:80]
        if ticket.get("user_intent"):
            return ticket
    except Exception as exc:
        logger.warning("Copilot 工单卡片生成失败：%s", exc)
    # 兜底：从对话抽取
    return {
        "user_intent": (messages[-1]["content"][:60] if messages else ""),
        "order_info": _extract_order(messages),
        "bot_answered": "（待人工查看对话记录）",
        "issue": "（待人工确认）",
    }


def _extract_order(messages: list[dict]) -> str:
    text = " ".join(m.get("content", "") for m in messages)
    m = re.search(r"[A-Za-z]{1,6}\d{8,}", text)
    return m.group(0) if m else "无"


async def generate_templates(ticket: dict, top_k: int = 3) -> list[str]:
    """3 个快捷回复模板（坐席一键复制）。"""
    ticket_text = json.dumps(ticket, ensure_ascii=False) if ticket else "客户未说明诉求"
    ctx = kb.search((ticket.get("user_intent") or ticket.get("issue") or "")[:50], top_k=2)
    kb_text = "\n".join(f"- {r['faq'].standard_question}：{r['faq'].answer[:60]}" for r in ctx) or "（无）"
    try:
        out = await llm.complete(
            [{"role": "user", "content": COPILOT_TEMPLATES_PROMPT.format(
                ticket=ticket_text, kb_context=kb_text,
            )}],
            temperature=0.4,
            max_tokens=200,
        )
        lines = [ln.strip() for ln in out.split("|") if ln.strip()]
        return lines[:3] or ["已收到您的反馈，正在为您加急处理～"]
    except Exception as exc:
        logger.warning("Copilot 回复模板生成失败：%s", exc)
        return ["已收到您的反馈，正在为您加急处理～"]


async def build_copilot_for(queue_id: int, session_id: str) -> dict:
    """为转人工队列项生成工单卡片并落库（转人工后异步调用，不阻塞 SSE）。"""
    from app.storage.db import db

    history = db.get_history(session_id, limit=16)
    messages = [{"role": m["role"], "content": m["content"]} for m in history]
    ticket = await extract_ticket(messages)
    copilot = {"ticket": ticket}
    db.set_copilot(queue_id, copilot)
    return copilot


# ---------- 内部系统查询（开发期 Mock，生产接入真实 API）----------
_ACTIONS = {
    "logistics": "物流进度",
    "order": "订单详情",
    "refund": "退款状态",
}


def mock_inner_query(action: str, order_info: str) -> dict:
    """Mock 内部系统查询结果（明确标注开发期演示数据）。"""
    order = re.search(r"[A-Za-z]{1,6}\d{8,}", order_info or "")
    order_no = order.group(0) if order else "（未提取到订单号）"
    if action == "logistics":
        body = f"【开发期演示】订单 {order_no} 当前已到达深圳转运中心，预计明天送达，请客户保持电话畅通。"
    elif action == "refund":
        body = f"【开发期演示】订单 {order_no} 退款申请已受理，预计 1-3 个工作日原路退回。"
    else:
        body = f"【开发期演示】订单 {order_no} 状态：已支付 / 待发货，商品：小答周边礼盒 ×1。"
    return {"action": _ACTIONS.get(action, action), "result": body, "mock": True}
