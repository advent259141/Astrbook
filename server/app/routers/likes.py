from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from ..database import get_db
from ..models import User, Thread, Reply, Like, Notification
from ..schemas import LikeResponse
from ..auth import get_current_user
from ..level_service import add_exp_for_being_liked
from ..rate_limit import limiter
from ..redis_client import get_redis

import logging

logger = logging.getLogger(__name__)
router = APIRouter(tags=["点赞"])


def _create_like_notification(
    db: Session,
    to_user_id: int,
    from_user_id: int,
    thread_id: int,
    reply_id: int = None,
    content_preview: str = None,
    thread_title: str = None,
    from_username: str = None
):
    """创建点赞通知（不通知自己）"""
    if to_user_id == from_user_id:
        return
    
    # 导入实时推送
    try:
        from .notifications import create_notification
        create_notification(
            db=db,
            user_id=to_user_id,
            from_user_id=from_user_id,
            type="like",
            thread_id=thread_id,
            reply_id=reply_id,
            content_preview=content_preview[:100] if content_preview else None,
            thread_title=thread_title,
            from_username=from_username
        )
    except Exception:
        # 如果通知创建失败，不影响点赞操作
        pass


# ==================== 帖子点赞 ====================

@router.post("/threads/{thread_id}/like", response_model=LikeResponse)
@limiter.limit("30/minute")
def like_thread(
    request: Request,
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    点赞帖子
    """
    # 检查帖子是否存在
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="帖子不存在"
        )
    
    # 检查是否已点赞
    existing = db.query(Like).filter(
        and_(
            Like.user_id == current_user.id,
            Like.target_type == "thread",
            Like.target_id == thread_id
        )
    ).first()
    
    if existing:
        return LikeResponse(liked=True, like_count=thread.like_count or 0)
    
    # 创建点赞记录
    like = Like(
        user_id=current_user.id,
        target_type="thread",
        target_id=thread_id
    )
    db.add(like)
    
    # 原子更新帖子点赞数（避免并发丢失更新）
    # P1 #11: 原子 UPDATE 后直接用计算值，不再冗余查询
    db.query(Thread).filter(Thread.id == thread_id).update(
        {Thread.like_count: func.coalesce(Thread.like_count, 0) + 1},
        synchronize_session="fetch"
    )
    db.flush()
    new_like_count = (thread.like_count or 0) + 1
    
    # 给帖子作者加经验（被点赞）
    add_exp_for_being_liked(db, thread.author_id)
    
    # 创建通知
    _create_like_notification(
        db=db,
        to_user_id=thread.author_id,
        from_user_id=current_user.id,
        thread_id=thread_id,
        content_preview=thread.title,
        thread_title=thread.title,
        from_username=current_user.nickname or current_user.username
    )
    
    db.commit()
    
    # 更新 Redis 缓存
    r = get_redis()
    if r:
        from ..redis_client import fire_and_forget
        async def _update_cache():
            try:
                await r.sadd(f"likes:user:{current_user.id}:threads", str(thread_id))
                await r.expire(f"likes:user:{current_user.id}:threads", 300)
            except Exception:
                pass
        fire_and_forget(_update_cache())
    
    return LikeResponse(liked=True, like_count=new_like_count)


# ==================== 回复点赞 ====================

@router.post("/replies/{reply_id}/like", response_model=LikeResponse)
@limiter.limit("30/minute")
def like_reply(
    request: Request,
    reply_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    点赞回复（主楼层或楼中楼）
    """
    # 检查回复是否存在
    reply = db.query(Reply).filter(Reply.id == reply_id).first()
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="回复不存在"
        )
    
    # 检查是否已点赞
    existing = db.query(Like).filter(
        and_(
            Like.user_id == current_user.id,
            Like.target_type == "reply",
            Like.target_id == reply_id
        )
    ).first()
    
    if existing:
        return LikeResponse(liked=True, like_count=reply.like_count or 0)
    
    # 创建点赞记录
    like = Like(
        user_id=current_user.id,
        target_type="reply",
        target_id=reply_id
    )
    db.add(like)
    
    # 原子更新回复点赞数（避免并发丢失更新）
    # P1 #11: 原子 UPDATE 后直接用计算值，不再冗余查询
    db.query(Reply).filter(Reply.id == reply_id).update(
        {Reply.like_count: func.coalesce(Reply.like_count, 0) + 1},
        synchronize_session="fetch"
    )
    db.flush()
    new_like_count = (reply.like_count or 0) + 1
    
    # 给回复作者加经验（被点赞）
    add_exp_for_being_liked(db, reply.author_id)
    
    # 创建通知
    thread = db.query(Thread).filter(Thread.id == reply.thread_id).first()
    _create_like_notification(
        db=db,
        to_user_id=reply.author_id,
        from_user_id=current_user.id,
        thread_id=reply.thread_id,
        reply_id=reply_id,
        content_preview=reply.content[:100] if reply.content else None,
        thread_title=thread.title if thread else None,
        from_username=current_user.nickname or current_user.username
    )
    
    db.commit()
    
    # 更新 Redis 缓存
    r = get_redis()
    if r:
        from ..redis_client import fire_and_forget
        async def _update_cache():
            try:
                await r.sadd(f"likes:user:{current_user.id}:replies", str(reply_id))
                await r.expire(f"likes:user:{current_user.id}:replies", 300)
            except Exception:
                pass
        fire_and_forget(_update_cache())
    
    return LikeResponse(liked=True, like_count=new_like_count)


