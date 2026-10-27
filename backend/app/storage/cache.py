"""高频问题秒回缓存（plan V1.5 缓存优化：Top 20 高频问题命中秒回）。

设计：
- key：规范化 query（jieba 分词 + 停用词过滤后 join），口语变体/标点差异可归一
- 仅缓存「自动回答」结果（handover=False），且仅用于会话首轮（多轮上下文不适用）
- 容量上限淘汰：命中次数最少且最久未命中的优先淘汰
- 失效：知识库重建（kb.version 变化）→ 整体清空，防止过期口径被秒回
"""
from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)


def normalize_query(query: str) -> str:
    """规范化查询：分词 + 停用词过滤 + 去除纯标点 token，作为缓存 key。

    例：「拆了包装还能退吗」「拆了包装还能退吗？」→ 同一 key。
    """
    import re

    from app.storage.kb import tokenize

    return " ".join(
        w for w in tokenize(query) if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", w)
    )


class AnswerCache:
    def __init__(self, max_entries: int = 20) -> None:
        self._max = max_entries
        self._data: "OrderedDict[str, dict]" = OrderedDict()
        self._version = -1  # 首次使用时强制与 kb.version 对齐

    def _sync_version(self, kb_version: int) -> None:
        if kb_version != self._version:
            self._data.clear()
            self._version = kb_version

    def get(self, key: str, kb_version: int) -> Optional[dict]:
        """命中返回缓存条目（meta + answer），并更新命中统计。"""
        self._sync_version(kb_version)
        entry = self._data.get(key)
        if entry is None:
            return None
        entry["count"] += 1
        entry["last_ts"] = time.time()
        return entry

    def put(self, key: str, kb_version: int, meta: dict, answer: str) -> None:
        """写入缓存条目（仅自动回答结果）。"""
        self._sync_version(kb_version)
        if not answer:
            return
        if key in self._data:
            return
        if len(self._data) >= self._max:
            self._evict()
        self._data[key] = {"meta": meta, "answer": answer, "count": 1, "last_ts": time.time()}

    def _evict(self) -> None:
        victim = min(self._data.items(), key=lambda kv: (kv[1]["count"], kv[1]["last_ts"]))
        del self._data[victim[0]]

    def clear(self) -> None:
        self._data.clear()

    def stats(self) -> dict:
        return {
            "size": len(self._data),
            "max": self._max,
            "hits_total": sum(max(e["count"] - 1, 0) for e in self._data.values()),
        }


answer_cache = AnswerCache(max_entries=settings.CACHE_MAX_ENTRIES)
