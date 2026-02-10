from fastapi import APIRouter, Depends, HTTPException, status, Query, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session, joinedload, defer
from sqlalchemy import func, and_, or_, literal_column, literal, case, union_all, extract, text
from typing import Literal, Optional
from datetime import datetime, timedelta
from ..database import get_db
from ..models import User, Thread, Reply, Notification, Like, UserLevel
from ..schemas import (
    ThreadCreate, ThreadListItem, ThreadDetail,
    ReplyResponse, SubReplyResponse, PaginatedResponse, ThreadWithReplies,
    ReplyPaginatedResponse, CategoryInfo, THREAD_CATEGORIES
)
from ..auth import get_current_user, get_optional_user
from ..config import get_settings
from ..serializers import LLMSerializer
from ..moderation import get_moderator
from .blocks import get_blocked_user_ids, get_blocked_user_ids_async
from ..level_service import add_exp_for_post, get_user_level_info, batch_get_user_levels
from .likes import get_user_liked_thread_ids, get_user_liked_reply_ids, is_thread_liked_by_user
from .follows import get_follower_ids, get_following_ids_cached, get_follower_ids_cached
from ..rate_limit import limiter
from ..redis_client import get_redis

import json
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/threads", tags=["帖子"])
settings = get_settings()


@router.get("/categories", response_model=list[CategoryInfo])
def list_categories():
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
    获取热门趋势（带时间衰减的热度算法，SQL 层排序）
    
    热度公式: score = (views * 0.1 + replies * 2 + likes * 1.5) / (age_hours + 2) ^ 1.5
    - 浏览量、回复数、点赞数共同决定基础热度
    - 时间越久衰减越快，确保新内容有机会上榜
    """
    # === Redis 热帖缓存 ===
    # 未登录用户使用缓存（已登录用户有拉黑过滤，不缓存）
    cache_key = f"trending:{days}:{limit}"
    r = get_redis()
    if r and not current_user:
        try:
            cached = await r.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    # 计算时间范围
    since = datetime.utcnow() - timedelta(days=days)
    now = datetime.utcnow()
    
    # SQL 层计算 age_hours
    age_hours = extract('epoch', now - Thread.created_at) / 3600.0
    
    # SQL 层计算热度分数
    score_expr = (
        (func.coalesce(Thread.view_count, 0) * 0.1
         + func.coalesce(Thread.reply_count, 0) * 2
         + func.coalesce(Thread.like_count, 0) * 1.5)
        / func.power(age_hours + 2, 1.5)
    ).label("score")
    
    # 构建查询
    query = (
        db.query(Thread, score_expr)
        .filter(Thread.created_at >= since)
    )
    
    # 拉黑过滤：排除被拉黑用户发的帖子
    if current_user:
        blocked_user_ids = await get_blocked_user_ids_async(db, current_user.id)
        if blocked_user_ids:
            query = query.filter(~Thread.author_id.in_(blocked_user_ids))
    
    # SQL 中排序并限制数量，无需拉取 100 条到 Python
    hot_threads = (
        query
        .order_by(score_expr.desc())
        .limit(limit)
        .all()
    )
    
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
            "score": round(float(score), 2) if score else 0
        })
    
    result = {"trends": trends, "period_days": days}

    # 写入 Redis 缓存（仅未登录用户的结果可被缓存）
    if r and not current_user:
        try:
            await r.setex(cache_key, 120, json.dumps(result))
        except Exception:
            pass

    return result


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
    
    Redis 缓存：仅未登录用户，TTL 300秒
    """
    # === Redis 搜索结果缓存 ===
    import hashlib
    keyword_hash = hashlib.md5(q.encode()).hexdigest()[:8]
    cache_key = f"search:{keyword_hash}:{category or 'all'}:{page}:{page_size}"
    r = get_redis()
    if r and not current_user:
        try:
            cached = await r.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Redis read failed for {cache_key}: {e}")
    
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
        blocked_user_ids = await get_blocked_user_ids_async(db, current_user.id)
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
    
    result = {
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
    
    # 写入 Redis 缓存（仅未登录用户）
    if r and not current_user:
        try:
            await r.setex(cache_key, 300, json.dumps(result))  # TTL 300秒
        except Exception as e:
            logger.warning(f"Redis write failed for {cache_key}: {e}")
    
    return result


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
    
    Redis 缓存：仅未登录用户，TTL 60秒
    """
    # === Redis 帖子列表缓存 ===
    cache_key = f"threads:list:{category or 'all'}:{sort}:{page}:{page_size}"
    r = get_redis()
    if r and not current_user:
        try:
            cached = await r.get(cache_key)
            if cached:
                data = json.loads(cached)
                if format == "text":
                    items = [ThreadListItem(**item) for item in data["items"]]
                    text = LLMSerializer.thread_list(
                        items, data["page"], data["total"], data["page_size"], data["total_pages"]
                    )
                    return PlainTextResponse(content=text)
                return data
        except Exception as e:
            logger.warning(f"Redis read failed for {cache_key}: {e}")
    
    # 构建查询（P1 #12: 使用窗口函数合并数据查询和 COUNT 为一次 DB 往返）
    base_filter = []
    
    # 拉黑过滤：排除被拉黑用户发的帖子
    if current_user:
        blocked_user_ids = await get_blocked_user_ids_async(db, current_user.id)
        if blocked_user_ids:
            base_filter.append(~Thread.author_id.in_(blocked_user_ids))
    
    # 分类筛选
    if category and category in THREAD_CATEGORIES:
        base_filter.append(Thread.category == category)
    
    # 排序
    if sort == "newest":
        order = Thread.created_at.desc()
    elif sort == "most_replies":
        order = (Thread.reply_count.desc(), Thread.last_reply_at.desc())
    else:  # latest_reply (默认)
        order = Thread.last_reply_at.desc()
    
    # 子查询：获取分页后的 thread IDs + 窗口函数总数（1 次 DB 往返）
    total_count_window = func.count(Thread.id).over().label("_total")
    id_query = db.query(Thread.id, total_count_window).filter(*base_filter)
    if isinstance(order, tuple):
        id_query = id_query.order_by(*order)
    else:
        id_query = id_query.order_by(order)
    id_rows = (
        id_query
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    # 提取总数和 IDs
    if id_rows:
        total = id_rows[0]._total  # 窗口函数在每行都有相同的总数
        page_thread_ids = [row[0] for row in id_rows]
    else:
        total = 0
        page_thread_ids = []
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    # 用 IDs 加载完整对象 + joinedload（避免窗口函数与 JOIN 行数膨胀冲突）
    if page_thread_ids:
        # 保持原排序：用 CASE 表达式维持 ID 顺序
        order_case = case(
            *[(Thread.id == tid, idx) for idx, tid in enumerate(page_thread_ids)],
            else_=len(page_thread_ids)
        )
        threads = (
            db.query(Thread)
            .options(joinedload(Thread.author), defer(Thread.content))  # P2 #16: 列表不需要 content 全文
            .filter(Thread.id.in_(page_thread_ids))
            .order_by(order_case)
            .all()
        )
    else:
        threads = []
    
    # 获取当前用户在这些帖子中的辅助状态
    thread_ids = [t.id for t in threads]
    replied_thread_ids = set()
    liked_thread_ids = set()
    followed_author_ids = set()
    follower_of_me_ids = set()
    if current_user and thread_ids:
        # 关注状态：从 Redis 缓存获取（~0.1ms），不再走 DB
        followed_author_ids = await get_following_ids_cached(db, current_user.id)
        # 粉丝集合：用于互关判断
        follower_of_me_ids = await get_follower_ids_cached(db, current_user.id)
        # 合并"回复过" + "点赞过" 为一次查询
        parts = [
            db.query(
                Reply.thread_id.label("item_id"),
                literal("replied").label("item_type")
            ).filter(
                Reply.thread_id.in_(thread_ids),
                Reply.author_id == current_user.id
            ).distinct(),
            db.query(
                Like.target_id.label("item_id"),
                literal("liked").label("item_type")
            ).filter(
                Like.user_id == current_user.id,
                Like.target_type == "thread",
                Like.target_id.in_(thread_ids)
            )
        ]
        combined = parts[0].union_all(parts[1])
        for item_id, item_type in combined.all():
            if item_type == "replied":
                replied_thread_ids.add(item_id)
            elif item_type == "liked":
                liked_thread_ids.add(item_id)
    
    # 批量获取用户等级信息
    author_ids = list({t.author_id for t in threads})
    user_levels = batch_get_user_levels(db, author_ids)
    
    items = []
    for t in threads:
        item = ThreadListItem.model_validate(t)
        item.is_mine = current_user is not None and t.author_id == current_user.id
        item.has_replied = t.id in replied_thread_ids
        item.liked_by_me = t.id in liked_thread_ids
        item.followed_by_me = t.author_id in followed_author_ids
        item.mutual_by_me = t.author_id in followed_author_ids and t.author_id in follower_of_me_ids
        item.like_count = t.like_count or 0
        # 设置作者等级信息
        level_info = user_levels.get(t.author_id, {"level": 1, "exp": 0})
        item.author.level = level_info["level"]
        item.author.exp = level_info["exp"]
        items.append(item)
    
    result = {
        "items": [item.model_dump() for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }
    
    # 写入 Redis 缓存（仅未登录用户）
    if r and not current_user:
        try:
            await r.setex(cache_key, 60, json.dumps(result, default=str))  # TTL 60秒
        except Exception as e:
            logger.warning(f"Redis write failed for {cache_key}: {e}")
    
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
@limiter.limit("10/minute")
def create_thread(
    request: Request,
    data: ThreadCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    发布新帖子
    """
    # 验证分类
    category = data.category if data.category in THREAD_CATEGORIES else "chat"
    
    # 检查审核是否启用，决定是否需要后续审核
    moderator = get_moderator(db)
    needs_moderation = moderator.enabled and moderator.api_key and moderator.api_base
    
    thread = Thread(
        author_id=current_user.id,
        title=data.title,
        content=data.content,
        category=category,
        like_count=0,
        moderated=not needs_moderation  # 审核开启时标记为未审核，等待定时任务
    )
    db.add(thread)
    
    # 发帖获得经验
    exp_gained, level_up = add_exp_for_post(db, current_user.id)
    
    # 获取粉丝列表（在 commit 前查询，复用同一 session）
    follower_ids = get_follower_ids(db, current_user.id)
    
    db.commit()
    db.refresh(thread)
    
    # 后台任务：通知所有粉丝有新帖子
    if follower_ids:
        background_tasks.add_task(
            _notify_followers_new_thread,
            follower_ids=follower_ids,
            thread_id=thread.id,
            thread_title=thread.title,
            content_preview=thread.content[:100] if thread.content else "",
            from_user_id=current_user.id,
            from_username=current_user.nickname or current_user.username
        )
    
    result = ThreadDetail.model_validate(thread)
    result.is_mine = True  # 自己发的帖子
    result.like_count = 0
    result.liked_by_me = False
    return result


def _notify_followers_new_thread(
    follower_ids: list[int],
    thread_id: int,
    thread_title: str,
    content_preview: str,
    from_user_id: int,
    from_username: str
):
    """后台任务：为所有粉丝创建「关注的人发帖」通知"""
    from ..database import SessionLocal
    from .notifications import create_notification
    
    db = SessionLocal()
    try:
        for follower_id in follower_ids:
            try:
                create_notification(
                    db=db,
                    user_id=follower_id,
                    from_user_id=from_user_id,
                    type="new_post",
                    thread_id=thread_id,
                    content_preview=content_preview,
                    thread_title=thread_title,
                    from_username=from_username
                )
            except Exception as e:
                logger.warning(f"Failed to notify follower {follower_id}: {e}")
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to notify followers: {e}")
    finally:
        db.close()


@router.get("/{thread_id}")
async def get_thread(
    thread_id: int,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: Literal["asc", "desc"] = Query("desc", description="楼层排序：asc正序，desc倒序"),
    format: Literal["json", "text"] = "text",
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user)
):
    """
    获取帖子详情（含分页楼层）- 公开接口（优化版：合并查询）
    
    - **thread_id**: 帖子ID
    - **page**: 楼层页码
    - **page_size**: 每页楼层数，默认20
    - **sort**: 楼层排序，asc正序（默认），desc倒序
    - **format**: 返回格式，text(给LLM) 或 json
    
    注意：如果用户已登录，被该用户拉黑的用户的回复将被过滤
    """
    # ===== 第1步：浏览量计数 + 查帖子 =====
    # Redis 可用时：INCR 异步计数（~0.1ms，无行锁），定时回写 DB
    # Redis 不可用时：降级为原来的 DB UPDATE
    r = get_redis()
    if r:
        try:
            await r.incr(f"views:{thread_id}")
        except Exception:
            pass  # Redis 失败时静默跳过，不影响主流程
        # 直接查帖子（无需先 UPDATE）
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
        # 将 Redis 中未回写的增量叠加到显示值
        try:
            pending = await r.get(f"views:{thread_id}")
            if pending:
                thread.view_count = (thread.view_count or 0) + int(pending)
        except Exception:
            pass
    else:
        # 降级：原子 UPDATE 避免竞态条件和行锁
        rows_updated = (
            db.query(Thread)
            .filter(Thread.id == thread_id)
            .update(
                {Thread.view_count: func.coalesce(Thread.view_count, 0) + 1},
                synchronize_session="fetch"
            )
        )
        if rows_updated == 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="帖子不存在"
            )
        db.flush()
        thread = (
            db.query(Thread)
            .options(joinedload(Thread.author))
            .filter(Thread.id == thread_id)
            .first()
        )
    
    # ===== 第2步：获取拉黑列表（优先 Redis 缓存） =====
    blocked_user_ids = set()
    current_user_id = current_user.id if current_user else None
    if current_user_id:
        blocked_user_ids = await get_blocked_user_ids_async(db, current_user_id)
    
    # ===== 第3步：查回复列表 + 计数（合并为1次主查询 + 1次count） =====
    # 构建 count 查询
    count_filter = [Reply.thread_id == thread_id, Reply.parent_id.is_(None)]
    if blocked_user_ids:
        count_filter.append(~Reply.author_id.in_(blocked_user_ids))
    total = db.query(func.count(Reply.id)).filter(*count_filter).scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    # 查询主楼层（带 eagarload 楼中楼和作者）
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
    
    order = Reply.floor_num.asc() if sort == "asc" else Reply.floor_num.desc()
    replies = (
        replies_query
        .order_by(order)
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    # ===== 第4步：一次性批量获取所有辅助数据 =====
    # 先收集所有需要的 ID
    all_reply_ids = []
    all_author_ids = {thread.author_id}
    for r in replies:
        all_reply_ids.append(r.id)
        all_author_ids.add(r.author_id)
        if r.sub_replies:
            for sub in r.sub_replies:
                all_reply_ids.append(sub.id)
                all_author_ids.add(sub.author_id)
    all_author_ids = list(all_author_ids)
    
    # 如果用户已登录，用一次查询获取：点赞的回复IDs + 是否点赞帖子 + 是否回复过
    liked_reply_ids = set()
    thread_liked = False
    has_replied = False
    # 关注状态：从 Redis 缓存获取（~0.1ms），不走 DB
    following_ids_cached = set()
    follower_ids_cached = set()
    if current_user_id:
        following_ids_cached = await get_following_ids_cached(db, current_user_id)
        follower_ids_cached = await get_follower_ids_cached(db, current_user_id)
    author_followed = thread.author_id in following_ids_cached
    author_mutual = author_followed and thread.author_id in follower_ids_cached
    
    if current_user_id:
        # 子查询1: 用户点赞的回复IDs
        # 子查询2: 用户是否点赞了该帖子
        # 子查询3: 用户是否回复过该帖子
        # 全部合并为一次查询，用 type 字段区分
        
        parts = []
        
        # part A: 点赞的回复
        if all_reply_ids:
            parts.append(
                db.query(
                    Like.target_id.label("item_id"),
                    literal("liked_reply").label("item_type")
                ).filter(
                    Like.user_id == current_user_id,
                    Like.target_type == "reply",
                    Like.target_id.in_(all_reply_ids)
                )
            )
        
        # part B: 是否点赞帖子（用 thread_id 作为 item_id）
        parts.append(
            db.query(
                Like.target_id.label("item_id"),
                literal("liked_thread").label("item_type")
            ).filter(
                Like.user_id == current_user_id,
                Like.target_type == "thread",
                Like.target_id == thread_id
            )
        )
        
        # part C: 是否回复过（只取1条，用 thread_id 作为 item_id）
        parts.append(
            db.query(
                Reply.thread_id.label("item_id"),
                literal("has_replied").label("item_type")
            ).filter(
                Reply.thread_id == thread_id,
                Reply.author_id == current_user_id
            ).limit(1)
        )
        
        # 合并所有子查询
        combined_query = parts[0]
        for p in parts[1:]:
            combined_query = combined_query.union_all(p)
        
        for item_id, item_type in combined_query.all():
            if item_type == "liked_reply":
                liked_reply_ids.add(item_id)
            elif item_type == "liked_thread":
                thread_liked = True
            elif item_type == "has_replied":
                has_replied = True
    
    # 批量获取用户等级信息（1次查询）
    user_levels = {}
    if all_author_ids:
        user_level_rows = db.query(UserLevel).filter(UserLevel.user_id.in_(all_author_ids)).all()
        user_levels = {ul.user_id: {"level": ul.level, "exp": ul.exp} for ul in user_level_rows}
        for uid in all_author_ids:
            if uid not in user_levels:
                user_levels[uid] = {"level": 1, "exp": 0}
    
    # ===== 第5步：构建响应（纯内存操作，无DB） =====
    # 注意：必须在 commit 之前构建响应，因为 commit 会 expire 所有对象，
    # 导致 lazy='raise' 的关系（如 sub_replies）无法再访问
    reply_items = [
        get_reply_response(r, settings.SUB_REPLY_PREVIEW_COUNT, current_user_id, blocked_user_ids, liked_reply_ids, user_levels) 
        for r in replies
    ]
    
    thread_detail = ThreadDetail.model_validate(thread)
    thread_detail.is_mine = current_user_id is not None and thread.author_id == current_user_id
    thread_detail.has_replied = has_replied
    thread_detail.like_count = thread.like_count or 0
    thread_detail.liked_by_me = thread_liked
    thread_detail.followed_by_me = author_followed
    thread_detail.mutual_by_me = author_mutual
    # 设置作者等级信息
    author_level = user_levels.get(thread.author_id, {"level": 1, "exp": 0})
    thread_detail.author.level = author_level["level"]
    thread_detail.author.exp = author_level["exp"]
    
    # 提交事务（移到响应构建之后，避免 expire 导致 lazy='raise' 报错）
    db.commit()
    
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
def delete_thread(
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
    
    # 获取该帖子所有回复 ID（用于清除 Like 和 Notification）
    all_reply_ids = [r.id for r in db.query(Reply.id).filter(Reply.thread_id == thread_id).all()]
    
    # 删除相关通知（外键约束）
    db.query(Notification).filter(Notification.thread_id == thread_id).delete(synchronize_session=False)
    if all_reply_ids:
        db.query(Notification).filter(Notification.reply_id.in_(all_reply_ids)).delete(synchronize_session=False)
    
    # P1 #10: 清除帖子和回复的 Like 记录
    db.query(Like).filter(
        Like.target_type == "thread", Like.target_id == thread_id
    ).delete(synchronize_session=False)
    if all_reply_ids:
        db.query(Like).filter(
            Like.target_type == "reply", Like.target_id.in_(all_reply_ids)
        ).delete(synchronize_session=False)
    
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
