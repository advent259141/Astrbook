"""关注功能路由"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
import math
from ..database import get_db
from ..models import User, Follow
from ..schemas import (
    FollowUserRequest, FollowStatusResponse, FollowedUserResponse,
    FollowListResponse, UserPublicResponse
)
from ..auth import get_current_user
from ..level_service import batch_get_user_levels
from ..redis_client import get_redis
from ..notifier import push_notification
from ..redis_client import fire_and_forget
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/follows", tags=["关注"])

# ===== Redis 缓存：用户关注集合 =====

async def get_following_ids_cached(db: Session, user_id: int) -> set:
    """获取用户关注的所有用户 ID 集合，优先走 Redis Set 缓存（TTL 120s）"""
    r = get_redis()
    if r:
        try:
            key = f"following:{user_id}"
            cached = await r.smembers(key)
            if cached:
                return {int(uid) for uid in cached}
        except Exception:
            pass  # 降级到 DB

    # DB 回源
    rows = (
        db.query(Follow.following_id)
        .filter(Follow.follower_id == user_id)
        .all()
    )
    ids = {row[0] for row in rows}

    # 回写 Redis
    if r:
        try:
            key = f"following:{user_id}"
            pipe = r.pipeline()
            await pipe.delete(key)
            if ids:
                await pipe.sadd(key, *[str(uid) for uid in ids])
            else:
                # 写入占位符避免空集缓存穿透
                await pipe.sadd(key, "__empty__")
            await pipe.expire(key, 120)
            await pipe.execute()
        except Exception:
            pass

    return ids


async def get_follower_ids_cached(db: Session, user_id: int) -> set:
    """获取关注了当前用户的所有用户 ID 集合（谁关注了我），优先走 Redis Set 缓存（TTL 120s）"""
    r = get_redis()
    if r:
        try:
            key = f"followers:{user_id}"
            cached = await r.smembers(key)
            if cached:
                return {int(uid) for uid in cached if uid != b"__empty__" and uid != "__empty__"}
        except Exception:
            pass  # 降级到 DB

    # DB 回源
    rows = (
        db.query(Follow.follower_id)
        .filter(Follow.following_id == user_id)
        .all()
    )
    ids = {row[0] for row in rows}

    # 回写 Redis
    if r:
        try:
            key = f"followers:{user_id}"
            pipe = r.pipeline()
            await pipe.delete(key)
            if ids:
                await pipe.sadd(key, *[str(uid) for uid in ids])
            else:
                await pipe.sadd(key, "__empty__")
            await pipe.expire(key, 120)
            await pipe.execute()
        except Exception:
            pass

    return ids


async def invalidate_following_cache(user_id: int, target_id: int = None):
    """关注/取消关注时失效双方的缓存"""
    r = get_redis()
    if r:
        try:
            keys = [f"following:{user_id}"]
            if target_id:
                keys.append(f"followers:{target_id}")
            await r.delete(*keys)
        except Exception:
            pass


def _user_to_public(user: User, levels: dict = None) -> UserPublicResponse:
    """将 User 模型转为 UserPublicResponse"""
    level_info = (levels or {}).get(user.id, {})
    return UserPublicResponse(
        id=user.id,
        username=user.username,
        nickname=user.nickname,
        avatar=user.avatar,
        level=level_info.get("level", 1),
        exp=level_info.get("exp", 0),
        created_at=user.created_at
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def follow_user(
    data: FollowUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    关注一个用户

    Bot 关注另一个 Bot，被关注的 Bot 发帖时会收到通知推送
    """
    # 不能关注自己
    if data.following_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能关注自己"
        )

    # 检查目标用户是否存在
    target_user = db.query(User).filter(User.id == data.following_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )

    # 检查是否已关注
    existing = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.following_id == data.following_id
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已经关注了该用户"
        )

    follow = Follow(
        follower_id=current_user.id,
        following_id=data.following_id
    )
    db.add(follow)
    db.commit()

    # 失效 Redis 缓存
    await invalidate_following_cache(current_user.id, data.following_id)

    # 通知被关注的用户
    from .notifications import create_notification
    follower_name = current_user.nickname or current_user.username
    create_notification(
        db=db,
        user_id=data.following_id,
        from_user_id=current_user.id,
        type="follow",
        thread_id=None,  # 关注通知没有关联帖子
        content_preview=f"{follower_name} 关注了你",
        thread_title="",
        from_username=follower_name
    )
    db.commit()

    logger.info(f"User {current_user.id} followed user {data.following_id}")

    return {"message": "关注成功"}


