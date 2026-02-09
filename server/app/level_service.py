"""
等级系统服务模块

提供经验值计算、等级升级、每日限制等功能。
Redis 缓存层：level:{user_id} → Hash { level, exp }，TTL 30 分钟。
"""

import logging
from datetime import date
from sqlalchemy.orm import Session
from .models import UserLevel, User
from .schemas import UserPublicResponse
from .redis_client import get_redis

logger = logging.getLogger(__name__)

_LEVEL_CACHE_TTL = 1800  # 30 分钟


# 经验获取规则
EXP_POST = 4       # 发帖经验
EXP_REPLY = 3      # 回帖经验
EXP_LIKED = 2      # 被点赞经验

# 每日经验上限
DAILY_POST_EXP_CAP = 32   # 发帖每日上限 (8帖 * 4经验)
DAILY_REPLY_EXP_CAP = 30  # 回帖每日上限 (10回复 * 3经验)


def exp_for_level(level: int) -> int:
    """升到该等级需要的累积经验（立方公式）"""
    return level ** 3


def calculate_level(total_exp: int) -> int:
    """根据总经验计算等级"""
    level = 1
    while (level + 1) ** 3 <= total_exp:
        level += 1
    return level


def get_next_level_exp(current_level: int) -> int:
    """获取升到下一级需要的累积经验"""
    return (current_level + 1) ** 3


def get_or_create_user_level(db: Session, user_id: int) -> UserLevel:
    """获取或创建用户等级信息"""
    user_level = db.query(UserLevel).filter(UserLevel.user_id == user_id).first()
    if not user_level:
        user_level = UserLevel(user_id=user_id, exp=0, level=1)
        db.add(user_level)
        db.flush()
    return user_level


def reset_daily_limits_if_needed(user_level: UserLevel) -> None:
    """如果日期变化，重置每日经验限制"""
    today = date.today()
    if user_level.last_exp_date != today:
        user_level.today_post_exp = 0
        user_level.today_reply_exp = 0
        user_level.last_exp_date = today


def _invalidate_level_cache(user_id: int):
    """经验变动后失效 Redis 缓存"""
    r = get_redis()
    if r:
        from .redis_client import fire_and_forget
        fire_and_forget(r.delete(f"level:{user_id}"))


def add_exp_for_post(db: Session, user_id: int) -> tuple[int, bool]:
    """
    发帖获得经验
    
    Returns:
        (获得的经验值, 是否升级)
    """
    user_level = get_or_create_user_level(db, user_id)
    reset_daily_limits_if_needed(user_level)
    
    # 检查每日上限
    if user_level.today_post_exp >= DAILY_POST_EXP_CAP:
        return 0, False
    
    # 计算实际获得的经验（可能因上限而减少）
    remaining = DAILY_POST_EXP_CAP - user_level.today_post_exp
    actual_exp = min(EXP_POST, remaining)
    
    # 增加经验
    old_level = user_level.level
    user_level.exp += actual_exp
    user_level.today_post_exp += actual_exp
    user_level.level = calculate_level(user_level.exp)
    
    # 失效 Redis 缓存
    if actual_exp > 0:
        _invalidate_level_cache(user_id)
    
    return actual_exp, user_level.level > old_level


def add_exp_for_reply(db: Session, user_id: int) -> tuple[int, bool]:
    """
    回帖/楼中楼获得经验
    
    Returns:
        (获得的经验值, 是否升级)
    """
    user_level = get_or_create_user_level(db, user_id)
    reset_daily_limits_if_needed(user_level)
    
    # 检查每日上限
    if user_level.today_reply_exp >= DAILY_REPLY_EXP_CAP:
        return 0, False
    
    # 计算实际获得的经验
    remaining = DAILY_REPLY_EXP_CAP - user_level.today_reply_exp
    actual_exp = min(EXP_REPLY, remaining)
    
    # 增加经验
    old_level = user_level.level
    user_level.exp += actual_exp
    user_level.today_reply_exp += actual_exp
    user_level.level = calculate_level(user_level.exp)
    
    # 失效 Redis 缓存
    if actual_exp > 0:
        _invalidate_level_cache(user_id)
    
    return actual_exp, user_level.level > old_level


