"""分层记忆（plan 5.4，V1.5 多轮记忆）：

- L1 短期记忆：最近 N 轮完整对话（已有滑动窗口，本模块不重复处理）
- L2 中期记忆：超出窗口的早期对话压缩成 ≤100 字摘要（增量合并，避免重复压缩）
- L3 结构化事实：从对话中提取订单号/型号/诉求等 Key-Value 事实，覆盖式更新

生成时由 orchestrator 把 summary + facts 注入 System Prompt，保证 >5 轮的长对话不丢上下文。
Mock 模式下返回稳定占位，离线链路行为不变。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from app.agent.llm import llm
from app.agent.prompts import MEMORY_FACTS_PROMPT, MEMORY_SUMMARY_PROMPT

logger = logging.getLogger(__name__)

_EMPTY_FACTS = {"user_intent": "", "order_info": "无", "product": "无", "request": "无"}

FACT_KEYS = ("user_intent", "order_info", "product", "request")


def _format_history(messages: list[dict]) -> str:
    lines = []
    for m in messages[-12:]:
        role = "用户" if m["role"] == "user" else "客服"
        lines.append(f"{role}：{m['content'][:80]}")
    return "\n".join(lines) if lines else "（无）"


async def extract_facts(messages: list[dict], prev: Optional[dict] = None) -> dict:
    """L3：提取结构化事实。prev 为已有事实，LLM 输出非法时回退保留旧值。"""
    if not messages:
        return dict(prev or _EMPTY_FACTS)
    try:
        out = await llm.complete(
            [{"role": "user", "content": MEMORY_FACTS_PROMPT.format(history=_format_history(messages))}],
            temperature=0.0,
            max_tokens=160,
        )
        data = json.loads(out.strip().strip("`").replace("```json", "").replace("```", "").strip() or "{}")
        if not isinstance(data, dict):
            raise ValueError("facts 不是 JSON 对象")
        merged = dict(prev or _EMPTY_FACTS)
        for k in FACT_KEYS:
            v = str(data.get(k, "")).strip()
            if v and v != "无":
                merged[k] = v[:60]
        return merged
    except Exception as exc:
        logger.warning("L3 事实提取失败，沿用旧值：%s", exc)
        return dict(prev or _EMPTY_FACTS)


async def compress_history(messages: list[dict], prev_summary: str = "") -> str:
    """L2：把早期对话压缩成摘要。若已有旧摘要，与新增部分一起合并压缩（增量式）。"""
    if not messages:
        return prev_summary
    text = _format_history(messages)
    if prev_summary:
        text = f"已有摘要：{prev_summary}\n\n新增对话：\n{text}"
    try:
        out = await llm.complete(
            [{"role": "user", "content": MEMORY_SUMMARY_PROMPT.format(history=text)}],
            temperature=0.2,
            max_tokens=120,
        )
        out = out.strip()
        return out[:160] if out else prev_summary
    except Exception as exc:
        logger.warning("L2 摘要压缩失败，沿用旧摘要：%s", exc)
        return prev_summary


def window_size() -> int:
    """窗口外消息条数阈值（1 轮 = user + assistant 2 条）。"""
    from app.config import settings

    return settings.HISTORY_WINDOW_TURNS * 2


def needs_summary(total_messages: int) -> bool:
    """历史消息数超过窗口（开始有被裁掉的早期对话）时才维护 L2 摘要。"""
    return total_messages > window_size()
