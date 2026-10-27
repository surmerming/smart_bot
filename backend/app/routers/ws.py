"""WebSocket 实时通道（plan V2.0 转人工实时排队）：

- `/ws/user?session_id=&visitor_token=`  用户端：转人工后建立，实时接收排队位置 / 人工接入事件
- `/ws/agent?token=`                      坐席端：实时接收新待办 / 完成事件，首帧下发待办快照

事件协议（JSON）：
    用户端：{"type":"queue","queue_id":155,"position":3,"ahead":2,"status":"waiting"}
            {"type":"agent_joined","queue_id":155}
    坐席端：{"type":"handovers","data":[...]}       # 首帧快照
            {"type":"handover_new","queue_id":155}
            {"type":"handover_done","queue_id":155}

降级：前端 WebSocket 失败时自动回退 HTTP 轮询（V1.5 逻辑保留）。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import settings
from app.storage.db import db
from app.storage.rate_limit import verify_visitor_token

logger = logging.getLogger(__name__)
router = APIRouter(tags=["ws"])


class ConnectionManager:
    def __init__(self) -> None:
        self._users: dict[str, set[WebSocket]] = {}
        self._agents: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    # ---- 连接管理 ----
    async def connect_user(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._users.setdefault(session_id, set()).add(ws)

    async def connect_agent(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._agents.add(ws)

    async def disconnect_user(self, session_id: str, ws: WebSocket) -> None:
        async with self._lock:
            conns = self._users.get(session_id)
            if conns:
                conns.discard(ws)
                if not conns:
                    self._users.pop(session_id, None)

    async def disconnect_agent(self, ws: WebSocket) -> None:
        async with self._lock:
            self._agents.discard(ws)

    # ---- 推送 ----
    async def push_user(self, session_id: str, data: dict) -> None:
        async with self._lock:
            conns = list(self._users.get(session_id, set()))
        for ws in conns:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:  # pragma: no cover
                pass

    async def broadcast_agent(self, data: dict) -> None:
        async with self._lock:
            conns = list(self._agents)
        for ws in conns:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:  # pragma: no cover
                pass

    # ---- 事件 ----
    async def notify_user_queue(self, session_id: str) -> None:
        """向某用户推送其当前排队进度（入队 / 前面有人完成时调用）。"""
        row = db.get_waiting_by_session(session_id)
        if not row:
            return
        st = db.queue_status(row["id"])
        if st:
            await self.push_user(session_id, {
                "type": "queue", "queue_id": st["queue_id"],
                "position": st["position"], "ahead": st["ahead"], "status": st["status"],
            })

    async def notify_user_agent_joined(self, session_id: str, queue_id: int) -> None:
        await self.push_user(session_id, {"type": "agent_joined", "queue_id": queue_id})

    async def broadcast_new_handover(self, queue_id: int) -> None:
        await self.broadcast_agent({"type": "handover_new", "queue_id": queue_id})

    async def broadcast_handover_done(self, queue_id: int, session_id: str) -> None:
        await self.broadcast_agent({"type": "handover_done", "queue_id": queue_id})
        await self.notify_user_agent_joined(session_id, queue_id)
        # 前面有人完成 → 其余在等用户位置前移
        for sid in list(self._users):
            await self.notify_user_queue(sid)


manager = ConnectionManager()


@router.websocket("/ws/user")
async def ws_user(websocket: WebSocket, session_id: str = "", visitor_token: str = ""):
    """用户端：转人工排队实时进度。Token 校验失败直接关闭。"""
    if not session_id or not verify_visitor_token(visitor_token, session_id):
        await websocket.close(code=4401)
        return
    await manager.connect_user(session_id, websocket)
    # 建连即推送一次当前排队状态（弥补连接前的变化）
    await manager.notify_user_queue(session_id)
    try:
        while True:
            # 只消费心跳/关闭信号，业务推送全部由服务端主动发起
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect_user(session_id, websocket)


@router.websocket("/ws/agent")
async def ws_agent(websocket: WebSocket, token: str = ""):
    """坐席端：待办实时广播。配置了 AGENT_WS_TOKEN 时需匹配，留空=开发期放行。"""
    if settings.AGENT_WS_TOKEN and token != settings.AGENT_WS_TOKEN:
        await websocket.close(code=4401)
        return
    await manager.connect_agent(websocket)
    # 首帧：待办快照
    try:
        await websocket.send_text(json.dumps(
            {"type": "handovers", "data": db.list_handovers("waiting")}, ensure_ascii=False,
        ))
    except Exception:  # pragma: no cover
        pass
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect_agent(websocket)
