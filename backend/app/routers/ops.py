"""运营统计（轻量看板）：自动化率 / 转人工率 / 点赞率 / 排队进度 / 坐席待办。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.storage.db import db

router = APIRouter(prefix="/api/v1", tags=["ops"])


@router.get("/ops/stats")
async def ops_stats():
    """核心口径：只要会话发生转人工，整个会话归入转人工，不计入自动化率。

    自动化率 + 转人工率 = 100%
    """
    stats = db.session_stats()
    stats["handover_rate"] = round(1.0 - stats["auto_rate"], 4)
    # V1.5：点赞率（feedback 口径）
    stats.update(db.feedback_stats())
    return stats


@router.get("/ops/handovers")
async def ops_handovers(status: str = "waiting"):
    """人工坐席待办列表（留言模式）：客服端拉取后主动回复。"""
    return db.list_handovers(status)


@router.get("/ops/badcases")
async def ops_badcases(limit: int = 20):
    """点踩记录（Bad Case 归因原料，运营看板用）。"""
    return db.list_badcases(limit)


@router.get("/ops/queue/status")
async def ops_queue_status(queue_id: int):
    """V1.5 排队进度：用户侧轮询「前面还有几人」。"""
    st = db.queue_status(queue_id)
    if st is None:
        raise HTTPException(status_code=404, detail="queue item not found")
    return st


@router.post("/ops/handovers/{queue_id}/complete")
async def ops_handover_complete(queue_id: int):
    """V1.5 坐席工作台：标记待办完成。"""
    if not db.complete_handover(queue_id):
        raise HTTPException(status_code=404, detail="handover not found or already done")
    return {"ok": True, "queue_id": queue_id}
