from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from .config import get_settings
from .database import get_db
from .models import User, Admin
import secrets
import threading
import time

settings = get_settings()
security = HTTPBearer()

# 密码加密
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ===== 用户认证内存缓存（TTL 60 秒） =====
# 键: user_id -> (User 对象快照, 过期时间戳)
_user_cache: dict[int, tuple[User, float]] = {}
_user_cache_lock = threading.Lock()
_USER_CACHE_TTL = 60  # 秒


def _get_cached_user(db: Session, user_id: int) -> Optional[User]:
    """从缓存获取用户，未命中则查 DB 并写入缓存"""
    now = time.monotonic()

    with _user_cache_lock:
        entry = _user_cache.get(user_id)
        if entry and entry[1] > now:
            # 将缓存中已分离的对象合并到当前 Session，避免 DetachedInstanceError
            return db.merge(entry[0], load=False)

    # Cache miss — query DB
    user = db.query(User).filter(User.id == user_id).first()
    if user is not None:
        # 预加载所有列属性，确保 expunge 后不触发懒加载
        db.refresh(user)
        db.expunge(user)
        with _user_cache_lock:
            _user_cache[user_id] = (user, now + _USER_CACHE_TTL)
        # 将 expunged 对象合并到当前 Session 以供本次请求使用
        return db.merge(user, load=False)
    return user


def invalidate_user_cache(user_id: int):
    """主动失效用户缓存（封禁/修改资料/改密码时调用）"""
    with _user_cache_lock:
        _user_cache.pop(user_id, None)


def _truncate_password(password: str) -> str:
    """截断密码到 72 字节（bcrypt 限制）"""
    return password.encode("utf-8")[:72].decode("utf-8", errors="ignore")


def hash_password(password: str) -> str:
    """加密密码"""
    return pwd_context.hash(_truncate_password(password))


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return pwd_context.verify(_truncate_password(plain_password), hashed_password)


def generate_token(user_id: int, token_type: str = "user") -> str:
    """生成 JWT token"""
    # Set expiration based on token type
    if token_type == "user_session":
        # User session tokens expire in 7 days
        expire = datetime.utcnow() + timedelta(days=7)
    elif token_type == "bot":
        # Bot tokens expire in 1 year (long-lived for API access)
        expire = datetime.utcnow() + timedelta(days=365)
    elif token_type == "admin":
        # Admin tokens expire in 1 day
        expire = datetime.utcnow() + timedelta(days=1)
    else:
        # Default expiration: 7 days
        expire = datetime.utcnow() + timedelta(days=7)

    payload = {
        "sub": str(user_id),
        "type": token_type,
        "iat": datetime.utcnow(),
        "exp": expire,
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> tuple[Optional[int], Optional[str]]:
    """验证 token，返回 (user_id, token_type)"""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id = payload.get("sub")
        token_type = payload.get("type", "user")
        if user_id is None:
            return None, None
        return int(user_id), token_type
    except JWTError:
        return None, None


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> User:
    """获取当前用户（支持 Bot Token 和用户会话 Token）"""
    token = credentials.credentials
    user_id, token_type = verify_token(token)

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的认证凭据",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 支持 bot token 和 user_session token
    if token_type not in ("bot", "user", "user_session"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="无效的 Token 类型",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = _get_cached_user(db, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 如果是 Bot Token，验证是否匹配
    if token_type == "bot" and user.token != token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已失效",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user.is_banned:
        reason = user.ban_reason or "违反社区规定"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"账号已被封禁，原因：{reason}",
        )

    return user


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    ),
    db: Session = Depends(get_db),
) -> Optional[User]:
    """获取当前用户（可选，允许未登录访问）"""
    if credentials is None:
        return None

    token = credentials.credentials
    user_id, token_type = verify_token(token)

    if user_id is None:
        return None

    # 支持 bot token 和 user_session token
    if token_type not in ("bot", "user", "user_session"):
        return None

    user = _get_cached_user(db, user_id)
    if user is None:
        return None

    # 如果是 Bot Token，验证是否匹配
    if token_type == "bot" and user.token != token:
        return None

    return user


async def verify_admin(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> Admin:
    """验证管理员"""
    token = credentials.credentials
    admin_id, token_type = verify_token(token)

    if admin_id is None or token_type != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限"
        )

    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="管理员不存在"
        )

    return admin
