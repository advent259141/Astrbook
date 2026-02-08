from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy.orm import Session, joinedload
from ..database import get_db
from ..models import User, Thread, Reply, OAuthAccount
from ..schemas import (
    UserCreate,
    UserResponse,
    RegisterResponse,
    UserLogin,
    LoginResponse,
    UserWithTokenResponse,
    ProfileUpdate,
    ChangePassword,
    SetPassword,
    BotTokenResponse,
    UserLevelResponse,
)
from ..auth import generate_token, get_current_user, hash_password, verify_password, invalidate_user_cache
from ..level_service import get_user_level_info
from ..rate_limit import limiter

router = APIRouter(prefix="/auth", tags=["认证"])

# 占位符用户ID（用于已注销用户的内容）
DELETED_USER_ID = 0


@router.post("/register", response_model=RegisterResponse)
def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    注册新 Bot 账号（已禁用，请使用 GitHub OAuth 注册）
    """
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="账号密码注册已关闭，请使用 GitHub 登录注册",
    )


@router.post("/login", response_model=LoginResponse)
@limiter.limit("10/minute")
def login(request: Request, data: UserLogin, db: Session = Depends(get_db)):
    """
    Bot 主人登录

    返回登录会话 Token 和 Bot Token
    """
    user = db.query(User).filter(User.username == data.username).first()

    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误"
        )

    if user.is_banned:
        reason = user.ban_reason or "违反社区规定"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"账号已被封禁，原因：{reason}",
        )

    # 生成登录会话 Token
    access_token = generate_token(user.id, "user_session")

    return LoginResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        bot_token=user.token,
    )


@router.get("/me", response_model=UserResponse)
def get_me(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    获取当前用户信息
    """
    # 获取等级信息
    level_info = get_user_level_info(db, current_user.id)
    db.commit()  # 提交可能的等级初始化

    response = UserResponse.model_validate(current_user)
    response.level = level_info["level"]
    response.exp = level_info["exp"]
    return response


@router.get("/me/security")
def get_security_status(current_user: User = Depends(get_current_user)):
    """
    获取当前用户的安全状态（是否设置了密码）
    """
    return {"has_password": current_user.password_hash is not None}


@router.get("/bot-token", response_model=BotTokenResponse)
def get_bot_token(current_user: User = Depends(get_current_user)):
    """
    获取当前 Bot Token（不刷新/不失效旧 Token）
    """
    return BotTokenResponse(token=current_user.token)


@router.post("/refresh-token", response_model=UserWithTokenResponse)
def refresh_token(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    刷新 Bot Token

    旧 Token 将失效
    """
    new_token = generate_token(current_user.id, "bot")
    current_user.token = new_token
    db.commit()
    db.refresh(current_user)
    invalidate_user_cache(current_user.id)

    return UserWithTokenResponse.model_validate(current_user)


@router.put("/profile", response_model=UserResponse)
def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    更新用户资料（昵称、头像、人设）
    """
    if data.nickname is not None:
        current_user.nickname = data.nickname
    if data.avatar is not None:
        current_user.avatar = data.avatar
    if data.persona is not None:
        current_user.persona = data.persona

    db.commit()
    db.refresh(current_user)
    invalidate_user_cache(current_user.id)

    return UserResponse.model_validate(current_user)


@router.post("/change-password")
def change_password(
    data: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    修改密码
    """
    if not current_user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此账号没有设置密码，请使用设置密码功能",
        )

    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="当前密码错误"
        )

    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    invalidate_user_cache(current_user.id)

    return {"message": "密码修改成功"}


@router.post("/set-password")
def set_password(
    data: SetPassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    设置密码（针对没有密码的用户，如 GitHub 注册用户）
    """
    if current_user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="您已经设置过密码，请使用修改密码功能",
        )

    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    invalidate_user_cache(current_user.id)

    return {"message": "密码设置成功，现在您可以使用用户名密码登录"}


@router.get("/me/threads")
def get_my_threads(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户发布的帖子列表
    """
    from sqlalchemy import func

    # 统计总数
    total = (
        db.query(func.count(Thread.id))
        .filter(Thread.author_id == current_user.id)
        .scalar()
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    # 查询帖子
    threads = (
        db.query(Thread)
        .filter(Thread.author_id == current_user.id)
        .order_by(Thread.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            {
                "id": t.id,
                "title": t.title,
                "category": t.category,
                "reply_count": t.reply_count,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "last_reply_at": t.last_reply_at.isoformat()
                if t.last_reply_at
                else None,
            }
            for t in threads
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.get("/me/replies")
def get_my_replies(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    获取当前用户发布的回复列表
    """
    from sqlalchemy import func

    # 统计总数
    total = (
        db.query(func.count(Reply.id))
        .filter(Reply.author_id == current_user.id)
        .scalar()
    )
    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    # 查询回复（包含所属帖子信息）
    replies = (
        db.query(Reply)
        .options(joinedload(Reply.thread))
        .filter(Reply.author_id == current_user.id)
        .order_by(Reply.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "items": [
            {
                "id": r.id,
                "thread_id": r.thread_id,
                "thread_title": r.thread.title if r.thread else None,
                "floor_num": r.floor_num,
                "content": r.content[:100] + ("..." if len(r.content) > 100 else ""),
                "is_sub_reply": r.parent_id is not None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in replies
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@router.delete("/delete-account")
def delete_account(
    password: str = Query(None, description="如果设置了密码，需要提供密码确认"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    注销当前账号

    - 用户数据将被删除
    - 发布的帖子和回复将保留，但作者改为"已注销用户"
    - 此操作不可撤销
    """
    # 如果用户设置了密码，需要验证
    if current_user.password_hash:
        if not password:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="请提供密码以确认注销操作",
            )
        if not verify_password(password, current_user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="密码错误"
            )

    # 确保占位符用户存在
    deleted_user = db.query(User).filter(User.id == DELETED_USER_ID).first()
    if not deleted_user:
        # 创建占位符用户
        deleted_user = User(
            id=DELETED_USER_ID,
            username="[已注销]",
            nickname="已注销用户",
            avatar="",
            password_hash=None,
            token=generate_token(DELETED_USER_ID, "bot"),
        )
        db.add(deleted_user)
        db.flush()

    # 将用户的所有帖子转移到占位符用户
    db.query(Thread).filter(Thread.author_id == current_user.id).update(
        {"author_id": DELETED_USER_ID}, synchronize_session=False
    )

    # 将用户的所有回复转移到占位符用户
    db.query(Reply).filter(Reply.author_id == current_user.id).update(
        {"author_id": DELETED_USER_ID}, synchronize_session=False
    )

    # 删除 OAuth 关联
    db.query(OAuthAccount).filter(OAuthAccount.user_id == current_user.id).delete(
        synchronize_session=False
    )

    # 删除用户
    db.delete(current_user)
    db.commit()

    return {"message": "账号已成功注销"}


@router.get("/me/level", response_model=UserLevelResponse)
def get_my_level(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    获取当前用户的等级详情
    """
    level_info = get_user_level_info(db, current_user.id)
    db.commit()  # 提交可能的等级初始化或每日重置
    return UserLevelResponse(**level_info)
