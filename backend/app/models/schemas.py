"""Pydantic 请求/响应模型：前后端契约的唯一来源。"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- 请求 ----------
class ChatInitRequest(BaseModel):
    """页面初始化（可带历史 session_id，用于刷新恢复）。"""
    session_id: Optional[str] = Field(None, description="已有会话 ID，恢复历史用")
    user_id: Optional[str] = Field(None, description="已登录用户 ID，可选")


class ChatStreamRequest(BaseModel):
    """核心对话接口：发送 Query。"""
    session_id: str = Field(..., min_length=8, max_length=64)
    message: str = Field(..., min_length=1, max_length=2000)
    visitor_token: str = Field(..., min_length=8, max_length=256)


class SessionBindRequest(BaseModel):
    """登录瞬间绑定：anonymous_session_id ↔ user_id。"""
    anonymous_session_id: str = Field(..., min_length=8, max_length=64)
    user_id: str = Field(..., min_length=1, max_length=64)


class FeedbackRequest(BaseModel):
    """点赞/点踩埋点。"""
    session_id: str = Field(..., min_length=8, max_length=64)
    message_id: Optional[str] = None
    value: Literal["up", "down"]
    query: Optional[str] = None
    context: Optional[str] = None
    answer: Optional[str] = None


class HandoverRequest(BaseModel):
    """手动触发转人工 + 预留言。"""
    session_id: str = Field(..., min_length=8, max_length=64)
    visitor_token: str = Field(..., min_length=8, max_length=256)
    contact: Optional[str] = Field(None, max_length=64, description="手机号/邮箱，可选")


# ---------- 响应 ----------
class ChatInitResponse(BaseModel):
    session_id: str
    visitor_token: str
    expires_in: int = 86400
    brand_name: str
    quick_chips: list
    history: list  # [{role, content, created_at}]
    status: str = "AGENT_ACTIVE"


class SessionBindResponse(BaseModel):
    ok: bool = True
    session_id: str
    user_id: str


class FeedbackResponse(BaseModel):
    ok: bool = True
    feedback_id: Optional[int] = None


class HandoverResponse(BaseModel):
    ok: bool = True
    queue_id: Optional[int] = None
    message: str = ""
