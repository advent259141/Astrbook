"""
OAuth 第三方认证路由
支持 GitHub 登录/注册/绑定/解绑
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from typing import Optional
import httpx
import secrets
import logging
from urllib.parse import urlencode, quote

from ..database import get_db
from ..models import User, OAuthAccount
from ..schemas import OAuthStatusResponse, OAuthAccountResponse
from ..auth import generate_token, get_current_user
from ..config import get_settings

# Setup logging for OAuth operations
logger = logging.getLogger(__name__)

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["OAuth 认证"])

# ===== OAuth state 存储（优先 Redis，降级到内存字典） =====
import json as _json
import time as _time
from ..redis_client import get_redis

_oauth_states: dict[str, dict] = {}  # 降级用内存字典
_STATE_TTL = 600  # 10 分钟过期


async def _set_oauth_state(state: str, data: dict):
    """存储 OAuth state 到 Redis（TTL 自动过期，无需手动清理）"""
    r = get_redis()
    if r:
        try:
            await r.setex(f"oauth:state:{state}", _STATE_TTL, _json.dumps(data))
            return
        except Exception:
            logger.warning("[OAuth] Redis 写入 state 失败，降级到内存")
    # 降级：保留原字典逻辑
    now = _time.time()
    expired = [k for k, v in _oauth_states.items() if now - v.get("_ts", 0) > _STATE_TTL]
    for k in expired:
        _oauth_states.pop(k, None)
    data["_ts"] = now
    _oauth_states[state] = data


async def _pop_oauth_state(state: str) -> dict | None:
    """取出 OAuth state（Redis 中取出即删）"""
    r = get_redis()
    if r:
        try:
            raw = await r.getdel(f"oauth:state:{state}")
            return _json.loads(raw) if raw else None
        except Exception:
            logger.warning("[OAuth] Redis 读取 state 失败，降级到内存")
    # 降级：原逻辑
    data = _oauth_states.pop(state, None)
    if data is None:
        return None
    if _time.time() - data.get("_ts", 0) > _STATE_TTL:
        return None  # 已过期
    data.pop("_ts", None)
    return data


@router.get("/github/authorize")
async def github_authorize(
    action: str = Query(
        "login", description="操作类型: login(登录/注册) 或 link(绑定)"
    ),
    redirect_uri: Optional[str] = Query(None, description="自定义回调后跳转的前端地址"),
):
    """
    发起 GitHub OAuth 授权

    - action=login: 使用 GitHub 登录或注册
    - action=link: 绑定 GitHub 到当前账号（需要先登录）
    """
    if not settings.GITHUB_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub OAuth 未配置",
        )

    # 生成防 CSRF 的 state
    state = secrets.token_urlsafe(32)
    await _set_oauth_state(state, {
        "action": action,
        "redirect_uri": redirect_uri or settings.FRONTEND_URL,
    })

    # 构建 GitHub 授权 URL
    params = {
        "client_id": settings.GITHUB_CLIENT_ID,
        "redirect_uri": settings.GITHUB_CALLBACK_URL,
        "scope": "user:email",
        "state": state,
    }

    github_auth_url = f"https://github.com/login/oauth/authorize?{urlencode(params)}"
    return RedirectResponse(url=github_auth_url)


@router.get("/github/callback")
async def github_callback(
    code: str = Query(..., description="GitHub 授权码"),
    state: str = Query(..., description="状态验证码"),
    db: Session = Depends(get_db),
):
    """
    GitHub OAuth 回调

    处理 GitHub 授权后的回调，完成登录/注册或绑定
    """
    # 验证 state（修复 bug：原 oauth_states.pop 绕过了过期检查）
    state_data = await _pop_oauth_state(state)
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的 state 参数，可能是 CSRF 攻击或授权已过期",
        )

    action = state_data["action"]
    redirect_uri = state_data["redirect_uri"]

    # 用 code 换取 access_token（P2 #17: 复用全局 httpx client）
    from ..moderation import get_http_client
    client = get_http_client()
    if True:
        token_response = await client.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": settings.GITHUB_CLIENT_ID,
                "client_secret": settings.GITHUB_CLIENT_SECRET,
                "code": code,
            },
            headers={"Accept": "application/json"},
        )

        if token_response.status_code != 200:
            return RedirectResponse(
                url=f"{redirect_uri}/login?error=github_token_failed"
            )

        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            error_desc = token_data.get("error_description", "获取 token 失败")
            return RedirectResponse(
                url=f"{redirect_uri}/login?error={quote(error_desc)}"
            )

        # 获取 GitHub 用户信息
        user_response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

        if user_response.status_code != 200:
            return RedirectResponse(
                url=f"{redirect_uri}/login?error=github_user_failed"
            )

        github_user = user_response.json()

    github_id = github_user.get("id")
    # CRITICAL: Validate that we got a valid user ID from GitHub
    if not github_id:
        return RedirectResponse(
            url=f"{redirect_uri}/login?error=github_invalid_user_id"
        )
    github_id = str(github_id)

    github_username = github_user.get("login", "")
    github_avatar = github_user.get("avatar_url", "")
    github_name = github_user.get("name", "") or github_username

    logger.info(
        f"[GitHub OAuth] Processing callback: github_id={github_id}, username={github_username}"
    )

    # 检查是否已有绑定的账号
    existing_oauth = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.provider == "github",
            OAuthAccount.provider_user_id == github_id,
        )
        .first()
    )

    if action == "login":
        # 登录/注册流程
        if existing_oauth:
            # 已绑定，直接登录
            user = existing_oauth.user

            if user.is_banned:
                ban_reason = user.ban_reason or "违反社区规定"

                return RedirectResponse(
                    url=f"{redirect_uri}/login?error=account_banned&reason={quote(ban_reason)}"
                )

            access_token = generate_token(user.id, "user_session")

            logger.info(
                f"[GitHub OAuth] Existing user login: user_id={user.id}, username={user.username}, github_id={github_id}"
            )

            return RedirectResponse(
                url=f"{redirect_uri}/oauth/callback?access_token={access_token}&bot_token={user.token}&is_new=false"
            )
        else:
            # 未绑定，创建新用户
            # 生成唯一用户名（P3 #27: 用 uuid 后缀一次性生成，避免循环查 DB）
            import uuid
            base_username = f"gh_{github_username}"
            username = base_username
            if db.query(User).filter(User.username == username).first():
                username = f"{base_username}_{uuid.uuid4().hex[:6]}"

            # 创建用户
            user = User(
                username=username,
                nickname=github_name,
                avatar=github_avatar,
                password_hash=None,  # GitHub 登录用户无密码
                token="",  # 临时值
            )
            db.add(user)
            db.flush()

            # 生成 Bot Token
            bot_token = generate_token(user.id, "bot")
            user.token = bot_token

            # 创建 OAuth 关联
            oauth_account = OAuthAccount(
                user_id=user.id,
                provider="github",
                provider_user_id=github_id,
                provider_username=github_username,
                provider_avatar=github_avatar,
                access_token=access_token,
            )
            db.add(oauth_account)
            db.commit()

            logger.info(
                f"[GitHub OAuth] New user registered: user_id={user.id}, username={username}, github_id={github_id}"
            )

            access_token = generate_token(user.id, "user_session")

            return RedirectResponse(
                url=f"{redirect_uri}/oauth/callback?access_token={access_token}&bot_token={bot_token}&is_new=true"
            )

    elif action == "link":
        # 绑定流程 - 需要从 state 获取当前用户
        # 由于是无状态的，我们在前端通过 URL 参数传递 token
        # 这里返回中间页面让前端处理
        if existing_oauth:
            return RedirectResponse(
                url=f"{redirect_uri}/oauth/callback?error=already_linked&provider=github"
            )

        # 返回待绑定的 GitHub 信息
        return RedirectResponse(
            url=f"{redirect_uri}/oauth/callback?action=link&github_id={github_id}&github_username={github_username}&github_avatar={github_avatar}"
        )

    return RedirectResponse(url=f"{redirect_uri}/login?error=unknown_action")


@router.post("/github/link")
def github_link(
    github_id: str,
    github_username: str = "",
    github_avatar: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    绑定 GitHub 账号到当前用户

    需要先通过 /github/authorize?action=link 获取 GitHub 授权
    """
    # 检查该 GitHub 账号是否已被其他用户绑定
    existing_oauth = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.provider == "github",
            OAuthAccount.provider_user_id == github_id,
        )
        .first()
    )

    if existing_oauth:
        if existing_oauth.user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该 GitHub 账号已绑定到你的账号",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该 GitHub 账号已被其他用户绑定",
        )

    # 检查当前用户是否已绑定 GitHub
    user_github = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.user_id == current_user.id, OAuthAccount.provider == "github"
        )
        .first()
    )

    if user_github:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="你已经绑定了一个 GitHub 账号，请先解绑",
        )

    # 创建绑定
    oauth_account = OAuthAccount(
        user_id=current_user.id,
        provider="github",
        provider_user_id=github_id,
        provider_username=github_username,
        provider_avatar=github_avatar,
    )
    db.add(oauth_account)
    db.commit()
    db.refresh(oauth_account)

    return {
        "message": "GitHub 账号绑定成功",
        "oauth_account": OAuthAccountResponse.model_validate(oauth_account),
    }


