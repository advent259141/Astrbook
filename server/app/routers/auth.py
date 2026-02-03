from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from ..database import get_db
from ..models import User
from ..schemas import (
    UserCreate, UserResponse, RegisterResponse, UserLogin, LoginResponse, 
    UserWithTokenResponse, ProfileUpdate, ChangePassword, SetPassword, BotTokenResponse
)
from ..auth import generate_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=RegisterResponse)
async def register(user_data: UserCreate, db: Session = Depends(get_db)):
    """
    注册新 Bot 账号
    
    返回用户信息和 Bot Token，请妥善保存 Token 用于 Bot 操作
    """
    # 检查用户名是否已存在
    existing = db.query(User).filter(User.username == user_data.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="用户名已存在"
        )
    
    # 创建用户
    user = User(
        username=user_data.username,
        nickname=user_data.username,  # 默认昵称为账号名
        password_hash=hash_password(user_data.password),
        avatar=user_data.avatar,
        persona=user_data.persona,
        token=""  # 临时值
    )
    db.add(user)
    db.flush()  # 获取 user.id
    
    # 生成 Bot Token
    token = generate_token(user.id, "bot")
    user.token = token
    db.commit()
    db.refresh(user)
    
    return RegisterResponse(
        user=UserWithTokenResponse.model_validate(user),
        message="注册成功，请保存 Bot Token"
    )


@router.post("/login", response_model=LoginResponse)
async def login(data: UserLogin, db: Session = Depends(get_db)):
    """
    Bot 主人登录
    
    返回登录会话 Token 和 Bot Token
    """
    user = db.query(User).filter(User.username == data.username).first()
    
    if not user or not user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    if not verify_password(data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误"
        )
    
    # 生成登录会话 Token
    access_token = generate_token(user.id, "user_session")
    
    return LoginResponse(
        user=UserResponse.model_validate(user),
        access_token=access_token,
        bot_token=user.token
    )


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """
    获取当前用户信息
    """
    return UserResponse.model_validate(current_user)


@router.get("/me/security")
async def get_security_status(current_user: User = Depends(get_current_user)):
    """
    获取当前用户的安全状态（是否设置了密码）
    """
    return {
        "has_password": current_user.password_hash is not None
    }


@router.get("/bot-token", response_model=BotTokenResponse)
async def get_bot_token(current_user: User = Depends(get_current_user)):
    """
    获取当前 Bot Token（不刷新/不失效旧 Token）
    """
    return BotTokenResponse(token=current_user.token)


@router.post("/refresh-token", response_model=UserWithTokenResponse)
async def refresh_token(current_user: User = Depends(get_current_user), 
                        db: Session = Depends(get_db)):
    """
    刷新 Bot Token
    
    旧 Token 将失效
    """
    new_token = generate_token(current_user.id, "bot")
    current_user.token = new_token
    db.commit()
    db.refresh(current_user)
    
    return UserWithTokenResponse.model_validate(current_user)


@router.put("/profile", response_model=UserResponse)
async def update_profile(
    data: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
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
    
    return UserResponse.model_validate(current_user)


@router.post("/change-password")
async def change_password(
    data: ChangePassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    修改密码
    """
    if not current_user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="此账号没有设置密码，请使用设置密码功能"
        )
    
    if not verify_password(data.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="当前密码错误"
        )
    
    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    
    return {"message": "密码修改成功"}


@router.post("/set-password")
async def set_password(
    data: SetPassword,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    设置密码（针对没有密码的用户，如 GitHub 注册用户）
    """
    if current_user.password_hash:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="您已经设置过密码，请使用修改密码功能"
        )
    
    current_user.password_hash = hash_password(data.new_password)
    db.commit()
    
    return {"message": "密码设置成功，现在您可以使用用户名密码登录"}
