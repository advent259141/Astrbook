from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, case
from typing import Optional, Literal
import re
import asyncio
import logging

from ..database import get_db
from ..models import User, Thread, Reply, Notification, BlockList
from ..schemas import NotificationResponse, UnreadCountResponse, PaginatedResponse, UserResponse
from ..auth import get_current_user
from ..notifier import push_notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["通知"])


def parse_mentions(content: str, db: Session) -> list[int]:
    """解析内容中的 @用户名，返回用户ID列表（批量查询，1次DB）"""
    pattern = r"@(\w+)"
    usernames = list(set(re.findall(pattern, content)))  # 去重
    
    if not usernames:
        return []
    
    # 一次查询获取所有提及的用户
    users = db.query(User.id).filter(User.username.in_(usernames)).all()
    return [u[0] for u in users]


def get_users_who_blocked(db: Session, sender_id: int, user_ids: list[int]) -> set[int]:
    """批量查询：在 user_ids 中，哪些用户拉黑了 sender_id（1 次 DB 查询）
    
    返回拉黑了 sender_id 的用户 ID 集合。
    用于预查询后传入 create_notification(blocked_user_ids=...) 避免 N+1 查询。
    """
    if not user_ids:
        return set()
    
    rows = (
        db.query(BlockList.user_id)
        .filter(
            BlockList.user_id.in_(user_ids),
            BlockList.blocked_user_id == sender_id
        )
        .all()
    )
    return {row[0] for row in rows}


def create_notification(
    db: Session,
    user_id: int,
    from_user_id: int,
    type: str,
    thread_id: int,
    reply_id: Optional[int] = None,
    content_preview: Optional[str] = None,
    thread_title: Optional[str] = None,
    from_username: Optional[str] = None,
    blocked_user_ids: Optional[set] = None
):
    """创建通知（不会给自己发通知，也不会给拉黑了发送者的用户发通知）并推送 WebSocket 消息
    
    Args:
        blocked_user_ids: 可选的预查询拉黑集合。如果传入，跳过 DB 查询。
                          调用方应通过 get_blocked_by_sender() 预先批量获取。
    """
    # 不给自己发通知
    if user_id == from_user_id:
        return None
    
    # 检查接收者是否拉黑了发送者
    if blocked_user_ids is not None:
        # 使用调用方预查询的拉黑集合
        if user_id in blocked_user_ids:
            return None
    else:
        # 回落到逐个查询（向后兼容）
        is_blocked = db.query(BlockList).filter(
            BlockList.user_id == user_id,
            BlockList.blocked_user_id == from_user_id
        ).first()
        if is_blocked:
            return None
    
    # 截取内容预览
    original_content = content_preview
    if content_preview and len(content_preview) > 100:
        content_preview = content_preview[:97] + "..."
    
    notification = Notification(
        user_id=user_id,
        from_user_id=from_user_id,
        type=type,
        thread_id=thread_id,
        reply_id=reply_id,
        content_preview=content_preview
    )
    db.add(notification)
    
    # Schedule WebSocket push (non-blocking, compatible with both async and sync contexts)
    if thread_title and from_username:
        coro = push_notification(
            user_id=user_id,
            notification_type=type,
            thread_id=thread_id,
            thread_title=thread_title,
            from_user_id=from_user_id,
            from_username=from_username,
            reply_id=reply_id,
            content=original_content
        )
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            # Called from a sync context (thread pool), schedule on the main loop
            try:
                loop = asyncio.get_event_loop()
                asyncio.run_coroutine_threadsafe(coro, loop)
            except Exception:
                logger.warning("[Notification] Failed to schedule push notification")
    
    return notification


@router.get("", response_model=PaginatedResponse[NotificationResponse])
def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    is_read: Optional[bool] = Query(None, description="筛选已读/未读，不传则返回全部"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取我的通知列表
    
    - **is_read**: 可选，true=已读，false=未读，不传=全部
    """
    query = (
        db.query(Notification)
        .options(
            joinedload(Notification.from_user),
            joinedload(Notification.thread)
        )
        .filter(Notification.user_id == current_user.id)
    )
    
    if is_read is not None:
        query = query.filter(Notification.is_read == is_read)
    
    # 统计总数（独立 count 查询，避免子查询包装 + 不必要的 JOIN）
    count_query = db.query(func.count(Notification.id)).filter(
        Notification.user_id == current_user.id
    )
    if is_read is not None:
        count_query = count_query.filter(Notification.is_read == is_read)
    total = count_query.scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    # 分页查询
    notifications = (
        query
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    items = [
        NotificationResponse(
            id=n.id,
            type=n.type,
            thread_id=n.thread_id,
            thread_title=n.thread.title if n.thread else None,
            reply_id=n.reply_id,
            from_user=UserResponse.model_validate(n.from_user),
            content_preview=n.content_preview,
            is_read=n.is_read,
            created_at=n.created_at
        )
        for n in notifications
    ]
    
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.get("/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取未读通知数量（合并为1次条件计数查询）
    """
    result = db.query(
        func.count(Notification.id).label("total"),
        func.count(case((Notification.is_read == False, 1))).label("unread")
    ).filter(Notification.user_id == current_user.id).first()
    
    return UnreadCountResponse(unread=result.unread, total=result.total)


@router.post("/{notification_id}/read")
def mark_as_read(
    notification_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    标记单条通知为已读
    """
    notification = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == current_user.id)
        .first()
    )
    
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="通知不存在"
        )
    
    notification.is_read = True
    db.commit()
    
    return {"message": "已标记为已读"}


@router.post("/read-all")
def mark_all_as_read(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    标记所有通知为已读
    """
    db.query(Notification).filter(
        Notification.user_id == current_user.id,
        Notification.is_read == False
    ).update({"is_read": True})
    
    db.commit()
    
    return {"message": "已全部标记为已读"}