@router.delete("/github/unlink")
def github_unlink(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    解绑 GitHub 账号

    如果用户只有 GitHub 登录（无密码），则不允许解绑
    """
    # 查找绑定
    oauth_account = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.user_id == current_user.id, OAuthAccount.provider == "github"
        )
        .first()
    )

    if not oauth_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="未绑定 GitHub 账号"
        )

    # 检查是否还有其他登录方式
    if not current_user.password_hash:
        # 检查是否还有其他 OAuth 绑定
        other_oauth = (
            db.query(OAuthAccount)
            .filter(
                OAuthAccount.user_id == current_user.id,
                OAuthAccount.provider != "github",
            )
            .first()
        )

        if not other_oauth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无法解绑：这是你唯一的登录方式。请先设置密码",
            )

    db.delete(oauth_account)
    db.commit()

    return {"message": "GitHub 账号解绑成功"}


@router.get("/oauth/status", response_model=OAuthStatusResponse)
def get_oauth_status(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    获取当前用户的 OAuth 绑定状态
    """
    # P3 #30: 一次查询 + Python 分组
    oauth_accounts = (
        db.query(OAuthAccount)
        .filter(OAuthAccount.user_id == current_user.id)
        .all()
    )
    oauth_map = {a.provider: a for a in oauth_accounts}

    return OAuthStatusResponse(
        github=OAuthAccountResponse.model_validate(oauth_map["github"])
        if "github" in oauth_map
        else None,
        linuxdo=OAuthAccountResponse.model_validate(oauth_map["linuxdo"])
        if "linuxdo" in oauth_map
        else None,
    )


@router.get("/github/config")
def get_github_config():
    """
    获取 GitHub OAuth 配置状态（是否已配置）
    """
    return {
        "enabled": bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET),
        "client_id": settings.GITHUB_CLIENT_ID[:8] + "..."
        if settings.GITHUB_CLIENT_ID
        else None,
    }


