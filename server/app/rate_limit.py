"""
速率限制配置

基于 slowapi，使用内存存储（单实例足够，多实例需切换 Redis 后端）。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import Request
from fastapi.responses import JSONResponse

# 全局 limiter 实例
limiter = Limiter(key_func=get_remote_address)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """统一的速率限制超限响应"""
    return JSONResponse(
        status_code=429,
        content={
            "detail": f"请求过于频繁，请稍后再试。限制: {exc.detail}"
        },
    )
