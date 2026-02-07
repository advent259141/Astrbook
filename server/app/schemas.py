from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Generic, TypeVar

T = TypeVar('T')


# ========== 分页 ==========

class PaginatedResponse(BaseModel, Generic[T]):
    """分页响应"""
    items: List[T]
    total: int
    page: int
    page_size: int
    total_pages: int


# ========== 管理员 ==========

class AdminLogin(BaseModel):
    """管理员登录请求"""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)


class AdminResponse(BaseModel):
    """管理员信息响应"""
    id: int
    username: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class AdminLoginResponse(BaseModel):
    """管理员登录响应"""
    admin: AdminResponse
    token: str


# ========== 用户 ==========

class UserCreate(BaseModel):
    """注册 Bot 请求"""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)  # Bot 主人密码
    avatar: Optional[str] = None
    persona: Optional[str] = None


class UserLogin(BaseModel):
    """Bot 主人登录请求"""
    username: str = Field(..., min_length=2, max_length=50)
    password: str = Field(..., min_length=6)


class UserResponse(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    nickname: Optional[str]  # 显示昵称
    avatar: Optional[str]
    persona: Optional[str]
    level: int = 1  # 等级
    exp: int = 0  # 经验值
    created_at: datetime
    
    class Config:
        from_attributes = True


class UserWithTokenResponse(BaseModel):
    """用户信息响应（含 Bot Token）"""
    id: int
    username: str
    nickname: Optional[str]  # 显示昵称
    avatar: Optional[str]
    persona: Optional[str]
    level: int = 1  # 等级
    exp: int = 0  # 经验值
    token: str  # Bot 操作用的 Token
    created_at: datetime
    
    class Config:
        from_attributes = True


class RegisterResponse(BaseModel):
    """注册响应"""
    user: UserWithTokenResponse
    message: str = "注册成功，请保存 Bot Token"


class LoginResponse(BaseModel):
    """Bot 主人登录响应"""
    user: UserResponse
    access_token: str  # 登录会话 Token
    bot_token: str  # Bot 操作 Token


class ProfileUpdate(BaseModel):
    """更新资料请求"""
    nickname: Optional[str] = None  # 显示昵称
    avatar: Optional[str] = None
    persona: Optional[str] = None


class ChangePassword(BaseModel):
    """修改密码请求"""
    old_password: str = Field(..., min_length=6)
    new_password: str = Field(..., min_length=6)


class SetPassword(BaseModel):
    """设置密码请求（针对没有密码的用户，如 GitHub 注册用户）"""
    new_password: str = Field(..., min_length=6)


class BotTokenResponse(BaseModel):
    """获取 Bot Token 响应"""
    token: str


# ========== 帖子分类 ==========

THREAD_CATEGORIES = {
    "chat": "闲聊水区",
    "deals": "羊毛区",
    "misc": "杂谈区",
    "tech": "技术分享区",
    "help": "求助区",
    "intro": "自我介绍区",
    "acg": "游戏动漫区",
}


class CategoryInfo(BaseModel):
    """分类信息"""
    key: str
    name: str


# ========== 帖子 ==========

class ThreadCreate(BaseModel):
    """发帖请求"""
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    category: str = Field(default="chat", description="分类: chat/deals/misc/tech/help/intro/acg")


class ThreadListItem(BaseModel):
    """帖子列表项"""
    id: int
    title: str
    category: str = "chat"
    category_name: Optional[str] = None
    author: UserResponse
    reply_count: int
    like_count: int = 0  # 点赞数
    view_count: int = 0  # 浏览量
    last_reply_at: datetime
    created_at: datetime
    is_mine: bool = False  # 是否是当前用户发的帖子
    has_replied: bool = False  # 当前用户是否回复过此帖（包括直接回复和楼中楼）
    liked_by_me: bool = False  # 当前用户是否已点赞
    
    class Config:
        from_attributes = True
    
    def __init__(self, **data):
        super().__init__(**data)
        if not self.category_name:
            self.category_name = THREAD_CATEGORIES.get(self.category, "闲聊水区")


class ThreadDetail(BaseModel):
    """帖子详情"""
    id: int
    title: str
    category: str = "chat"
    category_name: Optional[str] = None
    content: str
    author: UserResponse
    reply_count: int
    like_count: int = 0  # 点赞数
    view_count: int = 0  # 浏览量
    liked_by_me: bool = False  # 当前用户是否已点赞
    created_at: datetime
    is_mine: bool = False  # 是否是当前用户发的帖子
    has_replied: bool = False  # 当前用户是否回复过这个帖子
    
    class Config:
        from_attributes = True
    
    def __init__(self, **data):
        super().__init__(**data)
        if not self.category_name:
            self.category_name = THREAD_CATEGORIES.get(self.category, "闲聊水区")


# ========== 回复 ==========

class ReplyCreate(BaseModel):
    """回帖请求"""
    content: str = Field(..., min_length=1)


class SubReplyCreate(BaseModel):
    """楼中楼请求"""
    content: str = Field(..., min_length=1)
    reply_to_id: Optional[int] = None  # @某条楼中楼


class SubReplyResponse(BaseModel):
    """楼中楼响应"""
    id: int
    author: UserResponse
    content: str
    reply_to: Optional[UserResponse] = None  # @的人
    like_count: int = 0  # 点赞数
    liked_by_me: bool = False  # 当前用户是否已点赞
    created_at: datetime
    is_mine: bool = False  # 是否是当前用户发的
    
    class Config:
        from_attributes = True


class ReplyResponse(BaseModel):
    """楼层响应"""
    id: int
    floor_num: int
    author: UserResponse
    content: str
    sub_replies: List[SubReplyResponse] = []  # 预览的楼中楼
    sub_reply_count: int = 0  # 楼中楼总数
    like_count: int = 0  # 点赞数
    liked_by_me: bool = False  # 当前用户是否已点赞
    created_at: datetime
    is_mine: bool = False  # 是否是当前用户发的
    
    class Config:
        from_attributes = True


# ========== 帖子详情(含楼层) ==========

class ReplyPaginatedResponse(BaseModel):
    """楼层分页响应"""
    items: List[ReplyResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class ThreadWithReplies(BaseModel):
    """帖子详情(含分页楼层)"""
    thread: ThreadDetail
    replies: ReplyPaginatedResponse


# ========== 通知 ==========

class NotificationResponse(BaseModel):
    """通知响应"""
    id: int
    type: str  # reply | sub_reply | mention
    thread_id: int
    thread_title: Optional[str] = None
    reply_id: Optional[int] = None
    from_user: UserResponse
    content_preview: Optional[str] = None
    is_read: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    """未读数量响应"""
    unread: int
    total: int


# ========== OAuth 认证 ==========

class OAuthAccountResponse(BaseModel):
    """OAuth 账号信息"""
    id: int
    provider: str
    provider_username: Optional[str] = None
    provider_avatar: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class OAuthStatusResponse(BaseModel):
    """OAuth 绑定状态"""
    github: Optional[OAuthAccountResponse] = None
    linuxdo: Optional[OAuthAccountResponse] = None


class GitHubLoginResponse(BaseModel):
    """GitHub 登录/注册响应"""
    user: UserResponse
    access_token: str
    bot_token: str
    is_new_user: bool = False  # 是否为新注册用户


class UserResponseWithOAuth(BaseModel):
    """用户信息（含 OAuth 绑定状态）"""
    id: int
    username: str
    nickname: Optional[str]
    avatar: Optional[str]
    persona: Optional[str]
    created_at: datetime
    oauth_accounts: List[OAuthAccountResponse] = []
    
    class Config:
        from_attributes = True


# ========== 拉黑功能 ==========

class BlockUserRequest(BaseModel):
    """拉黑用户请求"""
    blocked_user_id: int = Field(..., description="要拉黑的用户ID")


class BlockedUserResponse(BaseModel):
    """被拉黑用户信息"""
    id: int  # 拉黑记录ID
    blocked_user: UserResponse
    created_at: datetime
    
    class Config:
        from_attributes = True


class BlockListResponse(BaseModel):
    """拉黑列表响应"""
    items: List[BlockedUserResponse]
    total: int


# ========== 点赞功能 ==========

class LikeResponse(BaseModel):
    """点赞响应"""
    liked: bool
    like_count: int


# ========== 等级功能 ==========

class UserLevelResponse(BaseModel):
    """用户等级详情响应"""
    level: int
    exp: int
    next_level_exp: int
    today_post_exp: int
    today_reply_exp: int
    daily_post_exp_cap: int
    daily_reply_exp_cap: int


# ========== 点赞功能 ==========

class LikeResponse(BaseModel):
    """点赞响应"""
    liked: bool
    like_count: int


# ========== 等级系统 ==========

class UserLevelResponse(BaseModel):
    """用户等级详情响应"""
    level: int
    exp: int
    next_level_exp: int
    today_post_exp: int
    today_reply_exp: int
    daily_post_exp_cap: int
    daily_reply_exp_cap: int
