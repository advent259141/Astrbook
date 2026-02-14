import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, case, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from ..auth import get_current_user
from ..database import get_db
from ..models import BlockList, DMConversation, DMMessage, DMRead, Follow, User
from ..notifier import get_pusher
from ..rate_limit import limiter
from ..redis_client import get_redis
from ..schemas import (
    DMConversationResponse,
    DMMessageCreateRequest,
    DMMessageResponse,
    DMReadRequest,
    DMUnreadCountResponse,
    PaginatedResponse,
    UserPublicResponse,
)

router = APIRouter(prefix="/dm", tags=["dm"])
logger = logging.getLogger(__name__)

# Redis缓存TTL配置
DM_CONVERSATION_LIST_CACHE_TTL = 15  # 会话列表缓存（秒）
DM_UNREAD_COUNT_CACHE_TTL = 10       # 未读数缓存（秒）
DM_USER_INFO_CACHE_TTL = 300         # 用户信息缓存（5分钟）


def _dm_conversation_cache_key(user_id: int, page: int, page_size: int) -> str:
    return f"dm:conv:list:{user_id}:{page}:{page_size}"


def _dm_conversation_cache_pattern(user_id: int) -> str:
    return f"dm:conv:list:{user_id}:*"


def _dm_unread_cache_key(user_id: int) -> str:
    return f"dm:unread:{user_id}"


async def _collect_keys_by_pattern(r, pattern: str) -> list[str]:
    cursor = 0
    keys: list[str] = []
    while True:
        cursor, batch = await r.scan(cursor=cursor, match=pattern, count=200)
        if batch:
            keys.extend(batch)
        if int(cursor) == 0:
            break
    return keys


async def _invalidate_dm_cache_for_users(
    user_ids: set[int],
    *,
    invalidate_conversations: bool = True,
    invalidate_unread: bool = True,
) -> None:
    if not user_ids:
        return

    r = get_redis()
    if not r:
        return

    try:
        keys: set[str] = set()
        if invalidate_unread:
            for user_id in user_ids:
                keys.add(_dm_unread_cache_key(user_id))

        if invalidate_conversations:
            for user_id in user_ids:
                pattern = _dm_conversation_cache_pattern(user_id)
                for key in await _collect_keys_by_pattern(r, pattern):
                    keys.add(key)

        if keys:
            await r.delete(*list(keys))
    except Exception as error:
        logger.warning(f"[DM] Redis cache invalidation failed: {error}")


def _normalize_pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _conversation_peer_id(conv: DMConversation, current_user_id: int) -> int:
    return conv.user_high_id if conv.user_low_id == current_user_id else conv.user_low_id


def _is_member(conv: DMConversation, user_id: int) -> bool:
    return conv.user_low_id == user_id or conv.user_high_id == user_id


def _is_blocked_between(db: Session, user_a: int, user_b: int) -> bool:
    blocked = (
        db.query(BlockList.id)
        .filter(
            or_(
                and_(BlockList.user_id == user_a, BlockList.blocked_user_id == user_b),
                and_(BlockList.user_id == user_b, BlockList.blocked_user_id == user_a),
            )
        )
        .first()
    )
    return blocked is not None


def _to_public_user(user: User) -> UserPublicResponse:
    return UserPublicResponse.model_validate(user)


def _trim_preview(content: str) -> str:
    if len(content) <= 200:
        return content
    return content[:197] + "..."


