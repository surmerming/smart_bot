"""安全防刷（2.6 四层防御的 MVP 极简版）：
1) IP 令牌桶限流（内存实现，生产换 Redis）
2) 动态 Visitor Token（HMAC 签名，绑定 session_id + 过期时间）
3) 会话轮次硬上限 / 输入超长拦截（在 router 层执行）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from collections import defaultdict, deque

from app.config import settings


# ---------- IP 限流：令牌桶（滑动窗口）----------
class IPRateLimiter:
    """单 IP 每分钟最多 N 条消息，超限返回是否放行。"""

    def __init__(self, limit_per_min: int = 10) -> None:
        self.limit = limit_per_min
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock_time: dict[str, float] = {}

    def allow(self, ip: str) -> tuple[bool, int]:
        """返回 (是否放行, 剩余配额)。"""
        now = time.monotonic()
        window = now - 60.0
        q = self._hits[ip]
        while q and q[0] < window:
            q.popleft()
        if len(q) >= self.limit:
            return False, 0
        q.append(now)
        return True, self.limit - len(q)


# ---------- Visitor Token（动态签名令牌）----------
def _sign(payload: str) -> str:
    return hmac.new(
        settings.VISITOR_TOKEN_SECRET.encode(), payload.encode(), hashlib.sha256
    ).hexdigest()


def generate_visitor_token(session_id: str, ttl_hours: int | None = None) -> str:
    """token = base64(payload).signature，payload = {session_id, exp}。"""
    ttl = ttl_hours or settings.VISITOR_TOKEN_TTL_HOURS
    exp = int(time.time()) + ttl * 3600
    payload = base64.urlsafe_b64encode(
        json.dumps({"s": session_id, "e": exp}, separators=(",", ":")).encode()
    ).decode()
    sig = _sign(payload)
    return f"{payload}.{sig}"


def verify_visitor_token(token: str, session_id: str) -> bool:
    """校验签名 + 会话匹配 + 未过期。裸 curl 不带 Token 直接拒绝。"""
    try:
        payload, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(_sign(payload), sig):
            return False
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        if data.get("s") != session_id:
            return False
        if int(data.get("e", 0)) < time.time():
            return False
        return True
    except Exception:
        return False


rate_limiter = IPRateLimiter(settings.RATE_LIMIT_PER_MIN)
