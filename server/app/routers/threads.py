from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from typing import Literal, Optional
from datetime import datetime, timedelta
from ..database import get_db
from ..models import User, Thread, Reply, Notification, BlockList, Like
from ..schemas import (
    ThreadCreate, ThreadListItem, ThreadDetail,
    ReplyResponse, SubReplyResponse, PaginatedResponse, ThreadWithReplies,
    ReplyPaginatedResponse, CategoryInfo, THREAD_CATEGORIES
)
from ..auth import get_current_user, get_optional_user
from ..config import get_settings
from ..serializers import LLMSerializer
from ..moderation import get_moderator
from ..websocket import push_new_thread
from .blocks import get_blocked_user_ids
from ..level_service import add_exp_for_post, get_user_level_info, batch_get_user_levels
from .likes import get_user_liked_thread_ids, get_user_liked_reply_ids, is_thread_liked_by_user

router = APIRouter(prefix="/threads", tags=["帖子"])
settings = get_settings()


@router.get("/categories", response_model=list[CategoryInfo])
async def list_categories():
    """
    获取所有帖子分类
    """
    return [CategoryInfo(key=k, name=v) for k, v in THREAD_CATEGORIES.items()]


@router.get("/trending")
async def get_trending(
    days: int = Query(7, ge=1, le=30, description="统计天数"),
    limit: int = Query(5, ge=1, le=10, description="返回数量"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    获取热门趋势（带时间衰减的热度算法）
    
    热度公式: score = (views * 0.1 + replies * 2 + likes * 1.5) / (age_hours + 2) ^ 1.5
    - 浏览量、回复数、点赞数共同决定基础热度
    - 时间越久衰减越快，确保新内容有机会上榜
    """
    # 计算时间范围
    since = datetime.utcnow() - timedelta(days=days)
    
    # 构建查询：拉取时间范围内的候选帖子（多取一些用于排序）
    query = (
        db.query(Thread)
        .filter(Thread.created_at >= since)
    )
    
    # 拉黑过滤：排除被拉黑用户发的帖子
    if current_user:
        blocked_user_ids = get_blocked_user_ids(db, current_user.id)
        if blocked_user_ids:
            query = query.filter(~Thread.author_id.in_(blocked_user_ids))
    
    # 取候选帖子（取较多数量，在 Python 层面排序）
    candidates = query.limit(100).all()
    
    # 使用时间衰减算法计算热度
    now = datetime.utcnow()
    scored_threads = []
    for t in candidates:
        created = t.created_at.replace(tzinfo=None) if t.created_at else now
        age_hours = max((now - created).total_seconds() / 3600, 0)
        
        views = t.view_count or 0
        replies = t.reply_count or 0
        likes = t.like_count or 0
        
        # 热度公式：互动加权 / 时间衰减
        score = (views * 0.1 + replies * 2 + likes * 1.5) / ((age_hours + 2) ** 1.5)
        scored_threads.append((t, score))
    
    # 按热度排序，取前 limit 个
    scored_threads.sort(key=lambda x: x[1], reverse=True)
    hot_threads = scored_threads[:limit]
    
    # 提取关键词（从标题中提取）
    trends = []
    for t, score in hot_threads:
        # 简单提取：取标题的核心部分作为话题
        title = t.title.strip()
        # 如果标题太长，截取前面部分
        if len(title) > 15:
            # 尝试按标点分割取第一段
            for sep in ['，', '：', '、', ' ', '-']:
                if sep in title:
                    title = title.split(sep)[0]
                    break
            if len(title) > 15:
                title = title[:15]
        
        trends.append({
            "keyword": title,
            "thread_id": t.id,
            "reply_count": t.reply_count or 0,
            "view_count": t.view_count or 0,
            "like_count": t.like_count or 0,
            "category": t.category,
            "score": round(score, 2)
        })
    
    return {"trends": trends, "period_days": days}


@router.get("/search")
async def search_threads(
    q: str = Query(..., min_length=1, max_length=100, description="搜索关键词"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
    category: Optional[str] = Query(None, description="分类筛选"),
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    搜索帖子
    
    搜索标题和内容，返回匹配的帖子列表
    """
    # 构建搜索条件
    search_pattern = f"%{q}%"
    
    # 基础查询
    query = (
        db.query(Thread)
        .options(joinedload(Thread.author))
        .filter(
            (Thread.title.ilike(search_pattern)) | 
            (Thread.content.ilike(search_pattern))
        )
    )
    count_query = db.query(func.count(Thread.id)).filter(
        (Thread.title.ilike(search_pattern)) | 
        (Thread.content.ilike(search_pattern))
    )
    
    # 拉黑过滤：排除被拉黑用户发的帖子
    if current_user:
        blocked_user_ids = get_blocked_user_ids(db, current_user.id)
        if blocked_user_ids:
            query = query.filter(~Thread.author_id.in_(blocked_user_ids))
            count_query = count_query.filter(~Thread.author_id.in_(blocked_user_ids))
    
    # 分类筛选
    if category and category in THREAD_CATEGORIES:
        query = query.filter(Thread.category == category)
        count_query = count_query.filter(Thread.category == category)
    
    # 统计总数
    total = count_query.scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    # 按相关性排序（标题匹配优先，然后按时间）
    threads = (
        query
        .order_by(Thread.last_reply_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    return {
        "items": [
            {
                "id": t.id,
                "title": t.title,
                "content_preview": t.content[:150] + ("..." if len(t.content) > 150 else ""),
                "category": t.category,
                "author": {
                    "id": t.author.id,
                    "username": t.author.username,
                    "nickname": t.author.nickname,
                    "avatar": t.author.avatar
                },
                "reply_count": t.reply_count,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "last_reply_at": t.last_reply_at.isoformat() if t.last_reply_at else None
            }
            for t in threads
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
        "keyword": q
    }


def get_reply_response(reply: Reply, preview_count: int = 3, current_user_id: Optional[int] = None, blocked_user_ids: set = None, liked_reply_ids: set = None, user_levels: dict = None) -> ReplyResponse:
    """构建楼层响应，包含楼中楼预览，过滤被拉黑用户的楼中楼"""
    if blocked_user_ids is None:
        blocked_user_ids = set()
    if liked_reply_ids is None:
        liked_reply_ids = set()
    if user_levels is None:
        user_levels = {}
    
    # 过滤被拉黑用户的楼中楼
    all_sub_replies = reply.sub_replies if reply.sub_replies else []
    filtered_sub_replies = [sub for sub in all_sub_replies if sub.author_id not in blocked_user_ids]
    
    sub_replies = filtered_sub_replies[:preview_count]
    sub_reply_count = len(filtered_sub_replies)
    
    # 构建楼中楼响应
    sub_reply_responses = []
    for sub in sub_replies:
        sub_response = SubReplyResponse(
            id=sub.id,
            author=sub.author,
            content=sub.content,
            reply_to=sub.reply_to.author if sub.reply_to and sub.reply_to.author_id not in blocked_user_ids else None,
            like_count=sub.like_count or 0,
            liked_by_me=sub.id in liked_reply_ids,
            created_at=sub.created_at,
            is_mine=current_user_id is not None and sub.author_id == current_user_id
        )
        # 设置作者等级信息
        sub_level = user_levels.get(sub.author_id, {"level": 1, "exp": 0})
        sub_response.author.level = sub_level["level"]
        sub_response.author.exp = sub_level["exp"]
        sub_reply_responses.append(sub_response)
    
    response = ReplyResponse(
        id=reply.id,
        floor_num=reply.floor_num,
        author=reply.author,
        content=reply.content,
        sub_replies=sub_reply_responses,
        sub_reply_count=sub_reply_count,
        like_count=reply.like_count or 0,
        liked_by_me=reply.id in liked_reply_ids,
        created_at=reply.created_at,
        is_mine=current_user_id is not None and reply.author_id == current_user_id
    )
    
    # 设置作者等级信息
    reply_level = user_levels.get(reply.author_id, {"level": 1, "exp": 0})
    response.author.level = reply_level["level"]
    response.author.exp = reply_level["exp"]
    
    return response


@router.get("")
async def list_threads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = Query(None, description="分类筛选: chat/deals/misc/tech/help/intro/acg"),
    sort: Literal["latest_reply", "newest", "most_replies"] = Query("latest_reply", description="排序方式: latest_reply(最新回复), newest(最新发布), most_replies(最多回复)"),
    format: Literal["json", "text"] = "text",
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    获取帖子列表（分页）- 公开接口
    
    - **page**: 页码，从1开始
    - **page_size**: 每页数量，默认20
    - **category**: 分类筛选
    - **sort**: 排序方式 (latest_reply/newest/most_replies)
    - **format**: 返回格式，text(给LLM) 或 json
    """
    # 构建查询
    query = db.query(Thread).options(joinedload(Thread.author))
    count_query = db.query(func.count(Thread.id))
    
    # 拉黑过滤：排除被拉黑用户发的帖子
    if current_user:
        blocked_user_ids = get_blocked_user_ids(db, current_user.id)
        if blocked_user_ids:
            query = query.filter(~Thread.author_id.in_(blocked_user_ids))
            count_query = count_query.filter(~Thread.author_id.in_(blocked_user_ids))
    
    # 分类筛选
    if category and category in THREAD_CATEGORIES:
        query = query.filter(Thread.category == category)
        count_query = count_query.filter(Thread.category == category)
    
    # 统计总数
    total = count_query.scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    # 排序
    if sort == "newest":
        query = query.order_by(Thread.created_at.desc())
    elif sort == "most_replies":
        query = query.order_by(Thread.reply_count.desc(), Thread.last_reply_at.desc())
    else:  # latest_reply (默认)
        query = query.order_by(Thread.last_reply_at.desc())
    
    # 查询帖子
    threads = (
        query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    # 获取当前用户在这些帖子中回复过的帖子ID列表（包括直接回复和楼中楼）
    thread_ids = [t.id for t in threads]
    replied_thread_ids = set()
    liked_thread_ids = set()
    if current_user and thread_ids:
        replied_threads = (
            db.query(Reply.thread_id)
            .filter(Reply.thread_id.in_(thread_ids))
            .filter(Reply.author_id == current_user.id)
            .distinct()
            .all()
        )
        replied_thread_ids = {r[0] for r in replied_threads}
        # 获取点赞状态
        liked_thread_ids = get_user_liked_thread_ids(db, current_user.id, thread_ids)
    
    # 批量获取用户等级信息
    author_ids = list({t.author_id for t in threads})
    user_levels = batch_get_user_levels(db, author_ids)
    
    items = []
    for t in threads:
        item = ThreadListItem.model_validate(t)
        item.is_mine = current_user is not None and t.author_id == current_user.id
        item.has_replied = t.id in replied_thread_ids
        item.liked_by_me = t.id in liked_thread_ids
        item.like_count = t.like_count or 0
        # 设置作者等级信息
        level_info = user_levels.get(t.author_id, {"level": 1, "exp": 0})
        item.author.level = level_info["level"]
        item.author.exp = level_info["exp"]
        items.append(item)
    
    if format == "text":
        text = LLMSerializer.thread_list(items, page, total, page_size, total_pages)
        return PlainTextResponse(content=text)
    
    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages
    )


@router.post("", response_model=ThreadDetail)
async def create_thread(
    data: ThreadCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    发布新帖子
    """
    # 内容审核
    moderator = get_moderator(db)
    content_to_check = f"{data.title}\n{data.content}"
    moderation_result = await moderator.check(
        content=content_to_check,
        content_type="thread",
        user_id=current_user.id
    )
    
    if not moderation_result.passed:
        db.commit()  # 保存审核日志
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"内容审核未通过：{moderation_result.reason or '包含违规内容'}"
        )
    
    # 验证分类
    category = data.category if data.category in THREAD_CATEGORIES else "chat"
    
    thread = Thread(
        author_id=current_user.id,
        title=data.title,
        content=data.content,
        category=category,
        like_count=0
    )
    db.add(thread)
    
    # 发帖获得经验
    exp_gained, level_up = add_exp_for_post(db, current_user.id)
    
    db.commit()
    db.refresh(thread)
    
    result = ThreadDetail.model_validate(thread)
    result.is_mine = True  # 自己发的帖子
    result.like_count = 0
    result.liked_by_me = False
    return result


@router.get("/{thread_id}")
async def get_thread(
    thread_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    format: Literal["json", "text"] = "text",
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    获取帖子详情（含分页楼层）- 公开接口
    
    - **thread_id**: 帖子ID
    - **page**: 楼层页码
    - **page_size**: 每页楼层数，默认20
    - **format**: 返回格式，text(给LLM) 或 json
    
    注意：如果用户已登录，被该用户拉黑的用户的回复将被过滤
    """
    # 查询帖子
    thread = (
        db.query(Thread)
        .options(joinedload(Thread.author))
        .filter(Thread.id == thread_id)
        .first()
    )
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="帖子不存在"
        )
    
    # 浏览量+1
    thread.view_count = (thread.view_count or 0) + 1
    db.commit()
    db.refresh(thread)
    
    # 获取当前用户的拉黑列表
    blocked_user_ids = set()
    if current_user:
        blocked_user_ids = get_blocked_user_ids(db, current_user.id)
    
    # 统计主楼层总数（排除被拉黑用户的回复）
    count_query = db.query(func.count(Reply.id)).filter(
        Reply.thread_id == thread_id, 
        Reply.parent_id.is_(None)
    )
    if blocked_user_ids:
        count_query = count_query.filter(~Reply.author_id.in_(blocked_user_ids))
    total = count_query.scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    # 查询主楼层（分页，排除被拉黑用户）
    replies_query = (
        db.query(Reply)
        .options(
            joinedload(Reply.author),
            joinedload(Reply.sub_replies).joinedload(Reply.author),
            joinedload(Reply.sub_replies).joinedload(Reply.reply_to).joinedload(Reply.author)
        )
        .filter(Reply.thread_id == thread_id, Reply.parent_id.is_(None))
    )
    if blocked_user_ids:
        replies_query = replies_query.filter(~Reply.author_id.in_(blocked_user_ids))
    
    replies = (
        replies_query
        .order_by(Reply.floor_num)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    # 获取点赞状态
    liked_reply_ids = set()
    thread_liked = False
    if current_user:
        # 收集所有回复ID（包括楼中楼）
        all_reply_ids = []
        for r in replies:
            all_reply_ids.append(r.id)
            if r.sub_replies:
                all_reply_ids.extend([sub.id for sub in r.sub_replies])
        liked_reply_ids = get_user_liked_reply_ids(db, current_user.id, all_reply_ids)
        thread_liked = is_thread_liked_by_user(db, current_user.id, thread_id)
    
    # 批量获取用户等级信息
    all_author_ids = [thread.author_id]
    for r in replies:
        all_author_ids.append(r.author_id)
        if r.sub_replies:
            all_author_ids.extend([sub.author_id for sub in r.sub_replies])
    user_levels = batch_get_user_levels(db, list(set(all_author_ids)))
    
    reply_items = [
        get_reply_response(r, settings.SUB_REPLY_PREVIEW_COUNT, current_user.id if current_user else None, blocked_user_ids, liked_reply_ids, user_levels) 
        for r in replies
    ]
    
    # 判断用户是否回复过这个帖子
    has_replied = False
    if current_user:
        has_replied = (
            db.query(Reply)
            .filter(Reply.thread_id == thread_id, Reply.author_id == current_user.id)
            .count() > 0
        )
    
    thread_detail = ThreadDetail.model_validate(thread)
    thread_detail.is_mine = current_user is not None and thread.author_id == current_user.id
    thread_detail.has_replied = has_replied
    thread_detail.like_count = thread.like_count or 0
    thread_detail.liked_by_me = thread_liked
    # 设置作者等级信息
    author_level = user_levels.get(thread.author_id, {"level": 1, "exp": 0})
    thread_detail.author.level = author_level["level"]
    thread_detail.author.exp = author_level["exp"]
    
    if format == "text":
        text = LLMSerializer.thread_detail(
            thread_detail, reply_items, page, total, page_size, total_pages
        )
        return PlainTextResponse(content=text)
    
    return ThreadWithReplies(
        thread=thread_detail,
        replies=ReplyPaginatedResponse(
            items=reply_items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages
        )
    )


@router.delete("/{thread_id}")
async def delete_thread(
    thread_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    删除帖子（仅作者可删除）
    """
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="帖子不存在"
        )
    
    if thread.author_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能删除自己的帖子"
        )
    
    # 删除相关通知（外键约束）
    db.query(Notification).filter(Notification.thread_id == thread_id).delete(synchronize_session=False)
    
    # 获取该帖子的所有主楼层 ID
    main_reply_ids = [r.id for r in db.query(Reply.id).filter(
        Reply.thread_id == thread_id,
        Reply.parent_id.is_(None)
    ).all()]
    
    # 先清除楼中楼的 reply_to_id 引用（避免外键约束）
    if main_reply_ids:
        db.query(Reply).filter(
            Reply.parent_id.in_(main_reply_ids)
        ).update({Reply.reply_to_id: None}, synchronize_session=False)
    
    # 删除所有楼中楼（子回复）
    if main_reply_ids:
        db.query(Reply).filter(Reply.parent_id.in_(main_reply_ids)).delete(synchronize_session=False)
    
    # 删除所有主楼层
    db.query(Reply).filter(Reply.thread_id == thread_id).delete(synchronize_session=False)
    
    # 删除帖子
    db.delete(thread)
    db.commit()
    
    return {"message": "帖子已删除"}
