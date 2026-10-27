"""运营统计 + 坐席工作台 + 运行控制（V1.5 看板 / V2.0 Copilot + Kill Switch + Bad Case + CSAT）。"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.models.schemas import BadCaseStatusRequest, CsatSubmitRequest, RuntimeUpdateRequest
from app.storage.db import db
from app.storage.rate_limit import verify_visitor_token
from app.storage.runtime_control import runtime

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["ops"])


# ================= V2.0 运行控制（Kill Switch + 灰度开关）=================
@router.get("/ops/runtime")
async def ops_runtime():
    """当前服务模式与灰度状态（运营看板运行控制面板）。"""
    return runtime.state()


@router.put("/ops/runtime")
async def ops_runtime_update(req: RuntimeUpdateRequest):
    """一键切换：mode=auto 正常 / handover 全局转人工 / off 维护下线；gray_percent 灰度放量比例。"""
    if req.mode is not None and not runtime.set_mode(req.mode):
        raise HTTPException(status_code=400, detail="invalid mode, must be auto/handover/off")
    if req.gray_percent is not None and not runtime.set_gray_percent(req.gray_percent):
        raise HTTPException(status_code=400, detail="invalid gray_percent, must be 0-100")
    return runtime.state()


# ================= V2.0 Bad Case 管理 =================
@router.post("/ops/badcases/{feedback_id}/status")
async def ops_badcase_status(feedback_id: int, req: BadCaseStatusRequest):
    """运营标记点踩记录处理状态：open / resolved / ignored + 备注。"""
    if not db.set_badcase_status(feedback_id, req.status, req.note):
        raise HTTPException(status_code=404, detail="badcase not found or invalid status")
    return {"ok": True, "feedback_id": feedback_id, "status": req.status, "note": req.note}


# ================= V2.0 CSAT 满意度 =================
@router.post("/csat")
async def csat_submit(req: CsatSubmitRequest):
    """满意度打分（widget 弹出）：需有效 Visitor Token + 1-5 星。"""
    if req.visitor_token and not verify_visitor_token(req.visitor_token, req.session_id):
        raise HTTPException(status_code=401, detail="invalid visitor token")
    if not db.add_csat(req.session_id, req.rating, req.comment):
        raise HTTPException(status_code=400, detail="rating must be 1-5")
    return {"ok": True, "rating": req.rating}


@router.get("/ops/csat")
async def ops_csat():
    """满意度统计：总量 / 平均分 / 星级分布。"""
    return db.csat_stats()


@router.get("/ops/stats")
async def ops_stats():
    """核心口径：只要会话发生转人工，整个会话归入转人工，不计入自动化率。

    自动化率 + 转人工率 = 100%
    """
    stats = db.session_stats()
    stats["handover_rate"] = round(1.0 - stats["auto_rate"], 4)
    # V1.5：点赞率（feedback 口径）
    stats.update(db.feedback_stats())
    # V2.0：CSAT 满意度
    stats.update(db.csat_stats())
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
