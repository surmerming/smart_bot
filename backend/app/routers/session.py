"""会话绑定与反馈路由：/api/v1/session/bind、/api/v1/feedback。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import FeedbackRequest, FeedbackResponse, SessionBindRequest, SessionBindResponse
from app.storage.db import db

router = APIRouter(prefix="/api/v1", tags=["session"])


@router.post("/session/bind", response_model=SessionBindResponse)
async def session_bind(req: SessionBindRequest):
    """登录瞬间绑定：anonymous_session_id ↔ user_id，历史聊天零丢失。"""
    session = db.get_session(req.anonymous_session_id)
    if session is None:
        # 未登录过：用匿名 ID 建会话
        db.create_session(req.anonymous_session_id, user_id=req.user_id)
        return SessionBindResponse(session_id=req.anonymous_session_id, user_id=req.user_id)
    db.bind_user(req.anonymous_session_id, req.user_id)
    return SessionBindResponse(session_id=req.anonymous_session_id, user_id=req.user_id)


@router.post("/feedback", response_model=FeedbackResponse)
async def feedback(req: FeedbackRequest):
    """点赞/点踩埋点：点踩自动打标入库，供 Bad Case 归因。"""
    fid = db.add_feedback(
        session_id=req.session_id,
        message_id=req.message_id,
        value=req.value,
        query=req.query,
        context=req.context,
        answer=req.answer,
    )
    return FeedbackResponse(feedback_id=fid)
