"""核心对话路由：/api/v1/chat/init、/api/v1/chat/stream(SSE)、/api/v1/handover。"""
from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.agent.orchestrator import Orchestrator
from app.config import settings
from app.models.schemas import ChatInitRequest, ChatInitResponse, ChatStreamRequest, HandoverRequest, HandoverResponse
from app.storage.db import db, new_session_id
from app.storage.kb import kb
from app.storage.rate_limit import generate_visitor_token, verify_visitor_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["chat"])

orchestrator = Orchestrator(kb)


@router.post("/chat/init", response_model=ChatInitResponse)
async def chat_init(req: ChatInitRequest):
    """页面初始化：创建/恢复会话，下发 Visitor Token，拉取历史（解决视觉失忆）。"""
    session_id = req.session_id or new_session_id()
    session = db.get_session(session_id)
    if session is None:
        db.create_session(session_id, user_id=req.user_id)
    elif req.user_id and not session.get("user_id"):
        db.bind_user(session_id, req.user_id)

    history = db.get_history(session_id, limit=20)
    return ChatInitResponse(
        session_id=session_id,
        visitor_token=generate_visitor_token(session_id),
        brand_name=settings.BRAND_NAME,
        quick_chips=settings.QUICK_CHIPS,
        history=history,
        status=(db.get_session(session_id) or {}).get("status", "AGENT_ACTIVE"),
    )


def _sse(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(req: ChatStreamRequest, request: Request):
    """核心对话接口：POST + SSE 流式返回回答与状态变更。

    防御（2.6）：
    - Visitor Token 校验（无 Token 的裸 curl 直接拒绝）
    - IP 限流在中间件层
    - 会话 30 轮硬上限 / 输入超长拦截（不调 LLM）
    """
    # 1) 访客 Token 校验
    if not verify_visitor_token(req.visitor_token, req.session_id):
        raise HTTPException(status_code=401, detail="invalid visitor token")

    # 2) 会话存在性
    session = db.get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    # 3) 输入长度拦截（撑爆 Context 的乱码）
    if len(req.message) > settings.MAX_INPUT_LEN:
        return StreamingResponse(
            _sse("meta", {"status": "blocked", "handover": False, "quick_replies": []})
            + _sse("text", {"content": "这条消息有点长啦，方便分几条发给我吗？"})
            + _sse("done", {"message_id": "", "handover": False}),
            media_type="text/event-stream",
        )

    # 4) 会话轮次硬上限（成本熔断）
    turn_count = session.get("turn_count", 0)
    if turn_count >= settings.SESSION_MAX_TURNS:
        return StreamingResponse(
            _sse("meta", {"status": "limit", "handover": False, "quick_replies": settings.HANDOVER_QUICK_REPLIES})
            + _sse("text", {"content": "您今天咨询的次数有点多啦～如需继续，请登录账号或转接人工，小助手会继续为您服务。"})
            + _sse("done", {"message_id": "", "handover": False}),
            media_type="text/event-stream",
        )

    # 5) 落库：用户消息
    db.add_message(req.session_id, "user", req.message)
    db.update_session(req.session_id, turn_count=turn_count + 1)

    # 6) 生成 assistant message_id，装配上下文
    assistant_id = f"msg_{uuid.uuid4().hex[:16]}"
    history = db.get_history(req.session_id, limit=settings.HISTORY_WINDOW_TURNS * 2 + 2)
    history = [{"role": m["role"], "content": m["content"]} for m in history]

    async def event_stream():
        full_text = ""
        handover = False
        handover_summary = ""
        session_status = "AGENT_ACTIVE"

        try:
            async for ev in orchestrator.process_turn(
                query=req.message,
                history=history[:-1],  # 去掉刚写入的当前用户消息（已在 query 中）
                session_status=session.get("status", "AGENT_ACTIVE"),
                session_meta=session.get("meta", {}),
                message_id=assistant_id,
            ):
                if ev["type"] == "text":
                    full_text += ev["data"]["content"]
                elif ev["type"] == "done":
                    handover = bool(ev["data"].get("handover"))
                    handover_summary = ev["data"].get("handover_summary", "")
                    if ev["data"].get("clear_pending"):
                        meta = dict(session.get("meta", {}))
                        meta.pop("pending_faq_id", None)
                        db.update_session(req.session_id, meta=meta, status="AGENT_ACTIVE")
                yield _sse(ev["type"], ev["data"])
        finally:
            # 落库：assistant 消息
            if full_text:
                db.add_message(req.session_id, "assistant", full_text)

        # 转人工：状态打标 + 排队登记（留言转人工）
        if handover:
            session_status = "HANDOVER"
            db.update_session(req.session_id, status="HANDOVER")
            db.enqueue_handover(req.session_id, handover_summary or req.message)
        else:
            db.update_session(req.session_id, status=session_status)

        # 追加一条 summary 事件，供前端展示转人工状态（可选）
        if handover:
            yield _sse("summary", {
                "message": "已转人工排队（留言模式）",
                "queue_id": None,
                "session_status": "HANDOVER",
            })

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/handover", response_model=HandoverResponse)
async def handover(req: HandoverRequest):
    """手动触发转人工 + 预留言。"""
    if not verify_visitor_token(req.visitor_token, req.session_id):
        raise HTTPException(status_code=401, detail="invalid visitor token")
    session = db.get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    history = db.get_history(req.session_id, limit=8)
    summary = "用户主动申请转人工。" + "；".join(
        f"{'用户' if m['role'] == 'user' else '客服'}：{m['content'][:50]}" for m in history[-4:]
    )
    qid = db.enqueue_handover(req.session_id, summary, req.contact)
    db.update_session(req.session_id, status="HANDOVER")
    return HandoverResponse(queue_id=qid, message="已登记，人工客服上线后会第一时间回复您。")