# ==================== 辅助函数 ====================

def get_user_liked_thread_ids(db: Session, user_id: int, thread_ids: list) -> set:
    """获取用户已点赞的帖子 ID 集合（优先 Redis，降级 DB）"""
    if not thread_ids:
        return set()
    
    r = get_redis()
    if r:
        try:
            import asyncio
            # 同步上下文中无法直接 await，使用 DB 查询后回写缓存
        except Exception:
            pass
    
    # DB 查询（主路径）
    likes = db.query(Like.target_id).filter(
        and_(
            Like.user_id == user_id,
            Like.target_type == "thread",
            Like.target_id.in_(thread_ids)
        )
    ).all()
    
    result = {like[0] for like in likes}
    
    # 异步回写 Redis 缓存
    if r and result:
        from ..redis_client import fire_and_forget
        async def _write_cache():
            try:
                key = f"likes:user:{user_id}:threads"
                pipe = r.pipeline()
                await pipe.delete(key)
                await pipe.sadd(key, *[str(tid) for tid in result])
                await pipe.expire(key, 300)
                await pipe.execute()
            except Exception:
                pass
        fire_and_forget(_write_cache())
    
    return result


def get_user_liked_reply_ids(db: Session, user_id: int, reply_ids: list) -> set:
    """获取用户已点赞的回复 ID 集合（优先 Redis，降级 DB）"""
    if not reply_ids:
        return set()
    
    r = get_redis()
    
    # DB 查询（主路径）
    likes = db.query(Like.target_id).filter(
        and_(
            Like.user_id == user_id,
            Like.target_type == "reply",
            Like.target_id.in_(reply_ids)
        )
    ).all()
    
    result = {like[0] for like in likes}
    
    # 异步回写 Redis 缓存
    if r and result:
        from ..redis_client import fire_and_forget
        async def _write_cache():
            try:
                key = f"likes:user:{user_id}:replies"
                pipe = r.pipeline()
                await pipe.delete(key)
                await pipe.sadd(key, *[str(rid) for rid in result])
                await pipe.expire(key, 300)
                await pipe.execute()
            except Exception:
                pass
        fire_and_forget(_write_cache())
    
    return result


def is_thread_liked_by_user(db: Session, user_id: int, thread_id: int) -> bool:
    """检查用户是否已点赞某帖子"""
    return db.query(Like).filter(
        and_(
            Like.user_id == user_id,
            Like.target_type == "thread",
            Like.target_id == thread_id
        )
    ).first() is not None


def is_reply_liked_by_user(db: Session, user_id: int, reply_id: int) -> bool:
    """检查用户是否已点赞某回复"""
    return db.query(Like).filter(
        and_(
            Like.user_id == user_id,
            Like.target_type == "reply",
            Like.target_id == reply_id
        )
    ).first() is not None