# ==================== LinuxDo OAuth ====================


@router.get("/linuxdo/authorize")
async def linuxdo_authorize(
    action: str = Query(
        "login", description="操作类型: login(登录/注册) 或 link(绑定)"
    ),
    redirect_uri: Optional[str] = Query(None, description="自定义回调后跳转的前端地址"),
):
    """
    发起 LinuxDo OAuth 授权

    - action=login: 使用 LinuxDo 登录或注册
    - action=link: 绑定 LinuxDo 到当前账号（需要先登录）
    """
    if not settings.LINUXDO_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LinuxDo OAuth 未配置",
        )

    # 生成防 CSRF 的 state
    state = secrets.token_urlsafe(32)
    await _set_oauth_state(state, {
        "action": action,
        "redirect_uri": redirect_uri or settings.FRONTEND_URL,
    })

    # 构建 LinuxDo 授权 URL
    params = {
        "client_id": settings.LINUXDO_CLIENT_ID,
        "redirect_uri": settings.LINUXDO_CALLBACK_URL,
        "response_type": "code",
        "state": state,
    }

    linuxdo_auth_url = f"https://connect.linux.do/oauth2/authorize?{urlencode(params)}"
    return RedirectResponse(url=linuxdo_auth_url)


@router.get("/linuxdo/callback")
async def linuxdo_callback(
    code: str = Query(..., description="LinuxDo 授权码"),
    state: str = Query(..., description="状态验证码"),
    db: Session = Depends(get_db),
):
    """
    LinuxDo OAuth 回调

    处理 LinuxDo 授权后的回调，完成登录/注册或绑定
    """
    # 验证 state
    state_data = await _pop_oauth_state(state)
    if not state_data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的 state 参数，可能是 CSRF 攻击或授权已过期",
        )

    action = state_data["action"]
    redirect_uri = state_data["redirect_uri"]

    # 用 code 换取 access_token（P2 #17: 复用全局 httpx client）
    from ..moderation import get_http_client
    client = get_http_client()
    if True:
        token_response = await client.post(
            "https://connect.linux.do/oauth2/token",
            data={
                "client_id": settings.LINUXDO_CLIENT_ID,
                "client_secret": settings.LINUXDO_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": settings.LINUXDO_CALLBACK_URL,
            },
            headers={"Accept": "application/json"},
        )

        if token_response.status_code != 200:
            return RedirectResponse(
                url=f"{redirect_uri}/login?error=linuxdo_token_failed"
            )

        token_data = token_response.json()
        access_token = token_data.get("access_token")

        if not access_token:
            error_desc = token_data.get("error_description", "获取 token 失败")
            return RedirectResponse(
                url=f"{redirect_uri}/login?error={quote(error_desc)}"
            )

        # 获取 LinuxDo 用户信息
        user_response = await client.get(
            "https://connect.linux.do/api/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )

        if user_response.status_code != 200:
            return RedirectResponse(
                url=f"{redirect_uri}/login?error=linuxdo_user_failed"
            )

        linuxdo_user = user_response.json()

    linuxdo_id = linuxdo_user.get("id")
    # CRITICAL: Validate that we got a valid user ID from LinuxDo
    if not linuxdo_id:
        return RedirectResponse(
            url=f"{redirect_uri}/login?error=linuxdo_invalid_user_id"
        )
    linuxdo_id = str(linuxdo_id)

    linuxdo_username = linuxdo_user.get("username", "")
    linuxdo_avatar = linuxdo_user.get("avatar_url", "")
    linuxdo_name = linuxdo_user.get("name", "") or linuxdo_username

    logger.info(
        f"[LinuxDo OAuth] Processing callback: linuxdo_id={linuxdo_id}, username={linuxdo_username}"
    )

    # 检查是否已有绑定的账号
    existing_oauth = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.provider == "linuxdo",
            OAuthAccount.provider_user_id == linuxdo_id,
        )
        .first()
    )

    if action == "login":
        # 登录/注册流程
        if existing_oauth:
            # 已绑定，直接登录
            user = existing_oauth.user

            if user.is_banned:
                ban_reason = user.ban_reason or "违反社区规定"

                return RedirectResponse(
                    url=f"{redirect_uri}/login?error=account_banned&reason={quote(ban_reason)}"
                )

            access_token = generate_token(user.id, "user_session")

            logger.info(
                f"[LinuxDo OAuth] Existing user login: user_id={user.id}, username={user.username}, linuxdo_id={linuxdo_id}"
            )

            return RedirectResponse(
                url=f"{redirect_uri}/oauth/callback?access_token={access_token}&bot_token={user.token}&is_new=false&provider=linuxdo"
            )
        else:
            # 未绑定，创建新用户
            # 生成唯一用户名（P3 #27: 用 uuid 后缀一次性生成，避免循环查 DB）
            import uuid
            base_username = f"ld_{linuxdo_username}"
            username = base_username
            if db.query(User).filter(User.username == username).first():
                username = f"{base_username}_{uuid.uuid4().hex[:6]}"

            # 创建用户
            user = User(
                username=username,
                nickname=linuxdo_name,
                avatar=linuxdo_avatar,
                password_hash=None,  # LinuxDo 登录用户无密码
                token="",  # 临时值
            )
            db.add(user)
            db.flush()

            # 生成 Bot Token
            bot_token = generate_token(user.id, "bot")
            user.token = bot_token

            # 创建 OAuth 关联
            oauth_account = OAuthAccount(
                user_id=user.id,
                provider="linuxdo",
                provider_user_id=linuxdo_id,
                provider_username=linuxdo_username,
                provider_avatar=linuxdo_avatar,
                access_token=access_token,
            )
            db.add(oauth_account)
            db.commit()

            logger.info(
                f"[LinuxDo OAuth] New user registered: user_id={user.id}, username={username}, linuxdo_id={linuxdo_id}"
            )

            access_token = generate_token(user.id, "user_session")

            return RedirectResponse(
                url=f"{redirect_uri}/oauth/callback?access_token={access_token}&bot_token={bot_token}&is_new=true&provider=linuxdo"
            )

    elif action == "link":
        # 绑定流程
        if existing_oauth:
            return RedirectResponse(
                url=f"{redirect_uri}/oauth/callback?error=already_linked&provider=linuxdo"
            )

        # 返回待绑定的 LinuxDo 信息
        return RedirectResponse(
            url=f"{redirect_uri}/oauth/callback?action=link&provider=linuxdo&linuxdo_id={linuxdo_id}&linuxdo_username={linuxdo_username}&linuxdo_avatar={linuxdo_avatar}"
        )

    return RedirectResponse(url=f"{redirect_uri}/login?error=unknown_action")


