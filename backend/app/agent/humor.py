"""幽默分段生成（5.5）：事实版回答 → 幽默润色 → 关键信息一致性校验，不一致回退事实版。

数字 / 时间 / 金额 / 规则 用【】锁定，润色不许动。
"""
from __future__ import annotations

import logging
import re

from app.agent.llm import llm
from app.agent.prompts import POLISH_PROMPT

logger = logging.getLogger(__name__)

_NUMBER_RE = re.compile(r"\d+(?:[.\-]\d+)*(?:%|折|元|块|天|小时|年|月|个|位|次|分钟)?")


def _normalize(text: str) -> str:
    """去空白/全半角归一，使「24 小时」与「24小时」指纹一致。"""
    text = re.sub(r"\s+", "", text)
    return text.replace("：", ":").replace("（", "(").replace("）", ")")


def extract_key_facts(text: str) -> set[str]:
    """抽取关键事实指纹：数字范围 + 单位（容忍数字与单位间空格）。"""
    return set(_NUMBER_RE.findall(_normalize(text)))


async def polish_answer(fact_answer: str, query: str) -> str:
    """对事实版做幽默润色；校验关键数字一致，不一致回退事实版。"""
    if len(fact_answer) < 6:
        return fact_answer
    facts_before = extract_key_facts(fact_answer)
    try:
        polished = await llm.complete(
            [{"role": "user", "content": POLISH_PROMPT.format(fact_answer=fact_answer)}],
            temperature=0.8,
            max_tokens=120,
        )
    except Exception as exc:
        logger.warning("幽默润色失败，回退事实版：%s", exc)
        return fact_answer

    polished = polished.strip()
    if not polished:
        return fact_answer
    # 校验：关键数字/时间/金额/规则不得被改动
    facts_after = extract_key_facts(polished)
    if not facts_before.issubset(facts_after):
        logger.info("润色版改变了关键事实（%s → %s），回退事实版", facts_before, facts_after)
        return fact_answer
    # 防风格溢出：长度暴增（编造细节）也回退
    if len(polished) > len(fact_answer) * 2 + 30:
        return fact_answer
    return polished