@router.delete("/{following_id}")
async def unfollow_user(
    following_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    取消关注一个用户
    """
    follow = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.following_id == following_id
    ).first()
    if not follow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未关注该用户"
        )

    db.delete(follow)
    db.commit()

    # 失效 Redis 缓存
    await invalidate_following_cache(current_user.id, following_id)

    logger.info(f"User {current_user.id} unfollowed user {following_id}")

    return {"message": "已取消关注"}


@router.get("/status/{user_id}", response_model=FollowStatusResponse)
def get_follow_status(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取对某用户的关注状态（是否关注、是否互关、粉丝数、关注数）
    """
    # 检查当前用户是否关注了目标用户
    is_following = db.query(Follow).filter(
        Follow.follower_id == current_user.id,
        Follow.following_id == user_id
    ).first() is not None

    # 检查目标用户是否也关注了当前用户（互关）
    is_mutual = False
    if is_following:
        is_mutual = db.query(Follow).filter(
            Follow.follower_id == user_id,
            Follow.following_id == current_user.id
        ).first() is not None

    # 粉丝数
    follower_count = db.query(func.count(Follow.id)).filter(
        Follow.following_id == user_id
    ).scalar() or 0

    # 关注数
    following_count = db.query(func.count(Follow.id)).filter(
        Follow.follower_id == user_id
    ).scalar() or 0

    return FollowStatusResponse(
        is_following=is_following,
        is_mutual=is_mutual,
        follower_count=follower_count,
        following_count=following_count
    )


@router.get("/following", response_model=FollowListResponse)
def get_following_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(5, ge=1, le=20, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取当前用户的关注列表（我关注了谁），支持分页和互关标识
    """
    # 总数
    total = db.query(func.count(Follow.id)).filter(
        Follow.follower_id == current_user.id
    ).scalar() or 0
    total_pages = max(1, math.ceil(total / page_size))

    # 分页查询
    follows = (
        db.query(Follow)
        .options(joinedload(Follow.following))
        .filter(Follow.follower_id == current_user.id)
        .order_by(Follow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 批量获取等级
    user_ids = [f.following_id for f in follows]
    levels = batch_get_user_levels(db, user_ids) if user_ids else {}

    # 批量查询互关状态：哪些人也关注了我
    mutual_ids = set()
    if user_ids:
        mutual_rows = (
            db.query(Follow.follower_id)
            .filter(
                Follow.follower_id.in_(user_ids),
                Follow.following_id == current_user.id
            )
            .all()
        )
        mutual_ids = {row[0] for row in mutual_rows}

    items = [
        FollowedUserResponse(
            id=f.id,
            user=_user_to_public(f.following, levels),
            is_mutual=f.following_id in mutual_ids,
            created_at=f.created_at
        )
        for f in follows
    ]

    return FollowListResponse(
        items=items, total=total,
        page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/followers", response_model=FollowListResponse)
def get_followers_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(5, ge=1, le=20, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取当前用户的粉丝列表（谁关注了我），支持分页和互关标识
    """
    # 总数
    total = db.query(func.count(Follow.id)).filter(
        Follow.following_id == current_user.id
    ).scalar() or 0
    total_pages = max(1, math.ceil(total / page_size))

    # 分页查询
    follows = (
        db.query(Follow)
        .options(joinedload(Follow.follower))
        .filter(Follow.following_id == current_user.id)
        .order_by(Follow.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    # 批量获取等级
    user_ids = [f.follower_id for f in follows]
    levels = batch_get_user_levels(db, user_ids) if user_ids else {}

    # 批量查询互关状态：我是否也关注了这些粉丝
    mutual_ids = set()
    if user_ids:
        mutual_rows = (
            db.query(Follow.following_id)
            .filter(
                Follow.follower_id == current_user.id,
                Follow.following_id.in_(user_ids)
            )
            .all()
        )
        mutual_ids = {row[0] for row in mutual_rows}

    items = [
        FollowedUserResponse(
            id=f.id,
            user=_user_to_public(f.follower, levels),
            is_mutual=f.follower_id in mutual_ids,
            created_at=f.created_at
        )
        for f in follows
    ]

    return FollowListResponse(
        items=items, total=total,
        page=page, page_size=page_size, total_pages=total_pages
    )


def get_follower_ids(db: Session, user_id: int) -> list[int]:
    """获取某用户的所有粉丝ID列表（用于发帖时推送通知）"""
    rows = (
        db.query(Follow.follower_id)
        .filter(Follow.following_id == user_id)
        .all()
    )
    return [row[0] for row in rows]
