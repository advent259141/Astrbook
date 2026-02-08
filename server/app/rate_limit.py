"""
速率限制配置

基于 slowapi，支持 Redis 后端（多实例共享限流计数器）。
当 REDIS_URL 配置时使用 Redis 存储，否则降级为内存存储。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse
from .config import get_settings

_settings = get_settings()

# 全局 limiter 实例（Redis 可用时使用 Redis 存储，否则内存存储）
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=_settings.REDIS_URL if _settings.REDIS_URL else "memory://",
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """统一的速率限制超限响应"""
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"请求过于频繁，请稍后再试。限制: {exc.detail}"
        },
    )
