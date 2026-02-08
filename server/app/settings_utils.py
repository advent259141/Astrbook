"""
公共设置工具函数

将 _get_setting / _set_setting 提取为共享模块，
支持批量查询以减少 DB 往返。
"""

from sqlalchemy.orm import Session
from .models import SystemSettings


def get_setting(db: Session, key: str, default: str = "") -> str:
    """获取单个设置值"""
    setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    return setting.value if setting and setting.value else default


def get_settings_batch(db: Session, keys: list[str], defaults: dict[str, str] | None = None) -> dict[str, str]:
    """
    批量获取多个设置值（1 次 WHERE IN 查询）

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
