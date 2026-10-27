"""运营统计（轻量看板）：自动化率 / 转人工率 按 6.1 科学口径。"""
from __future__ import annotations

from fastapi import APIRouter

from app.storage.db import db

router = APIRouter(prefix="/api/v1", tags=["ops"])


@router.get("/ops/stats")
async def ops_stats():
    """核心口径：只要会话发生转人工，整个会话归入转人工，不计入自动化率。

    自动化率 + 转人工率 = 100%
    """
    stats = db.session_stats()
    stats["handover_rate"] = round(1.0 - stats["auto_rate"], 4)
    return stats


@router.get("/ops/handovers")
async def ops_handovers(status: str = "waiting"):
    """人工坐席待办列表（MVP 留言模式）：客服端拉取后主动回复。"""
    return db.list_handovers(status)