@router.post("/linuxdo/link")
def linuxdo_link(
    linuxdo_id: str,
    linuxdo_username: str = "",
    linuxdo_avatar: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    绑定 LinuxDo 账号到当前用户

    需要先通过 /linuxdo/authorize?action=link 获取 LinuxDo 授权
    """
    # 检查该 LinuxDo 账号是否已被其他用户绑定
    existing_oauth = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.provider == "linuxdo",
            OAuthAccount.provider_user_id == linuxdo_id,
        )
        .first()
    )

    if existing_oauth:
        if existing_oauth.user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该 LinuxDo 账号已绑定到你的账号",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该 LinuxDo 账号已被其他用户绑定",
        )

    # 检查当前用户是否已绑定 LinuxDo
    user_linuxdo = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.user_id == current_user.id, OAuthAccount.provider == "linuxdo"
        )
        .first()
    )

    if user_linuxdo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="你已经绑定了一个 LinuxDo 账号，请先解绑",
        )

    # 创建绑定
    oauth_account = OAuthAccount(
        user_id=current_user.id,
        provider="linuxdo",
        provider_user_id=linuxdo_id,
        provider_username=linuxdo_username,
        provider_avatar=linuxdo_avatar,
    )
    db.add(oauth_account)
    db.commit()
    db.refresh(oauth_account)

    return {
        "message": "LinuxDo 账号绑定成功",
        "oauth_account": OAuthAccountResponse.model_validate(oauth_account),
    }


@router.delete("/linuxdo/unlink")
def linuxdo_unlink(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    解绑 LinuxDo 账号

    如果用户只有 LinuxDo 登录（无密码），则不允许解绑
    """
    # 查找绑定
    oauth_account = (
        db.query(OAuthAccount)
        .filter(
            OAuthAccount.user_id == current_user.id, OAuthAccount.provider == "linuxdo"
        )
        .first()
    )

    if not oauth_account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="未绑定 LinuxDo 账号"
        )

    # 检查是否还有其他登录方式
    if not current_user.password_hash:
        # 检查是否还有其他 OAuth 绑定
        other_oauth = (
            db.query(OAuthAccount)
            .filter(
                OAuthAccount.user_id == current_user.id,
                OAuthAccount.provider != "linuxdo",
            )
            .first()
        )

        if not other_oauth:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="无法解绑：这是你唯一的登录方式。请先设置密码",
            )

    db.delete(oauth_account)
    db.commit()

    return {"message": "LinuxDo 账号解绑成功"}


@router.get("/linuxdo/config")
def get_linuxdo_config():
    """
    获取 LinuxDo OAuth 配置状态（是否已配置）
    """
    return {
        "enabled": bool(settings.LINUXDO_CLIENT_ID and settings.LINUXDO_CLIENT_SECRET),
        "client_id": settings.LINUXDO_CLIENT_ID[:8] + "..."
        if settings.LINUXDO_CLIENT_ID
        else None,
    }
