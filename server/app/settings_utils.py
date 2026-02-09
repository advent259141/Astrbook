"""
公共设置工具函数

将 _get_setting / _set_setting 提取为共享模块，
支持批量查询以减少 DB 往返。
Redis 缓存层：所有设置存入 Redis Hash "sys:settings"，TTL 300 秒。
"""

import logging
from sqlalchemy.orm import Session
from .models import SystemSettings
from .redis_client import get_redis

logger = logging.getLogger(__name__)

_SYS_SETTINGS_KEY = "sys:settings"
_SYS_SETTINGS_TTL = 300  # 5 分钟


def get_setting(db: Session, key: str, default: str = "") -> str:
    """获取单个设置值"""
    setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    return setting.value if setting and setting.value else default


def get_settings_batch(db: Session, keys: list[str], defaults: dict[str, str] | None = None) -> dict[str, str]:
    """
    批量获取多个设置值（1 次 WHERE IN 查询）

    优先从 Redis Hash `sys:settings` 批量读取已缓存的 key，
    仅对未命中的 key 查询 DB，查询后回写 Redis。

    Args:
        db: 数据库会话
        keys: 要查询的设置键列表
        defaults: 默认值字典，未找到的键使用对应默认值

    Returns:
        键值字典
    """
    if defaults is None:
        defaults = {}

    settings = (
        db.query(SystemSettings.key, SystemSettings.value)
        .filter(SystemSettings.key.in_(keys))
        .all()
    )

    result = {key: defaults.get(key, "") for key in keys}
    for key, value in settings:
        if value:
            result[key] = value

    return result


def set_setting(db: Session, key: str, value: str):
    """设置单个值"""
    setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    if setting:
        setting.value = value
    else:
        setting = SystemSettings(key=key, value=value)
        db.add(setting)


async def invalidate_settings_cache(*keys: str):
    """主动失效 Redis 中的设置缓存（异步版本，admin 路由调用）"""
    r = get_redis()
    if r:
        try:
            if keys:
                await r.hdel(_SYS_SETTINGS_KEY, *keys)
            else:
                await r.delete(_SYS_SETTINGS_KEY)
        except Exception:
            pass