def add_exp_for_being_liked(db: Session, user_id: int) -> tuple[int, bool]:
    """
    被点赞获得经验（无每日上限）
    
    Returns:
        (获得的经验值, 是否升级)
    """
    user_level = get_or_create_user_level(db, user_id)
    
    # 增加经验（无上限）
    old_level = user_level.level
    user_level.exp += EXP_LIKED
    user_level.level = calculate_level(user_level.exp)
    
    # 失效 Redis 缓存
    _invalidate_level_cache(user_id)
    
    return EXP_LIKED, user_level.level > old_level


def get_user_level_info(db: Session, user_id: int) -> dict:
    """
    获取用户等级信息
    
    Returns:
        {
            "level": 当前等级,
            "exp": 当前经验,
            "next_level_exp": 下一级所需经验,
            "today_post_exp": 今日发帖已获经验,
            "today_reply_exp": 今日回帖已获经验
        }
    """
    user_level = get_or_create_user_level(db, user_id)
    reset_daily_limits_if_needed(user_level)
    
    return {
        "level": user_level.level,
        "exp": user_level.exp,
        "next_level_exp": get_next_level_exp(user_level.level),
        "today_post_exp": user_level.today_post_exp,
        "today_reply_exp": user_level.today_reply_exp,
        "daily_post_exp_cap": DAILY_POST_EXP_CAP,
        "daily_reply_exp_cap": DAILY_REPLY_EXP_CAP,
    }


def get_user_with_level(db: Session, user: User) -> UserPublicResponse:
    """
    获取用户响应，包含等级信息
    """
    level_info = get_or_create_user_level(db, user.id)
    response = UserPublicResponse.model_validate(user)
    response.level = level_info.level
    response.exp = level_info.exp
    return response


def batch_get_user_levels(db: Session, user_ids: list) -> dict:
    """
    批量获取用户等级信息（优先 Redis MGET，miss 查 DB 并回写）
    
    Returns:
        {user_id: {"level": x, "exp": y}, ...}
    """
    if not user_ids:
        return {}
    
    result = {}
    missing_ids = list(user_ids)
    r = get_redis()
    
    # 尝试从 Redis 批量读取
    if r:
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            # 使用同步上下文中的 fire-and-forget 模式不可行，
            # 因为需要返回值。batch_get_user_levels 被同步调用，
            # 所以只能在有 running loop 时尝试。
            # 但该函数的调用方（threads 路由）现在是 async，
            # 实际上无法直接 await。保留 DB 查询为主路径，
            # Redis 仅用于写入缓存以供下次命中。
        except RuntimeError:
            pass
    
    # DB 查询（主路径）
    user_levels = db.query(UserLevel).filter(UserLevel.user_id.in_(user_ids)).all()
    result = {ul.user_id: {"level": ul.level, "exp": ul.exp} for ul in user_levels}
    
    # 对于没有等级信息的用户，返回默认值
    for uid in user_ids:
        if uid not in result:
            result[uid] = {"level": 1, "exp": 0}
    
    # 异步回写 Redis（fire-and-forget）
    if r and result:
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            async def _write_cache():
                try:
                    pipe = r.pipeline()
                    for uid, info in result.items():
                        key = f"level:{uid}"
                        pipe.hset(key, mapping={"level": str(info["level"]), "exp": str(info["exp"])})
                        pipe.expire(key, _LEVEL_CACHE_TTL)
                    await pipe.execute()
                except Exception:
                    pass
            loop.create_task(_write_cache())
        except (RuntimeError, Exception):
            pass
    
    return result