def _resolve_conversation_by_target(
    db: Session,
    *,
    current_user: User,
    target_user_id: int,
    allow_create: bool = False,
    for_update: bool = False,
) -> tuple[Optional[DMConversation], bool]:
    if target_user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cannot start DM with yourself",
        )

    target_user = db.query(User.id).filter(User.id == target_user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="target user not found",
        )

    if _is_blocked_between(db, current_user.id, target_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot DM due to block relationship",
        )

    user_low_id, user_high_id = _normalize_pair(current_user.id, target_user_id)
    conversation_query = db.query(DMConversation).filter(
        DMConversation.user_low_id == user_low_id,
        DMConversation.user_high_id == user_high_id,
    )
    if for_update and db.bind and db.bind.dialect.name != "sqlite":
        conversation_query = conversation_query.with_for_update()

    conversation = conversation_query.first()
    created_new = False
    if not conversation and allow_create:
        conversation = DMConversation(
            user_low_id=user_low_id,
            user_high_id=user_high_id,
            created_by_id=current_user.id,
            message_count=0,
        )
        db.add(conversation)
        try:
            db.flush()
        except IntegrityError:
            # 并发创建：另一个事务已创建相同会话
            db.rollback()
            # 重新查询（可能需要短暂等待事务提交）
            conversation = (
                db.query(DMConversation)
                .filter(
                    DMConversation.user_low_id == user_low_id,
                    DMConversation.user_high_id == user_high_id,
                )
                .first()
            )
            if not conversation:
                # 罕见情况：会话被创建后又删除，或其他DB问题
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="failed to create DM conversation due to race condition",
                )
        else:
            db.add(
                DMRead(
                    conversation_id=conversation.id,
                    user_id=user_low_id,
                    last_read_message_id=0,
                )
            )
            db.add(
                DMRead(
                    conversation_id=conversation.id,
                    user_id=user_high_id,
                    last_read_message_id=0,
                )
            )
            created_new = True

    return conversation, created_new


def _mark_read_cursor(
    db: Session,
    *,
    conversation_id: int,
    user_id: int,
    target_message_id: int,
) -> tuple[int, bool]:
    target_message_id = max(0, int(target_message_id or 0))
    read_row = (
        db.query(DMRead)
        .filter(
            DMRead.conversation_id == conversation_id,
            DMRead.user_id == user_id,
        )
        .first()
    )

    if not read_row:
        if target_message_id <= 0:
            return 0, False
        db.add(
            DMRead(
                conversation_id=conversation_id,
                user_id=user_id,
                last_read_message_id=target_message_id,
                last_read_at=datetime.utcnow(),
            )
        )
        return target_message_id, True

    previous_read_id = int(read_row.last_read_message_id or 0)
    if target_message_id > previous_read_id:
        read_row.last_read_message_id = target_message_id
        read_row.last_read_at = datetime.utcnow()
        return target_message_id, True

    return previous_read_id, False


def _serialize_messages(
    messages: list[DMMessage],
    current_user_id: int,
) -> list[DMMessageResponse]:
    items: list[DMMessageResponse] = []
    for message in messages:
        items.append(
            DMMessageResponse(
                id=message.id,
                conversation_id=message.conversation_id,
                sender=_to_public_user(message.sender),
                content=message.content,
                client_msg_id=message.client_msg_id,
                is_mine=message.sender_id == current_user_id,
                created_at=message.created_at,
            )
        )
    return items


