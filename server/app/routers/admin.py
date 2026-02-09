from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc, or_
from pydantic import BaseModel
from typing import Optional
from ..database import get_db
from ..models import (
    User,
    Thread,
    Reply,
    Admin,
    SystemSettings,
    ModerationLog,
    Notification,
    Like,
    UserLevel,
    BlockList,
    ImageUpload,
    OAuthAccount,
)
from ..schemas import AdminLogin, AdminLoginResponse, AdminResponse, THREAD_CATEGORIES
from ..auth import verify_admin, verify_password, generate_token, invalidate_user_cache
from ..moderation import fetch_available_models, DEFAULT_MODERATION_PROMPT, invalidate_moderation_cache
from ..settings_utils import get_settings_batch
from ..redis_client import get_redis

import json

router = APIRouter(prefix="/admin", tags=["管理"])


class ThreadCategoryUpdate(BaseModel):
    """修改帖子分类请求"""

    category: str


class UserBanRequest(BaseModel):
    """封禁用户请求"""

    reason: Optional[str] = None


@router.post("/login", response_model=AdminLoginResponse)
def admin_login(data: AdminLogin, db: Session = Depends(get_db)):
    """
    管理员登录
    """
    admin = db.query(Admin).filter(Admin.username == data.username).first()

    if not admin or not verify_password(data.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    token = generate_token(admin.id, "admin")

    return AdminLoginResponse(admin=AdminResponse.model_validate(admin), token=token)


@router.get("/me", response_model=AdminResponse)
def get_admin_info(admin: Admin = Depends(verify_admin)):
    """
    获取当前管理员信息
    """
    return AdminResponse.model_validate(admin)


@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db), admin: Admin = Depends(verify_admin)
):
    """
    获取平台统计数据（需要管理员权限，Redis 缓存 30 秒）
    """
    _STATS_KEY = "stats:dashboard"
    _STATS_TTL = 30
    r = get_redis()
    
    # 尝试从 Redis 读取缓存
    if r:
        try:
            cached = await r.get(_STATS_KEY)
            if cached:
                return json.loads(cached)
        except Exception:
            pass

    # P3 #21: 合并 4 次 COUNT 为 1 次查询（4 个标量子查询合并为 1 条 SQL）
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    from sqlalchemy import select
    stats_row = db.execute(
        select(
            select(func.count(Thread.id)).label("thread_count"),
            select(func.count(Reply.id)).label("reply_count"),
            select(func.count(User.id)).label("user_count"),
            select(func.count(Thread.id)).where(Thread.created_at >= today_start).label("today_threads"),
        )
    ).first()

    result = {
        "threadCount": stats_row[0],
        "replyCount": stats_row[1],
        "userCount": stats_row[2],
        "todayThreads": stats_row[3],
    }

    # 写入 Redis 缓存
    if r:
        try:
            await r.setex(_STATS_KEY, _STATS_TTL, json.dumps(result))
        except Exception:
            pass

    return result


