"""
Redis 连接管理器

- 提供全局连接池（decode_responses=True）
- 支持 Redis 不可用时的优雅降级
- 提供 get_redis() 依赖注入
"""

import logging
import redis.asyncio as aioredis
from typing import Optional
from .config import get_settings

logger = logging.getLogger(__name__)

_pool: Optional[aioredis.Redis] = None


async def init_redis():
    """初始化 Redis 连接池（app startup 时调用）"""
    global _pool
    settings = get_settings()
    if not settings.REDIS_URL:
        logger.info("[Redis] REDIS_URL 未配置，Redis 缓存已禁用")
        return
    try:
        _pool = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            max_connections=20
        )
        await _pool.ping()
        logger.info(f"[Redis] 连接成功: {settings.REDIS_URL}")
    except Exception as e:
        logger.warning(f"[Redis] 连接失败，将降级回本地模式: {e}")
        _pool = None


async def close_redis():
    """关闭 Redis 连接池（app shutdown 时调用）"""
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None


def get_redis() -> Optional[aioredis.Redis]:
    """获取 Redis 客户端，未初始化或连接失败返回 None"""
    return _pool