def _serialize_conversations(
    db: Session,
    conversations: list[DMConversation],
    current_user: User,
) -> list[DMConversationResponse]:
    if not conversations:
        return []

    current_user_id = current_user.id
    conv_ids = [conv.id for conv in conversations]
    peer_ids = {_conversation_peer_id(conv, current_user_id) for conv in conversations}

    # 批量查询用户，只加载需要的字段
    peer_users = (
        db.query(User)
        .filter(User.id.in_(peer_ids))
        .options(
            joinedload(User.level_info)
        )
        .all()
    )
    peer_map = {user.id: user for user in peer_users}

    # 合并Follow查询：一次查询同时获取following和follower
    follow_rows = (
        db.query(Follow.follower_id, Follow.following_id)
        .filter(
            or_(
                and_(Follow.follower_id == current_user_id, Follow.following_id.in_(peer_ids)),
                and_(Follow.following_id == current_user_id, Follow.follower_id.in_(peer_ids)),
            )
        )
        .all()
    )
    following_ids: set[int] = set()
    follower_ids: set[int] = set()
    for follower_id, following_id in follow_rows:
        if follower_id == current_user_id:
            following_ids.add(following_id)
        if following_id == current_user_id:
            follower_ids.add(follower_id)

    # 简化BlockList查询
    blocked_rows = (
        db.query(BlockList.user_id, BlockList.blocked_user_id)
        .filter(
            or_(
                and_(BlockList.user_id == current_user_id, BlockList.blocked_user_id.in_(peer_ids)),
                and_(BlockList.blocked_user_id == current_user_id, BlockList.user_id.in_(peer_ids)),
            )
        )
        .all()
    )
    blocked_peer_ids = {
        blocked_id if user_id == current_user_id else user_id
        for user_id, blocked_id in blocked_rows
    }

    read_subquery = (
        db.query(
            DMRead.conversation_id.label("conversation_id"),
            DMRead.last_read_message_id.label("last_read_message_id"),
        )
        .filter(DMRead.user_id == current_user_id, DMRead.conversation_id.in_(conv_ids))
        .subquery()
    )
    unread_rows = (
        db.query(
            DMMessage.conversation_id,
            func.count(DMMessage.id).label("unread_count"),
        )
        .outerjoin(
            read_subquery,
            read_subquery.c.conversation_id == DMMessage.conversation_id,
        )
        .filter(
            DMMessage.conversation_id.in_(conv_ids),
            DMMessage.sender_id != current_user_id,
            DMMessage.id > func.coalesce(read_subquery.c.last_read_message_id, 0),
        )
        .group_by(DMMessage.conversation_id)
        .all()
    )
    unread_map = {row[0]: int(row[1]) for row in unread_rows}

    items: list[DMConversationResponse] = []
    for conv in conversations:
        peer_id = _conversation_peer_id(conv, current_user_id)
        peer_user = peer_map.get(peer_id)
        if not peer_user:
            continue

        is_mutual = peer_id in following_ids and peer_id in follower_ids
        is_blocked = peer_id in blocked_peer_ids
        can_send = not is_blocked

        items.append(
            DMConversationResponse(
                id=conv.id,
                peer=_to_public_user(peer_user),
                message_count=int(conv.message_count or 0),
                last_message_id=conv.last_message_id,
                last_message_sender_id=conv.last_message_sender_id,
                last_message_preview=conv.last_message_preview,
                last_message_at=conv.last_message_at,
                unread_count=unread_map.get(conv.id, 0),
                is_mutual_follow=is_mutual,
                is_blocked=is_blocked,
                can_send=can_send,
                created_at=conv.created_at,
            )
        )

    return items


def _query_messages(
    db: Session,
    *,
    conversation_id: int,
    before_id: Optional[int],
    limit: int,
) -> list[DMMessage]:
    query = (
        db.query(DMMessage)
        .options(
            joinedload(DMMessage.sender).joinedload(User.level_info)
        )
        .filter(DMMessage.conversation_id == conversation_id)
    )
    if before_id:
        query = query.filter(DMMessage.id < before_id)

    messages = query.order_by(DMMessage.id.desc()).limit(limit).all()
    messages.reverse()
    return messages


async def _auto_mark_read_after_fetch(
    db: Session,
    *,
    conversation_id: int,
    current_user_id: int,
    messages: list[DMMessage],
) -> None:
    if not messages:
        return

    latest_message_id = int(messages[-1].id)
    _, updated = _mark_read_cursor(
        db,
        conversation_id=conversation_id,
        user_id=current_user_id,
        target_message_id=latest_message_id,
    )
    if not updated:
        return

    db.commit()
    await _invalidate_dm_cache_for_users(
        {current_user_id},
        invalidate_conversations=True,
        invalidate_unread=True,
    )


async def _mark_read_for_conversation(
    db: Session,
    *,
    conversation: DMConversation,
    current_user_id: int,
    data: Optional[DMReadRequest],
) -> dict:
    last_read_message_id = data.last_read_message_id if data else None
    if last_read_message_id is None:
        target_message_id = int(conversation.last_message_id or 0)
    else:
        message = (
            db.query(DMMessage.id)
            .filter(
                DMMessage.id == last_read_message_id,
                DMMessage.conversation_id == conversation.id,
            )
            .first()
        )
        if not message:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="last_read_message_id does not belong to this conversation",
            )
        target_message_id = int(last_read_message_id)

    effective_read_id, updated = _mark_read_cursor(
        db,
        conversation_id=conversation.id,
        user_id=current_user_id,
        target_message_id=target_message_id,
    )

    if updated:
        db.commit()
        await _invalidate_dm_cache_for_users(
            {current_user_id},
            invalidate_conversations=True,
            invalidate_unread=True,
        )

    return {
        "conversation_id": conversation.id,
        "last_read_message_id": effective_read_id,
        "updated": updated,
    }


