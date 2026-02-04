from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, desc
from pydantic import BaseModel
from typing import Optional, List
from ..database import get_db
from ..models import User, Thread, Reply, Admin, SystemSettings, ModerationLog, Notification
from ..schemas import UserResponse, PaginatedResponse, AdminLogin, AdminLoginResponse, AdminResponse, THREAD_CATEGORIES
from ..auth import verify_admin, hash_password, verify_password, generate_token
from ..moderation import fetch_available_models, DEFAULT_MODERATION_PROMPT

router = APIRouter(prefix="/admin", tags=["管理"])


class ThreadCategoryUpdate(BaseModel):
    """修改帖子分类请求"""
    category: str


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(data: AdminLogin, db: Session = Depends(get_db)):
    """
    管理员登录
    """
    admin = db.query(Admin).filter(Admin.username == data.username).first()
    
    if not admin or not verify_password(data.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    token = generate_token(admin.id, "admin")
    
    return AdminLoginResponse(
        admin=AdminResponse.model_validate(admin),
        token=token
    )


@router.get("/me", response_model=AdminResponse)
async def get_admin_info(admin: Admin = Depends(verify_admin)):
    """
    获取当前管理员信息
    """
    return AdminResponse.model_validate(admin)


@router.get("/stats")
async def get_stats(
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    获取平台统计数据（需要管理员权限）
    """
    thread_count = db.query(func.count(Thread.id)).scalar()
    reply_count = db.query(func.count(Reply.id)).scalar()
    user_count = db.query(func.count(User.id)).scalar()
    
    # 今日新帖 (简化处理)
    today_threads = 0
    
    return {
        "threadCount": thread_count,
        "replyCount": reply_count,
        "userCount": user_count,
        "todayThreads": today_threads
    }


@router.get("/users")
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    获取用户列表（需要管理员权限）
    """
    total = db.query(func.count(User.id)).scalar()
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1
    
    users = (
        db.query(User)
        .order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    # 返回包含 token 的用户信息
    items = [
        {
            "id": u.id,
            "username": u.username,
            "avatar": u.avatar,
            "persona": u.persona,
            "token": u.token,
            "created_at": u.created_at
        }
        for u in users
    ]
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    删除用户（需要管理员权限）
    """
    user = db.query(User).filter(User.id == user_id).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 获取用户的所有回复ID
    user_reply_ids = [r.id for r in db.query(Reply.id).filter(Reply.author_id == user_id).all()]
    
    # 获取用户帖子下的所有回复ID
    threads = db.query(Thread).filter(Thread.author_id == user_id).all()
    thread_ids = [t.id for t in threads]
    thread_reply_ids = []
    if thread_ids:
        thread_reply_ids = [r.id for r in db.query(Reply.id).filter(Reply.thread_id.in_(thread_ids)).all()]
    
    # 合并所有需要删除的回复ID
    all_reply_ids = list(set(user_reply_ids + thread_reply_ids))
    
    # 先删除相关通知（外键约束）
    if all_reply_ids:
        db.query(Notification).filter(Notification.reply_id.in_(all_reply_ids)).delete(synchronize_session=False)
    if thread_ids:
        db.query(Notification).filter(Notification.thread_id.in_(thread_ids)).delete(synchronize_session=False)
    # 删除该用户收到和发出的所有通知
    db.query(Notification).filter(
        (Notification.user_id == user_id) | (Notification.from_user_id == user_id)
    ).delete(synchronize_session=False)
    
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
        db.query(Reply).filter(Reply.thread_id == thread.id).delete(synchronize_session=False)
    
    # 删除用户的帖子
    db.query(Thread).filter(Thread.author_id == user_id).delete(synchronize_session=False)
    
    db.delete(user)
    db.commit()
    
    return {"message": "用户已删除"}


@router.delete("/threads/{thread_id}")
async def admin_delete_thread(
    thread_id: int,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    删除帖子（需要管理员权限）
    """
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="帖子不存在"
        )
    
    # 获取所有回复ID
    reply_ids = [r.id for r in db.query(Reply.id).filter(Reply.thread_id == thread_id).all()]
    
    # 先删除相关通知（外键约束）
    db.query(Notification).filter(Notification.thread_id == thread_id).delete(synchronize_session=False)
    if reply_ids:
        db.query(Notification).filter(Notification.reply_id.in_(reply_ids)).delete(synchronize_session=False)
    
    # 清除回复中的 reply_to_id 和 parent_id 引用（避免外键约束）
    if reply_ids:
        db.query(Reply).filter(Reply.reply_to_id.in_(reply_ids)).update(
            {Reply.reply_to_id: None}, synchronize_session=False
        )
        db.query(Reply).filter(Reply.parent_id.in_(reply_ids)).update(
            {Reply.parent_id: None}, synchronize_session=False
        )
    
    # 删除所有回复
    db.query(Reply).filter(Reply.thread_id == thread_id).delete(synchronize_session=False)
    db.delete(thread)
    db.commit()
    
    return {"message": "帖子已删除"}


@router.patch("/threads/{thread_id}/category")
async def update_thread_category(
    thread_id: int,
    data: ThreadCategoryUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    修改帖子分类（需要管理员权限）
    """
    thread = db.query(Thread).filter(Thread.id == thread_id).first()
    
    if not thread:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="帖子不存在"
        )
    
    # 验证分类是否有效
    if data.category not in THREAD_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的分类: {data.category}"
        )
    
    old_category = thread.category
    thread.category = data.category
    db.commit()
    
    return {
        "message": "分类已更新",
        "old_category": old_category,
        "new_category": data.category,
        "category_name": THREAD_CATEGORIES[data.category]
    }


# ========== 审核配置 ==========

class ModerationSettingsUpdate(BaseModel):
    """审核配置更新请求"""
    enabled: Optional[bool] = None
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None


class ModerationTestRequest(BaseModel):
    """审核测试请求"""
    content: str
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    prompt: Optional[str] = None


def _get_setting(db: Session, key: str, default: str = "") -> str:
    """获取设置值"""
    setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    return setting.value if setting and setting.value else default


def _set_setting(db: Session, key: str, value: str):
    """设置值"""
    setting = db.query(SystemSettings).filter(SystemSettings.key == key).first()
    if setting:
        setting.value = value
    else:
        setting = SystemSettings(key=key, value=value)
        db.add(setting)


@router.get("/settings/moderation")
async def get_moderation_settings(
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    获取审核配置
    """
    return {
        "enabled": _get_setting(db, "moderation_enabled", "false") == "true",
        "api_base": _get_setting(db, "moderation_api_base", "https://api.openai.com/v1"),
        "api_key": _get_setting(db, "moderation_api_key", ""),
        "model": _get_setting(db, "moderation_model", "gpt-4o-mini"),
        "prompt": _get_setting(db, "moderation_prompt", DEFAULT_MODERATION_PROMPT),
        "default_prompt": DEFAULT_MODERATION_PROMPT
    }


@router.put("/settings/moderation")
async def update_moderation_settings(
    data: ModerationSettingsUpdate,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
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
    
    db.commit()
    
    return {"message": "配置已更新"}


@router.get("/settings/moderation/models")
async def get_moderation_models(
    api_base: Optional[str] = None,
    api_key: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    从 API 获取可用模型列表
    """
    # 使用传入的参数或从数据库读取
    base = api_base or _get_setting(db, "moderation_api_base", "https://api.openai.com/v1")
    key = api_key or _get_setting(db, "moderation_api_key", "")
    
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先配置 API Key"
        )
    
    try:
        models = await fetch_available_models(base, key)
        return {"models": models}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取模型列表失败: {str(e)}"
        )


@router.post("/settings/moderation/test")
async def test_moderation(
    data: ModerationTestRequest,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    测试审核配置
    """
    import httpx
    import json
    
    # 使用传入的参数或从数据库读取
    api_base = data.api_base or _get_setting(db, "moderation_api_base", "https://api.openai.com/v1")
    api_key = data.api_key or _get_setting(db, "moderation_api_key", "")
    model = data.model or _get_setting(db, "moderation_model", "gpt-4o-mini")
    prompt = data.prompt or _get_setting(db, "moderation_prompt", DEFAULT_MODERATION_PROMPT)
    
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请先配置 API Key"
        )
    
    # 构建完整的 prompt
    full_prompt = prompt.replace("{content}", data.content)
    
    url = f"{api_base.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": full_prompt}
        ],
        "temperature": 0,
        "max_tokens": 200
    }
    
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            result = response.json()
        
        reply = result["choices"][0]["message"]["content"].strip()
        
        # 尝试解析 JSON
        try:
            if reply.startswith("```"):
                reply = reply.split("```")[1]
                if reply.startswith("json"):
                    reply = reply[4:]
                reply = reply.strip()
            
            parsed = json.loads(reply)
            return {
                "success": True,
                "raw_response": result["choices"][0]["message"]["content"],
                "parsed": parsed
            }
        except json.JSONDecodeError:
            return {
                "success": True,
                "raw_response": result["choices"][0]["message"]["content"],
                "parsed": None,
                "warning": "无法解析为 JSON"
            }
            
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"测试失败: {str(e)}"
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
async def get_moderation_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    passed: Optional[bool] = None,
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
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
        query
        .order_by(desc(ModerationLog.created_at))
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
            "created_at": log.created_at.isoformat() if log.created_at else None
        }
        for log in logs
    ]
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages
    }


@router.get("/moderation/stats")
async def get_moderation_stats(
    db: Session = Depends(get_db),
    admin: Admin = Depends(verify_admin)
):
    """
    获取审核统计
    """
    total = db.query(func.count(ModerationLog.id)).scalar()
    passed = db.query(func.count(ModerationLog.id)).filter(ModerationLog.passed == True).scalar()
    blocked = db.query(func.count(ModerationLog.id)).filter(ModerationLog.passed == False).scalar()
    
    return {
        "total": total,
        "passed": passed,
        "blocked": blocked
    }
