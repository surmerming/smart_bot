"""运行控制：Kill Switch + 灰度开关（V2.0 容错机制 / 灰度上线）。

服务模式（Kill Switch）：
    auto      正常：RAG + 自动回答 + 转人工决策全开
    handover  全局转人工：不再走检索/LLM，所有对话直接转人工登记（半切，保业务不丢）
    off       维护模式：完全下线，回复维护话术，不登记不调 LLM（全切）

灰度开关：
    gray_percent 0-100：按 session_id 稳定哈希分流，命中灰度组的会话在 init 响应
    与 SSE meta 中标注 gray=true（可观测），未来接新逻辑时按此分流放量。

所有状态内存化（单实例），与 plan「灰度上线：10% 流量灰度 → 全量」对齐；
生产多实例时可扩展为 Redis 共享。
"""
from __future__ import annotations

import hashlib
import logging

logger = logging.getLogger(__name__)

_MODES = ("auto", "handover", "off")


class RuntimeControl:
    def __init__(self) -> None:
        self._mode: str = "auto"
        self._gray_percent: int = 0

    # ---------- 服务模式（Kill Switch） ----------
    @property
    def mode(self) -> str:
        return self._mode

    def set_mode(self, mode: str) -> bool:
        if mode not in _MODES:
            return False
        if mode != self._mode:
            logger.warning("运行模式切换: %s -> %s（Kill Switch）", self._mode, mode)
        self._mode = mode
        return True

    @property
    def is_handover_all(self) -> bool:
        """全局转人工：所有对话直接转人工登记。"""
        return self._mode == "handover"

    @property
    def is_offline(self) -> bool:
        """维护模式：服务完全下线。"""
        return self._mode == "off"

    # ---------- 灰度开关 ----------
    @property
    def gray_percent(self) -> int:
        return self._gray_percent

    def set_gray_percent(self, percent: int) -> bool:
        if not isinstance(percent, int) or not 0 <= percent <= 100:
            return False
        self._gray_percent = percent
        return True

    def is_gray_session(self, session_id: str) -> bool:
        """按 session_id 稳定哈希分流（同一会话全程同组，不抖动）。"""
        if self._gray_percent <= 0:
            return False
        if self._gray_percent >= 100:
            return True
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 100
        return bucket < self._gray_percent

    # ---------- 状态快照 ----------
    def state(self) -> dict:
        return {
            "mode": self._mode,
            "gray_percent": self._gray_percent,
            "kill_switch": self._mode != "auto",
        }


runtime = RuntimeControl()