@router.get("", response_model=PaginatedResponse[DMConversationResponse])
async def list_conversations(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = get_redis()
    cache_key = _dm_conversation_cache_key(current_user.id, page, page_size)
    if r:
        try:
            cached = await r.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    # 使用with_hint优化查询计划（PostgreSQL）
    base_query = db.query(DMConversation).filter(
        or_(
            DMConversation.user_low_id == current_user.id,
            DMConversation.user_high_id == current_user.id,
        )
    )

    # 优化：使用窗口函数避免两次查询
    total = base_query.count()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    conversations = (
        base_query
        .order_by(
            case((DMConversation.last_message_at.is_(None), 1), else_=0),
            DMConversation.last_message_at.desc(),
            DMConversation.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = _serialize_conversations(db, conversations, current_user)

    response = PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )
    if r:
        try:
            payload = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)
            await r.setex(cache_key, DM_CONVERSATION_LIST_CACHE_TTL, payload)
        except Exception:
            pass
    return response


@router.get("/messages", response_model=list[DMMessageResponse])
async def list_messages_by_target(
    target_user_id: int = Query(..., ge=1),
    before_id: Optional[int] = Query(None, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation, _ = _resolve_conversation_by_target(
        db,
        current_user=current_user,
        target_user_id=target_user_id,
        allow_create=False,
    )
    if not conversation:
        return []

    messages = _query_messages(
        db,
        conversation_id=conversation.id,
        before_id=before_id,
        limit=limit,
    )
    await _auto_mark_read_after_fetch(
        db,
        conversation_id=conversation.id,
        current_user_id=current_user.id,
        messages=messages,
    )
    return _serialize_messages(messages, current_user.id)


async def _send_message_in_conversation(
    *,
    db: Session,
    current_user: User,
    conversation: DMConversation,
    content: str,
    client_msg_id: Optional[str],
) -> DMMessageResponse:
    conversation_id = int(conversation.id)
    peer_id = _conversation_peer_id(conversation, current_user.id)

    if _is_blocked_between(db, current_user.id, peer_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="cannot send DM due to block relationship",
        )

    if client_msg_id:
        dedup_message = (
            db.query(DMMessage)
            .options(joinedload(DMMessage.sender))
            .filter(
                DMMessage.conversation_id == conversation_id,
                DMMessage.sender_id == current_user.id,
                DMMessage.client_msg_id == client_msg_id,
            )
            .first()
        )
        if dedup_message:
            return _serialize_messages([dedup_message], current_user.id)[0]

    now = datetime.utcnow()
    message = DMMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=content,
        client_msg_id=client_msg_id,
        created_at=now,
    )
    db.add(message)
    db.flush()

    conversation.message_count = int(conversation.message_count or 0) + 1
    conversation.last_message_id = message.id
    conversation.last_message_sender_id = current_user.id
    conversation.last_message_preview = _trim_preview(content)
    conversation.last_message_at = now

    sender_read = (
        db.query(DMRead)
        .filter(
            DMRead.conversation_id == conversation_id,
            DMRead.user_id == current_user.id,
        )
        .first()
    )
    if not sender_read:
        db.add(
            DMRead(
                conversation_id=conversation_id,
                user_id=current_user.id,
                last_read_message_id=message.id,
                last_read_at=now,
            )
        )
    else:
        if message.id > int(sender_read.last_read_message_id or 0):
            sender_read.last_read_message_id = message.id
        sender_read.last_read_at = now

    peer_read = (
        db.query(DMRead)
        .filter(
            DMRead.conversation_id == conversation_id,
            DMRead.user_id == peer_id,
        )
        .first()
    )
    if not peer_read:
        db.add(
            DMRead(
                conversation_id=conversation_id,
                user_id=peer_id,
                last_read_message_id=0,
            )
        )

    db.commit()
    db.refresh(message)
    db.refresh(current_user)
    await _invalidate_dm_cache_for_users({current_user.id, peer_id})

    payload = {
        "type": "dm_new_message",
        "conversation_id": conversation_id,
        "message": {
            "id": message.id,
            "conversation_id": conversation_id,
            "sender_id": current_user.id,
            "sender_username": current_user.username,
            "sender_nickname": current_user.nickname,
            "content": message.content,
            "client_msg_id": message.client_msg_id,
            "created_at": message.created_at.isoformat(),
        },
        "timestamp": datetime.utcnow().isoformat(),
    }
    pusher = get_pusher()
    await pusher.send_to_user(peer_id, payload)
    if peer_id != current_user.id:
        await pusher.send_to_user(current_user.id, payload)

    return DMMessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sender=_to_public_user(current_user),
        content=message.content,
        client_msg_id=message.client_msg_id,
        is_mine=True,
        created_at=message.created_at,
    )


@router.post("/messages", response_model=DMMessageResponse)
@limiter.limit("20/minute")
async def send_message_by_target(
    request: Request,
    target_user_id: int = Query(..., ge=1),
    data: DMMessageCreateRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    content = data.content.strip()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="message content cannot be empty",
        )

    conversation, _ = _resolve_conversation_by_target(
        db,
        current_user=current_user,
        target_user_id=target_user_id,
        allow_create=True,
        for_update=True,
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        )

    return await _send_message_in_conversation(
        db=db,
        current_user=current_user,
        conversation=conversation,
        content=content,
        client_msg_id=data.client_msg_id,
    )


@router.post("/read")
async def mark_read_by_target(
    target_user_id: int = Query(..., ge=1),
    data: Optional[DMReadRequest] = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation, _ = _resolve_conversation_by_target(
        db,
        current_user=current_user,
        target_user_id=target_user_id,
        allow_create=False,
    )
    if not conversation:
        return {
            "conversation_id": None,
            "last_read_message_id": 0,
            "updated": False,
        }

    return await _mark_read_for_conversation(
        db,
        conversation=conversation,
        current_user_id=current_user.id,
        data=data,
    )


@router.get("/unread-count", response_model=DMUnreadCountResponse)
async def get_dm_unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = get_redis()
    cache_key = _dm_unread_cache_key(current_user.id)
    if r:
        try:
            cached = await r.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    read_subquery = (
        db.query(
            DMRead.conversation_id.label("conversation_id"),
            DMRead.last_read_message_id.label("last_read_message_id"),
        )
        .filter(DMRead.user_id == current_user.id)
        .subquery()
    )

    unread_rows = (
        db.query(
            DMMessage.conversation_id,
            func.count(DMMessage.id).label("unread_count"),
        )
        .join(DMConversation, DMConversation.id == DMMessage.conversation_id)
        .outerjoin(
            read_subquery,
            read_subquery.c.conversation_id == DMMessage.conversation_id,
        )
        .filter(
            or_(
                DMConversation.user_low_id == current_user.id,
                DMConversation.user_high_id == current_user.id,
            ),
            DMMessage.sender_id != current_user.id,
            DMMessage.id > func.coalesce(read_subquery.c.last_read_message_id, 0),
        )
        .group_by(DMMessage.conversation_id)
        .all()
    )

    unread_total = sum(int(row[1]) for row in unread_rows)
    conversations_with_unread = len(unread_rows)

    response = DMUnreadCountResponse(
        unread=unread_total,
        conversations_with_unread=conversations_with_unread,
    )
    if r:
        try:
            payload = json.dumps(response.model_dump(), ensure_ascii=False)
            await r.setex(cache_key, DM_UNREAD_COUNT_CACHE_TTL, payload)
        except Exception:
            pass
    return response
