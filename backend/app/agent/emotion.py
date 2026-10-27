"""情绪分级：LLM 分级判断为主（5.6），关键词兜底兜住极端场景。

LEVEL_0 正常 / LEVEL_1 轻微不满 / LEVEL_2 明显生气 / LEVEL_3 严重投诉。
"""
from __future__ import annotations

import logging

from app.agent.llm import llm
from app.agent.prompts import EMOTION_PROMPT
from app.storage.kb import has_risk_keyword

logger = logging.getLogger(__name__)

# 兜底关键词（仅用于 LLM 不可用时，避免漏掉红灯场景）
_RED_FALLBACK = ["12315", "315", "曝光", "投诉", "举报", "起诉", "报警", "诈骗", "等着瞧", "媒体", "记者"]
_YELLOW_FALLBACK = ["怎么还没", "等很久", "几天了", "还不发货", "太慢了", "怎么回事", "什么破", "再也不买"]


def _keyword_fallback(query: str) -> str:
    if any(k in query for k in _RED_FALLBACK):
        return "LEVEL_3"
    if any(k in query for k in _YELLOW_FALLBACK):
        return "LEVEL_2"
    if has_risk_keyword(query):
        return "LEVEL_3"
    return "LEVEL_0"


async def classify_emotion(query: str) -> str:
    """返回 LEVEL_0 ~ LEVEL_3。"""
    try:
        label = await llm.complete(
            [{"role": "user", "content": EMOTION_PROMPT.format(query=query)}],
            temperature=0.0,
            max_tokens=8,
        )
        label = label.strip().upper()
        if label.startswith("LEVEL_"):
            level = label[:7]
            if level in {"LEVEL_0", "LEVEL_1", "LEVEL_2", "LEVEL_3"}:
                return level
        # LLM 输出异常时回退关键词
        logger.warning("情绪分级输出异常：%r，回退关键词", label)
    except Exception as exc:
        logger.warning("情绪分级调用失败，回退关键词：%s", exc)
    return _keyword_fallback(query)
