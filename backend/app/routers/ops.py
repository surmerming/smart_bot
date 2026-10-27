"""运营统计 + 坐席工作台（V1.5 看板 / V2.0 Copilot）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.storage.db import db

logger = logging.getLogger(__name__)
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
    """V1.5 坐席工作台：标记待办完成，并触发 WebSocket 广播（人工已接入/位置前移）。"""
    row = db.get_handover(queue_id)
    if not row or not db.complete_handover(queue_id):
        raise HTTPException(status_code=404, detail="handover not found or already done")
    from app.routers.ws import manager

    await manager.broadcast_handover_done(queue_id, row["session_id"])
    return {"ok": True, "queue_id": queue_id}


# ================= V2.0 坐席 AI Copilot =================
@router.get("/ops/copilot/{queue_id}")
async def ops_copilot(queue_id: int):
    """工单卡片：未生成则现场生成（转人工后一般已异步生成）。"""
    row = db.get_handover(queue_id)
    if not row:
        raise HTTPException(status_code=404, detail="queue item not found")
    copilot = db.get_handover_copilot(queue_id)
    if not copilot:
        from app.agent.copilot import build_copilot_for

        copilot = await build_copilot_for(queue_id, row["session_id"])
    return {"queue_id": queue_id, "session_id": row["session_id"], "copilot": copilot}


@router.post("/ops/copilot/templates")
async def ops_copilot_templates(queue_id: int):
    """生成 3 个快捷回复模板（坐席一键复制）。"""
    row = db.get_handover(queue_id)
    if not row:
        raise HTTPException(status_code=404, detail="queue item not found")
    copilot = db.get_handover_copilot(queue_id) or {}
    ticket = copilot.get("ticket")
    templates = copilot.get("templates")
    if not templates:
        from app.agent.copilot import extract_ticket, generate_templates

        if not ticket:
            history = db.get_history(row["session_id"], limit=12)
            ticket = await extract_ticket(
                [{"role": m["role"], "content": m["content"]} for m in history]
            )
        templates = await generate_templates(ticket)
        copilot["ticket"] = ticket
        copilot["templates"] = templates
        db.set_copilot(queue_id, copilot)
    return {"queue_id": queue_id, "templates": templates}


@router.post("/ops/copilot/query")
async def ops_copilot_query(queue_id: int, action: str = "logistics"):
    """坐席一键查询内部系统（开发期 Mock 数据，生产接真实 API）。"""
    row = db.get_handover(queue_id)
    if not row:
        raise HTTPException(status_code=404, detail="queue item not found")
    from app.agent.copilot import mock_inner_query

    copilot = db.get_handover_copilot(queue_id)
    order_info = (copilot or {}).get("ticket", {}).get("order_info", "")
    if not order_info:
        history = db.get_history(row["session_id"], limit=12)
        from app.agent.copilot import extract_ticket

        ticket = await extract_ticket([{"role": m["role"], "content": m["content"]} for m in history])
        order_info = ticket.get("order_info", "")
    return mock_inner_query(action, order_info)
