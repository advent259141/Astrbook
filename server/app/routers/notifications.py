from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Optional, Literal
import re
import asyncio

from ..database import get_db
from ..models import User, Thread, Reply, Notification
from ..schemas import NotificationResponse, UnreadCountResponse, PaginatedResponse, UserResponse
from ..auth import get_current_user
from ..websocket import push_notification

router = APIRouter(prefix="/notifications", tags=["通知"])


def parse_mentions(content: str, db: Session) -> list[int]:
    """解析内容中的 @用户名，返回用户ID列表"""
    pattern = r"@(\w+)"
    usernames = re.findall(pattern, content)
    
    user_ids = []
    for username in usernames:
        user = db.query(User).filter(User.username == username).first()
        if user:
            user_ids.append(user.id)
    
    return user_ids


def create_notification(
    db: Session,
    user_id: int,
    from_user_id: int,
    type: str,
    thread_id: int,
    reply_id: Optional[int] = None,
    content_preview: Optional[str] = None,
    thread_title: Optional[str] = None,
    from_username: Optional[str] = None
):
    """创建通知（不会给自己发通知）并推送 WebSocket 消息"""
    if user_id == from_user_id:
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
    
    # Schedule WebSocket push (non-blocking)
    if thread_title and from_username:
        asyncio.create_task(
            push_notification(
                user_id=user_id,
                notification_type=type,
                thread_id=thread_id,
                thread_title=thread_title,
                from_user_id=from_user_id,
                from_username=from_username,
                reply_id=reply_id,
                content=original_content
            )
        )
    
    return notification


@router.get("", response_model=PaginatedResponse[NotificationResponse])
async def list_notifications(
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
    
    # 统计总数
    total = query.count()
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
async def get_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取未读通知数量
    """
    unread = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .scalar()
    )
    
    total = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == current_user.id)
        .scalar()
    )
    
    return UnreadCountResponse(unread=unread, total=total)


@router.post("/{notification_id}/read")
async def mark_as_read(
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
async def mark_all_as_read(
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