@router.get("/users")
def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """
    获取用户列表（需要管理员权限）
    """
    query = db.query(User)
    count_query = db.query(func.count(User.id))

    if q:
        pattern = f"%{q}%"
        search_filter = or_(User.username.ilike(pattern), User.nickname.ilike(pattern))
        query = query.filter(search_filter)
        count_query = count_query.filter(search_filter)

    total = count_query.scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    users = (
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": u.id,
            "username": u.username,
            "nickname": u.nickname,
            "avatar": u.avatar,
            "persona": u.persona,
            "token": u.token,
            "is_banned": u.is_banned,
            "ban_reason": u.ban_reason,
            "created_at": u.created_at,
        }
        for u in users
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.post("/users/{user_id}/ban")
def ban_user(
    user_id: int,
    data: UserBanRequest = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """封禁用户（需要管理员权限）"""
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    user.is_banned = True
    user.ban_reason = data.reason if data and data.reason else "违反社区规定"
    db.commit()
    invalidate_user_cache(user_id)

    return {
        "message": "用户已封禁",
        "user_id": user.id,
        "is_banned": True,
        "ban_reason": user.ban_reason,
    }


@router.delete("/users/{user_id}/ban")
def unban_user(
    user_id: int, db: Session = Depends(get_db), admin: Admin = Depends(verify_admin)
):
    """解封用户（需要管理员权限）"""
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    user.is_banned = False
    user.ban_reason = None
    db.commit()
    invalidate_user_cache(user_id)

    return {"message": "用户已解封", "user_id": user.id, "is_banned": False}


@router.delete("/users/{user_id}")
def delete_user(
    user_id: int, db: Session = Depends(get_db), admin: Admin = Depends(verify_admin)
):
    """
    删除用户（需要管理员权限）
    """
    user = db.query(User).filter(User.id == user_id).first()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    # 获取用户的所有回复ID
    user_reply_ids = [
        r.id for r in db.query(Reply.id).filter(Reply.author_id == user_id).all()
    ]

    # 获取用户帖子下的所有回复ID
    threads = db.query(Thread).filter(Thread.author_id == user_id).all()
    thread_ids = [t.id for t in threads]
    thread_reply_ids = []
    if thread_ids:
        thread_reply_ids = [
            r.id
            for r in db.query(Reply.id).filter(Reply.thread_id.in_(thread_ids)).all()
        ]

    # 合并所有需要删除的回复ID
    all_reply_ids = list(set(user_reply_ids + thread_reply_ids))

    # 先删除相关通知（外键约束）
    if all_reply_ids:
        db.query(Notification).filter(Notification.reply_id.in_(all_reply_ids)).delete(
            synchronize_session=False
        )
    if thread_ids:
        db.query(Notification).filter(Notification.thread_id.in_(thread_ids)).delete(
            synchronize_session=False
        )
    # 删除该用户收到和发出的所有通知
    db.query(Notification).filter(
        (Notification.user_id == user_id) | (Notification.from_user_id == user_id)
    ).delete(synchronize_session=False)

    # P1 #10: 清除 Like 记录（用户的点赞 + 被删帖子/回复收到的点赞）
    db.query(Like).filter(Like.user_id == user_id).delete(synchronize_session=False)
    if thread_ids:
        db.query(Like).filter(
            Like.target_type == "thread", Like.target_id.in_(thread_ids)
        ).delete(synchronize_session=False)
    if all_reply_ids:
        db.query(Like).filter(
            Like.target_type == "reply", Like.target_id.in_(all_reply_ids)
        ).delete(synchronize_session=False)

    # P1 #10: 清除 UserLevel 记录
    db.query(UserLevel).filter(UserLevel.user_id == user_id).delete(synchronize_session=False)

    # P1 #10: 清除 BlockList 记录（双向）
    db.query(BlockList).filter(
        (BlockList.user_id == user_id) | (BlockList.blocked_user_id == user_id)
    ).delete(synchronize_session=False)

    # P1 #10: 清除 ImageUpload 记录
    db.query(ImageUpload).filter(ImageUpload.user_id == user_id).delete(synchronize_session=False)

    # P1 #10: 清除 OAuthAccount 记录
    db.query(OAuthAccount).filter(OAuthAccount.user_id == user_id).delete(synchronize_session=False)

    # P1 #10: 清除 ModerationLog 记录
    db.query(ModerationLog).filter(ModerationLog.user_id == user_id).delete(synchronize_session=False)

    # 清除回复中的 reply_to_id 引用（避免外键约束）
    if all_reply_ids:
        db.query(Reply).filter(Reply.reply_to_id.in_(all_reply_ids)).update(
            {Reply.reply_to_id: None}, synchronize_session=False
        )
        db.query(Reply).filter(Reply.parent_id.in_(all_reply_ids)).update(
            {Reply.parent_id: None}, synchronize_session=False
        )

    # 删除用户的所有回复
    db.query(Reply).filter(Reply.author_id == user_id).delete(synchronize_session=False)

    # 删除用户帖子下的所有回复
    for thread in threads:
        db.query(Reply).filter(Reply.thread_id == thread.id).delete(
            synchronize_session=False
        )

    # 删除用户的帖子
    db.query(Thread).filter(Thread.author_id == user_id).delete(
        synchronize_session=False
    )

    db.delete(user)
    db.commit()

    return {"message": "用户已删除"}


@router.get("/threads")
def list_threads(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """获取帖子列表（需要管理员权限），支持搜索"""
    query = db.query(Thread).options(joinedload(Thread.author))
    count_query = db.query(func.count(Thread.id))

    if q:
        pattern = f"%{q}%"
        search_filter = or_(Thread.title.ilike(pattern), Thread.content.ilike(pattern))
        query = query.filter(search_filter)
        count_query = count_query.filter(search_filter)

    total = count_query.scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    threads = (
        query.order_by(desc(Thread.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": t.id,
            "title": t.title,
            "category": t.category,
            "author": {
                "id": t.author.id,
                "username": t.author.username,
                "nickname": t.author.nickname,
                "avatar": t.author.avatar,
            }
            if t.author
            else None,
            "reply_count": t.reply_count,
            "like_count": t.like_count,
            "last_reply_at": t.last_reply_at,
            "created_at": t.created_at,
        }
        for t in threads
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.delete("/threads/{thread_id}")
def admin_delete_thread(
    thread_id: int, db: Session = Depends(get_db), admin: Admin = Depends(verify_admin)
):
    """
    删除帖子（需要管理员权限）
    """
    thread = db.query(Thread).filter(Thread.id == thread_id).first()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="帖子不存在")

    # 获取所有回复ID
    reply_ids = [
        r.id for r in db.query(Reply.id).filter(Reply.thread_id == thread_id).all()
    ]

    # 先删除相关通知（外键约束）
    db.query(Notification).filter(Notification.thread_id == thread_id).delete(
        synchronize_session=False
    )
    if reply_ids:
        db.query(Notification).filter(Notification.reply_id.in_(reply_ids)).delete(
            synchronize_session=False
        )

    # P1 #10: 清除帖子和回复的 Like 记录
    db.query(Like).filter(
        Like.target_type == "thread", Like.target_id == thread_id
    ).delete(synchronize_session=False)
    if reply_ids:
        db.query(Like).filter(
            Like.target_type == "reply", Like.target_id.in_(reply_ids)
        ).delete(synchronize_session=False)

    # 清除回复中的 reply_to_id 和 parent_id 引用（避免外键约束）
    if reply_ids:
        db.query(Reply).filter(Reply.reply_to_id.in_(reply_ids)).update(
            {Reply.reply_to_id: None}, synchronize_session=False
        )
        db.query(Reply).filter(Reply.parent_id.in_(reply_ids)).update(
            {Reply.parent_id: None}, synchronize_session=False
        )

    # 删除所有回复
    db.query(Reply).filter(Reply.thread_id == thread_id).delete(
        synchronize_session=False
    )
    db.delete(thread)
    db.commit()

    return {"message": "帖子已删除"}


@router.patch("/threads/{thread_id}/category")
def update_thread_category(
    thread_id: int,
    data: ThreadCategoryUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """
    修改帖子分类（需要管理员权限）
    """
    thread = db.query(Thread).filter(Thread.id == thread_id).first()

    if not thread:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="帖子不存在")

    # 验证分类是否有效
    if data.category not in THREAD_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的分类: {data.category}",
        )

    old_category = thread.category
    thread.category = data.category
    db.commit()

    return {
        "message": "分类已更新",
        "old_category": old_category,
        "new_category": data.category,
        "category_name": THREAD_CATEGORIES[data.category],
    }


# ========== 审核配置 ==========


class ModerationSettingsUpdate(BaseModel):
    """审核配置更新请求"""

    enabled: Optional[bool] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None
    interval: Optional[int] = None  # 审核间隔（秒）


class ModerationTestRequest(BaseModel):
    """审核测试请求"""

    content: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None


def _get_setting(db: Session, key: str, default: str = "") -> str:
    """获取设置值（使用公共工具函数）"""
    from ..settings_utils import get_setting
    return get_setting(db, key, default)


def _set_setting(db: Session, key: str, value: str):
    """设置值（使用公共工具函数）"""
    from ..settings_utils import set_setting
    set_setting(db, key, value)


@router.get("/settings/moderation")
def get_moderation_settings(
    db: Session = Depends(get_db), admin: Admin = Depends(verify_admin)
):
    """
    获取审核配置
    """
    s = get_settings_batch(db, [
        "moderation_enabled", "moderation_api_base",
        "moderation_api_key", "moderation_model", "moderation_prompt",
        "moderation_interval"
    ], defaults={
        "moderation_enabled": "false",
        "moderation_api_base": "https://api.openai.com/v1",
        "moderation_api_key": "",
        "moderation_model": "gpt-4o-mini",
        "moderation_prompt": DEFAULT_MODERATION_PROMPT,
        "moderation_interval": "60",
    })
    return {
        "enabled": s["moderation_enabled"] == "true",
        "api_base": s["moderation_api_base"],
        "api_key": s["moderation_api_key"],
        "model": s["moderation_model"],
        "prompt": s["moderation_prompt"],
        "interval": int(s["moderation_interval"]),
        "default_prompt": DEFAULT_MODERATION_PROMPT,
    }


@router.put("/settings/moderation")
async def update_moderation_settings(
    data: ModerationSettingsUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """
    更新审核配置
    """
    if data.enabled is not None:
        _set_setting(db, "moderation_enabled", "true" if data.enabled else "false")
    if data.api_base is not None:
        _set_setting(db, "moderation_api_base", data.api_base)
    if data.api_key is not None:
        _set_setting(db, "moderation_api_key", data.api_key)
    if data.model is not None:
        _set_setting(db, "moderation_model", data.model)
    if data.prompt is not None:
        _set_setting(db, "moderation_prompt", data.prompt)
    if data.interval is not None:
        _set_setting(db, "moderation_interval", str(max(10, data.interval)))  # 最小10秒

    db.commit()
    
    # 失效审核配置缓存（内存 + Redis）
    await invalidate_moderation_cache()

    return {"message": "配置已更新"}


# ========== 图床设置 ==========


class ImageBedSettingsUpdate(BaseModel):
    """图床设置更新"""

    daily_limit: Optional[int] = None
    max_size_mb: Optional[int] = None


@router.get("/settings/imagebed")
def get_imagebed_settings(
    db: Session = Depends(get_db), admin: Admin = Depends(verify_admin)
):
    """
    获取图床配置
    """
    s = get_settings_batch(db, ["imgbed_daily_limit", "imgbed_max_size"], defaults={
        "imgbed_daily_limit": "20",
        "imgbed_max_size": str(10 * 1024 * 1024),
    })
    return {
        "daily_limit": int(s["imgbed_daily_limit"]),
        "max_size_mb": int(s["imgbed_max_size"])
        // (1024 * 1024),
    }


@router.put("/settings/imagebed")
def update_imagebed_settings(
    data: ImageBedSettingsUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """
    更新图床配置
    """
    if data.daily_limit is not None:
        _set_setting(db, "imgbed_daily_limit", str(data.daily_limit))
    if data.max_size_mb is not None:
        _set_setting(db, "imgbed_max_size", str(data.max_size_mb * 1024 * 1024))

    db.commit()

    return {"message": "图床配置已更新"}


@router.get("/settings/moderation/models")
async def get_moderation_models(
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """
    从 API 获取可用模型列表
    """
    # 使用传入的参数或从数据库读取
    base = api_base or _get_setting(
        db, "moderation_api_base", "https://api.openai.com/v1"
    )
    key = api_key or _get_setting(db, "moderation_api_key", "")

    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="请先配置 API Key"
        )

    try:
        models = await fetch_available_models(base, key)
        return {"models": models}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取模型列表失败: {str(e)}",
        )


@router.post("/settings/moderation/test")
async def test_moderation(
    data: ModerationTestRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """
    测试审核配置
    """
    import httpx
    import json

    # 使用传入的参数或从数据库读取
    api_base = data.api_base or _get_setting(
        db, "moderation_api_base", "https://api.openai.com/v1"
    )
    api_key = data.api_key or _get_setting(db, "moderation_api_key", "")
    model = data.model or _get_setting(db, "moderation_model", "gpt-4o-mini")
    prompt = data.prompt or _get_setting(
        db, "moderation_prompt", DEFAULT_MODERATION_PROMPT
    )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="请先配置 API Key"
        )

    # 构建完整的 prompt（格式与批量审核一致：[id] 内容）
    numbered_content = f"[1] {data.content}"
    full_prompt = prompt.replace("{content}", numbered_content)

    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": full_prompt}],
        "temperature": 0,
        "max_tokens": 200,
    }

    try:
        from ..moderation import get_http_client
        client = get_http_client()
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        result = response.json()

        reply = result["choices"][0]["message"]["content"].strip()

        # 尝试解析 JSON 数组响应
        try:
            if reply.startswith("```"):
                reply = reply.split("```")[1]
                if reply.startswith("json"):
                    reply = reply[4:]
                reply = reply.strip()

            parsed_raw = json.loads(reply)
            # 响应是 JSON 数组，提取第一个元素给前端展示
            if isinstance(parsed_raw, list) and len(parsed_raw) > 0:
                parsed = parsed_raw[0]
            else:
                parsed = parsed_raw
            return {
                "success": True,
                "raw_response": result["choices"][0]["message"]["content"],
                "parsed": parsed,
            }
        except json.JSONDecodeError:
            return {
                "success": True,
                "raw_response": result["choices"][0]["message"]["content"],
                "parsed": None,
                "warning": "无法解析为 JSON",
            }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"测试失败: {str(e)}",
        )


# ========== 审核日志 ==========


class ModerationLogResponse(BaseModel):
    """审核日志响应"""

    id: int
    content_type: str
    content_id: Optional[int]
    user_id: int
    username: Optional[str] = None
    content_preview: Optional[str]
    passed: bool
    flagged_category: Optional[str]
    reason: Optional[str]
    model_used: Optional[str]
    created_at: str


@router.get("/moderation/logs")
def get_moderation_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    passed: Optional[bool] = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin),
):
    """
    获取审核日志列表
    """
    query = db.query(ModerationLog).options(joinedload(ModerationLog.user))
    count_query = db.query(func.count(ModerationLog.id))

    # 筛选
    if passed is not None:
        query = query.filter(ModerationLog.passed == passed)
        count_query = count_query.filter(ModerationLog.passed == passed)

    total = count_query.scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    logs = (
        query.order_by(desc(ModerationLog.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": log.id,
            "content_type": log.content_type,
            "content_id": log.content_id,
            "user_id": log.user_id,
            "username": log.user.username if log.user else None,
            "content_preview": log.content_preview,
            "passed": log.passed,
            "flagged_category": log.flagged_category,
            "reason": log.reason,
            "model_used": log.model_used,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        }
        for log in logs
    ]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/moderation/stats")
def get_moderation_stats(
    db: Session = Depends(get_db), admin: Admin = Depends(verify_admin)
):
    """
    获取审核统计
    """
    # P3 #31: 合并 3 次 COUNT 为 1 次 CASE/WHEN 聚合查询
    from sqlalchemy import case as sa_case
    stats = db.query(
        func.count(ModerationLog.id).label("total"),
        func.sum(sa_case((ModerationLog.passed == True, 1), else_=0)).label("passed"),
        func.sum(sa_case((ModerationLog.passed == False, 1), else_=0)).label("blocked"),
    ).first()

    return {
        "total": stats.total or 0,
        "passed": int(stats.passed or 0),
        "blocked": int(stats.blocked or 0),
    }
