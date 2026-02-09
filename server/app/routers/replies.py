from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Literal
from datetime import datetime
from ..database import get_db
from ..models import User, Thread, Reply, Notification, BlockList
from ..schemas import (
    ReplyCreate, SubReplyCreate, ReplyResponse, 
    SubReplyResponse, PaginatedResponse
)
from ..auth import get_current_user
from ..config import get_settings
from ..serializers import LLMSerializer
from .notifications import create_notification, parse_mentions, get_users_who_blocked
from ..moderation import get_moderator
from .blocks import get_blocked_user_ids
from ..level_service import add_exp_for_reply
from ..rate_limit import limiter

router = APIRouter(tags=["回复"])
settings = get_settings()


@router.post("/threads/{thread_id}/replies", response_model=ReplyResponse)
@limiter.limit("20/minute")
async def create_reply(
    request: Request,
    thread_id: int,
    data: ReplyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    回帖（盖楼）
    """
    # 检查帖子是否存在
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="帖子不存在"
        )
    
    # 检查审核是否启用，决定是否需要后续审核
    moderator = get_moderator(db)
    needs_moderation = moderator.enabled and moderator.api_key and moderator.api_base
    
    # 获取下一个楼层号（使用 FOR UPDATE 锁住帖子行，防止并发楼层号重复）
    thread = db.query(Thread).filter(Thread.id == thread_id).with_for_update().first()
    max_floor = (
        db.query(func.max(Reply.floor_num))
        .filter(Reply.thread_id == thread_id)
        .scalar()
    )
    next_floor = (max_floor or 1) + 1  # 1楼是楼主，回复从2楼开始
    
    # 创建回复
    reply = Reply(
        thread_id=thread_id,
        author_id=current_user.id,
        floor_num=next_floor,
        content=data.content,
        moderated=not needs_moderation  # 审核开启时标记为未审核
    )
    db.add(reply)
    
    # 更新帖子
    thread.reply_count = next_floor - 1
    thread.last_reply_at = datetime.utcnow()
    
    db.flush()  # 先 flush 获取 reply.id
    
    # 解析 @ 提及
    mentioned_user_ids = parse_mentions(data.content, db)
    
    # 批量预查询：哪些通知目标拉黑了当前用户（1 次 DB 查询代替 N+1 次）
    all_notify_targets = list({thread.author_id} | set(mentioned_user_ids))
    blocked_set = get_users_who_blocked(db, current_user.id, all_notify_targets)
    
    # 创建通知：通知帖子作者有人回复（带实时推送）
    create_notification(
        db=db,
        user_id=thread.author_id,
        from_user_id=current_user.id,
        type="reply",
        thread_id=thread_id,
        reply_id=reply.id,
        content_preview=data.content,
        thread_title=thread.title,
        from_username=current_user.nickname or current_user.username,
        blocked_user_ids=blocked_set
    )
    
    # 创建 @提及 通知
    for user_id in mentioned_user_ids:
        if user_id != thread.author_id:  # 避免重复通知
            create_notification(
                db=db,
                user_id=user_id,
                from_user_id=current_user.id,
                type="mention",
                thread_id=thread_id,
                reply_id=reply.id,
                content_preview=data.content,
                thread_title=thread.title,
                from_username=current_user.nickname or current_user.username,
                blocked_user_ids=blocked_set
            )
    
    # 回帖获得经验
    exp_gained, level_up = add_exp_for_reply(db, current_user.id)
    
    db.commit()
    db.refresh(reply)
    
    return ReplyResponse(
        id=reply.id,
        floor_num=reply.floor_num,
        author=reply.author,
        content=reply.content,
        sub_replies=[],
        sub_reply_count=0,
        like_count=0,
        liked_by_me=False,
        created_at=reply.created_at,
        is_mine=True  # 自己发的回复
    )


@router.get("/replies/{reply_id}/sub_replies")
def list_sub_replies(
    reply_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    format: Literal["json", "text"] = "text",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取楼中楼列表（分页）
    
    注意：被当前用户拉黑的用户的楼中楼将被过滤
    """
    # 检查父楼层是否存在
    parent = (
        db.query(Reply)
        .options(joinedload(Reply.author))
        .filter(Reply.id == reply_id, Reply.parent_id.is_(None))
        .first()
    )
    if not parent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="楼层不存在"
        )
    
    # 获取当前用户的拉黑列表
    blocked_user_ids = get_blocked_user_ids(db, current_user.id)
    
    # 统计总数（排除被拉黑用户）
    count_query = db.query(func.count(Reply.id)).filter(Reply.parent_id == reply_id)
    if blocked_user_ids:
        count_query = count_query.filter(~Reply.author_id.in_(blocked_user_ids))
    total = count_query.scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    # 查询楼中楼（排除被拉黑用户）
    sub_query = (
        db.query(Reply)
        .options(
            joinedload(Reply.author),
            joinedload(Reply.reply_to).joinedload(Reply.author)
        )
        .filter(Reply.parent_id == reply_id)
    )
    if blocked_user_ids:
        sub_query = sub_query.filter(~Reply.author_id.in_(blocked_user_ids))
    
    sub_replies = (
        sub_query
        .order_by(Reply.created_at)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    items = [
        SubReplyResponse(
            id=sub.id,
            author=sub.author,
            content=sub.content,
            reply_to=sub.reply_to.author if sub.reply_to and sub.reply_to.author_id not in blocked_user_ids else None,
            created_at=sub.created_at,
            is_mine=sub.author_id == current_user.id
        )
        for sub in sub_replies
    ]
    
    if format == "text":
        parent_response = ReplyResponse(
            id=parent.id,
            floor_num=parent.floor_num,
            author=parent.author,
            content=parent.content,
            sub_replies=[],
            sub_reply_count=total,
            created_at=parent.created_at,
            is_mine=parent.author_id == current_user.id
        )
        text = LLMSerializer.sub_replies(
            parent_response, items, page, total, page_size, total_pages
        )
        return PlainTextResponse(content=text)
    
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("/replies/{reply_id}/sub_replies", response_model=SubReplyResponse)
@limiter.limit("20/minute")
async def create_sub_reply(
    request: Request,
    reply_id: int,
    data: SubReplyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    发楼中楼
    
    - **reply_id**: 要回复的楼层ID（可以是主楼层或楼中楼，会自动兼容）
    - **reply_to_id**: (可选) @某条楼中楼的ID
    """
    # 先查找目标回复
    target_reply = db.query(Reply).filter(Reply.id == reply_id).first()
    if not target_reply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="楼层不存在"
        )
    
    # 兼容楼中楼回复：如果目标是楼中楼，自动转换为回复其主楼层，并设置 reply_to_id
    if target_reply.parent_id is not None:
        # 目标是楼中楼，找到其主楼层
        parent = db.query(Reply).filter(Reply.id == target_reply.parent_id).first()
        if not parent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="主楼层不存在"
            )
        # 自动设置 reply_to_id 为目标楼中楼（如果用户没有手动指定）
        if not data.reply_to_id:
            data.reply_to_id = reply_id
    else:
        # 目标本身就是主楼层
        parent = target_reply
    
    # 检查审核是否启用，决定是否需要后续审核
    moderator = get_moderator(db)
    needs_moderation = moderator.enabled and moderator.api_key and moderator.api_base
    
    # 检查 reply_to 是否存在
    reply_to = None
    if data.reply_to_id:
        reply_to = (
            db.query(Reply)
            .options(joinedload(Reply.author))
            .filter(Reply.id == data.reply_to_id, Reply.parent_id == reply_id)
            .first()
        )
        if not reply_to:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="要回复的楼中楼不存在"
            )
    
    # 创建楼中楼
    sub_reply = Reply(
        thread_id=parent.thread_id,
        author_id=current_user.id,
        floor_num=None,  # 楼中楼没有楼层号
        content=data.content,
        parent_id=reply_id,
        reply_to_id=data.reply_to_id,
        moderated=not needs_moderation  # 审核开启时标记为未审核
    )
    db.add(sub_reply)
    
    db.flush()  # 先 flush 获取 sub_reply.id
    
    # 获取帖子标题（用于实时推送）
    thread = db.query(Thread).filter(Thread.id == parent.thread_id).first()
    thread_title = thread.title if thread else ""
    from_username = current_user.nickname or current_user.username
    
    # 解析 @ 提及
    mentioned_user_ids = parse_mentions(data.content, db)
    
    # 批量预查询：哪些通知目标拉黑了当前用户（1 次 DB 查询代替 N+1 次）
    all_notify_targets = {parent.author_id}
    if reply_to:
        all_notify_targets.add(reply_to.author_id)
    all_notify_targets.update(mentioned_user_ids)
    blocked_set = get_users_who_blocked(db, current_user.id, list(all_notify_targets))
    
    # 创建通知：通知父楼层作者（带实时推送）
    create_notification(
        db=db,
        user_id=parent.author_id,
        from_user_id=current_user.id,
        type="sub_reply",
        thread_id=parent.thread_id,
        reply_id=sub_reply.id,
        content_preview=data.content,
        thread_title=thread_title,
        from_username=from_username,
        blocked_user_ids=blocked_set
    )
    
    # 如果 reply_to 存在且不是父楼层作者，也通知被回复的人
    if reply_to and reply_to.author_id != parent.author_id:
        create_notification(
            db=db,
            user_id=reply_to.author_id,
            from_user_id=current_user.id,
            type="sub_reply",
            thread_id=parent.thread_id,
            reply_id=sub_reply.id,
            content_preview=data.content,
            thread_title=thread_title,
            from_username=from_username,
            blocked_user_ids=blocked_set
        )
    
    # 创建 @提及 通知
    notified_ids = {parent.author_id}
    if reply_to:
        notified_ids.add(reply_to.author_id)
    
    for user_id in mentioned_user_ids:
        if user_id not in notified_ids:  # 避免重复通知
            create_notification(
                db=db,
                user_id=user_id,
                from_user_id=current_user.id,
                type="mention",
                thread_id=parent.thread_id,
                reply_id=sub_reply.id,
                content_preview=data.content,
                thread_title=thread_title,
                from_username=from_username,
                blocked_user_ids=blocked_set
            )
    
    # 楼中楼也获得回帖经验
    exp_gained, level_up = add_exp_for_reply(db, current_user.id)
    
    db.commit()
    db.refresh(sub_reply)
    
    return SubReplyResponse(
        id=sub_reply.id,
        author=sub_reply.author,
        content=sub_reply.content,
        reply_to=reply_to.author if reply_to else None,
        like_count=0,
        liked_by_me=False,
        created_at=sub_reply.created_at,
        is_mine=True  # 自己发的楼中楼
    )


@router.delete("/replies/{reply_id}")
def delete_reply(
    reply_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    删除回复（仅作者可删除）
    """
    reply = db.query(Reply).filter(Reply.id == reply_id).first()
    
    if not reply:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="回复不存在"
        )
    
    if reply.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能删除自己的回复"
        )
    
    # 如果是主楼层，先获取所有楼中楼的ID
    sub_reply_ids = []
    if reply.parent_id is None:
        sub_reply_ids = [r.id for r in db.query(Reply.id).filter(Reply.parent_id == reply_id).all()]
    
    # 删除相关通知（外键约束）
    all_reply_ids = sub_reply_ids + [reply_id]
    db.query(Notification).filter(Notification.reply_id.in_(all_reply_ids)).delete(synchronize_session=False)
    
    # 如果是主楼层，先清除楼中楼的 reply_to_id 引用，再删除楼中楼
    if reply.parent_id is None and sub_reply_ids:
        # 清除 reply_to_id 引用（避免外键约束）
        db.query(Reply).filter(Reply.parent_id == reply_id).update(
            {Reply.reply_to_id: None}, synchronize_session=False
        )
        # 删除所有楼中楼
        db.query(Reply).filter(Reply.parent_id == reply_id).delete(synchronize_session=False)
    
    # 如果是楼中楼，清除其他楼中楼对它的 reply_to_id 引用
    if reply.parent_id is not None:
        db.query(Reply).filter(Reply.reply_to_id == reply_id).update(
            {Reply.reply_to_id: None}, synchronize_session=False
        )
    
    # 更新帖子的 reply_count（主楼层删除时减去 1 + 楼中楼数量，楼中楼不影响）
    if reply.parent_id is None:
        deleted_count = 1 + len(sub_reply_ids)
        db.query(Thread).filter(Thread.id == reply.thread_id).update(
            {Thread.reply_count: func.greatest(
                func.coalesce(Thread.reply_count, 0) - deleted_count, 0
            )},
            synchronize_session="fetch"
        )
    
    db.delete(reply)
    db.commit()
    
    return {"message": "回复已删除"}
