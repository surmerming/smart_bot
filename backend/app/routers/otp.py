"""OTP 聊天内验证（plan 3.1-5② 账户安全场景：忘记密码 / 修改手机号）。

流程：识别敏感意图 → 引导提供手机号 → otp/send 下发验证码 → 用户输入 → otp/verify 校验。
校验通过后会话标记 otp_verified 临时状态（含时间戳），未来敏感操作 API 以此为门禁；
会话结束 / 超时后状态自然失效（验证码 TTL 过期即销毁）。

演示模式（OTP_MOCK_MODE=true，默认）：短信服务未接入，响应直接返回验证码并标注演示，
用于开发联调与 UI 验证；生产设 OTP_MOCK_MODE=false 后不返回 code，需接入真实短信通道。
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models.schemas import OtpSendRequest, OtpVerifyRequest
from app.storage.db import db
from app.storage.rate_limit import verify_visitor_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1", tags=["otp"])


def _gen_code() -> str:
    return f"{secrets.randbelow(1000000):06d}"


@router.post("/otp/send")
async def otp_send(req: OtpSendRequest):
    """下发验证码：session 内暂存（含过期时间），Mock 模式直接返回 code。"""
    if not verify_visitor_token(req.visitor_token, req.session_id):
        raise HTTPException(status_code=401, detail="invalid visitor token")
    session = db.get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    code = _gen_code()
    expires_at = (datetime.now() + timedelta(minutes=settings.OTP_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
    meta = dict(session.get("meta", {}))
    meta["otp_pending"] = {"code": code, "phone": req.phone, "expires_at": expires_at}
    db.update_session(req.session_id, meta=meta)
    logger.info("OTP 下发：session=%s phone=%s expires=%s", req.session_id, req.phone, expires_at)

    resp = {"ok": True, "sent": True, "ttl_minutes": settings.OTP_TTL_MINUTES}
    if settings.OTP_MOCK_MODE:
        resp["code"] = code  # 演示模式直接返回，生产不返回
        resp["mock"] = True
    return resp


@router.post("/otp/verify")
async def otp_verify(req: OtpVerifyRequest):
    """校验验证码：通过 → 会话标记 otp_verified 临时状态（10 分钟有效，超时销毁）。"""
    if not verify_visitor_token(req.visitor_token, req.session_id):
        raise HTTPException(status_code=401, detail="invalid visitor token")
    session = db.get_session(req.session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")

    meta = dict(session.get("meta", {}))
    pending = meta.get("otp_pending")
    if not pending:
        raise HTTPException(status_code=400, detail="no otp sent, please request a code first")
    if pending.get("phone") != req.phone:
        raise HTTPException(status_code=400, detail="phone mismatch")
    try:
        expired = datetime.now() > datetime.strptime(pending["expires_at"], "%Y-%m-%d %H:%M:%S")
    except ValueError:  # pragma: no cover
        expired = True
    if expired:
        meta.pop("otp_pending", None)
        db.update_session(req.session_id, meta=meta)
        raise HTTPException(status_code=410, detail="otp expired, please request a new code")
    if secrets.compare_digest(str(pending["code"]), req.code):
        # 校验通过：写入临时安全状态（TTL 同验证码），清除待验证码
        meta.pop("otp_pending", None)
        meta["otp_verified"] = {"phone": req.phone, "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        db.update_session(req.session_id, meta=meta)
        return {"ok": True, "verified": True, "ttl_minutes": settings.OTP_TTL_MINUTES}
    raise HTTPException(status_code=400, detail="invalid code")
