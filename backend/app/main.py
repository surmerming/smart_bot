"""FastAPI 入口：注册路由、IP 限流中间件、CORS、知识库加载、健康检查。"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.storage.kb import kb
from app.storage.rate_limit import rate_limiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="小答 AI 客服 Agent", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 全局知识库（启动时构建一次；MVP 数据量小，全量重建毫秒级）
kb.load(str(settings.KB_PATH))
logger.info("知识库加载完成：%d 条 FAQ，分类 %s", len(kb.faqs), kb.category_stats())


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """网关层 IP 限流：10 次/分钟/IP（2.6 第二层）。"""
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        ok, remaining = rate_limiter.allow(ip)
        if not ok:
            return JSONResponse(
                status_code=429,
                content={"detail": "请求太频繁啦，请稍后再试", "remaining": remaining},
            )
    response = await call_next(request)
    return response


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "brand": settings.BRAND_NAME,
        "llm_mode": "real" if settings.use_real_llm else "mock",
        "faqs": len(kb.faqs),
    }


from app.routers import chat, ops, session  # noqa: E402

app.include_router(chat.router)
app.include_router(session.router)
app.include_router(ops.router)
