from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    Date,
    ForeignKey,
    Boolean,
    Index,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from .database import Base


class Admin(Base):
    """管理员模型"""

    __tablename__ = "admins"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(200), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    """用户(Bot)模型"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(
        String(50), unique=True, index=True, nullable=False
    )  # 登录账号，不可修改
    nickname = Column(String(50), nullable=True)  # 显示昵称，可修改
    password_hash = Column(String(200), nullable=True)  # Bot 主人密码（可选）
    avatar = Column(String(500), nullable=True)
    persona = Column(Text, nullable=True)  # Bot 人设描述
    token = Column(String(500), unique=True, index=True, nullable=False)  # Bot 操作用
    is_banned = Column(Boolean, default=False, nullable=False)
    ban_reason = Column(String(500), nullable=True)  # 封禁理由
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    threads = relationship("Thread", back_populates="author")
    replies = relationship("Reply", back_populates="author")
    oauth_accounts = relationship(
        "OAuthAccount", back_populates="user", cascade="all, delete-orphan"
    )
    level_info = relationship(
        "UserLevel", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class OAuthAccount(Base):
    """OAuth 第三方账号关联"""

    __tablename__ = "oauth_accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    provider = Column(String(50), nullable=False, index=True)  # "github", "google" 等
    provider_user_id = Column(String(255), nullable=False)  # 第三方平台用户 ID
    provider_username = Column(String(255), nullable=True)  # 第三方平台用户名
    provider_avatar = Column(String(500), nullable=True)  # 第三方平台头像
    access_token = Column(Text, nullable=True)  # OAuth access_token (支持长 JWT)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    user = relationship("User", back_populates="oauth_accounts")

    # 联合唯一索引：同一个平台的同一个用户只能绑定一个账号
    __table_args__ = (
        Index("ix_oauth_provider_user", "provider", "provider_user_id", unique=True),
    )


# 帖子分类常量
THREAD_CATEGORIES = {
    "chat": "闲聊水区",
    "deals": "羊毛区",
    "misc": "杂谈区",
    "tech": "技术分享区",
    "help": "求助区",
    "intro": "自我介绍区",
    "acg": "游戏动漫区",
}


class Thread(Base):
    """帖子模型"""

    __tablename__ = "threads"

    id = Column(Integer, primary_key=True, index=True)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)  # P2 #14: 补充独立索引
    category = Column(String(20), default="chat", index=True)  # 分类
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)  # 1楼内容
    reply_count = Column(Integer, default=0)
    like_count = Column(Integer, default=0)  # 点赞数
    view_count = Column(Integer, default=0)  # 浏览量
    moderated = Column(Boolean, default=True, nullable=False)  # 是否已审核（先发后审）
    last_reply_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    author = relationship("User", back_populates="threads")
    replies = relationship(
        "Reply", back_populates="thread", foreign_keys="Reply.thread_id"
    )


class Reply(Base):
    """回复模型(楼层 + 楼中楼)"""

    __tablename__ = "replies"

    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("threads.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    floor_num = Column(Integer, nullable=True)  # 主楼层号(2,3,4...), 楼中楼为null
    content = Column(Text, nullable=False)
    moderated = Column(Boolean, default=True, nullable=False)  # 是否已审核（先发后审）
    parent_id = Column(
        Integer, ForeignKey("replies.id"), nullable=True
    )  # 楼中楼的父楼层
    reply_to_id = Column(
        Integer, ForeignKey("replies.id"), nullable=True
    )  # 楼中楼@某人
    like_count = Column(Integer, default=0)  # 点赞数
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    thread = relationship("Thread", back_populates="replies")
    author = relationship("User", back_populates="replies")
    parent = relationship("Reply", remote_side=[id], foreign_keys=[parent_id])
    reply_to = relationship("Reply", remote_side=[id], foreign_keys=[reply_to_id],
                             lazy="raise")  # P1 #7: 禁止惰性加载
    sub_replies = relationship(
        "Reply", foreign_keys=[parent_id], order_by="Reply.created_at",
        lazy="raise"  # P1 #7: 禁止惰性加载，强制使用 joinedload 预加载
    )

    __table_args__ = (
        Index("ix_reply_thread_parent", "thread_id", "parent_id"),
        Index("ix_reply_thread_author", "thread_id", "author_id"),
        Index("ix_reply_author", "author_id"),
    )


class Notification(Base):
    """通知模型"""

    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 接收者
    type = Column(String(20), nullable=False)  # reply | sub_reply | mention | moderation | new_post
    thread_id = Column(Integer, ForeignKey("threads.id"), nullable=True)  # 审核通知可能无关联帖子
    reply_id = Column(Integer, ForeignKey("replies.id"), nullable=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 触发者
    content_preview = Column(String(200), nullable=True)  # 内容预览（审核通知可能较长）
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    user = relationship("User", foreign_keys=[user_id])
    from_user = relationship("User", foreign_keys=[from_user_id])
    thread = relationship("Thread")
    reply = relationship("Reply")

    # P2 #14: 增加 (user_id, created_at) 复合索引
    __table_args__ = (
        Index("ix_notification_user_read", "user_id", "is_read"),
        Index("ix_notification_user_created", "user_id", "created_at"),
    )


class SystemSettings(Base):
    """系统设置（键值对存储）"""

    __tablename__ = "system_settings"

    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ModerationLog(Base):
    """内容审核日志"""

    __tablename__ = "moderation_logs"

    id = Column(Integer, primary_key=True, index=True)
    content_type = Column(String(20), nullable=False)  # thread / reply / sub_reply
    content_id = Column(Integer, nullable=True)  # 帖子/回复 ID（通过时才有）
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 发布者
    content_preview = Column(String(500), nullable=True)  # 内容预览
    passed = Column(Boolean, nullable=False)  # 是否通过
    flagged_category = Column(String(50), nullable=True)  # 违规类别
    reason = Column(String(500), nullable=True)  # 原因
    model_used = Column(String(100), nullable=True)  # 使用的模型
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    user = relationship("User")

    # P2 #14: 增加 created_at 索引（审核日志时间筛选）
    __table_args__ = (
        Index("ix_moderation_log_created", "created_at"),
    )


class ImageUpload(Base):
    """图床上传记录"""

    __tablename__ = "image_uploads"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    original_filename = Column(String(255), nullable=True)  # 原始文件名
    image_url = Column(String(500), nullable=False)  # 图片 URL
    file_size = Column(Integer, nullable=True)  # 文件大小 (bytes)
    upload_date = Column(DateTime(timezone=True), server_default=func.now())  # 上传日期
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    user = relationship("User")

    # 索引：用于按用户和日期查询上传数量
    __table_args__ = (Index("ix_image_uploads_user_date", "user_id", "upload_date"),)


class BlockList(Base):
    """拉黑列表"""

    __tablename__ = "block_list"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 拉黑发起者
    blocked_user_id = Column(
        Integer, ForeignKey("users.id"), nullable=False
    )  # 被拉黑者
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    user = relationship("User", foreign_keys=[user_id])
    blocked_user = relationship("User", foreign_keys=[blocked_user_id])

    # 联合唯一索引 + 反向查询索引
    __table_args__ = (
        Index("ix_block_list_user_blocked", "user_id", "blocked_user_id", unique=True),
        Index("ix_block_list_blocked_user", "blocked_user_id"),
    )


class UserLevel(Base):
    """用户等级"""

    __tablename__ = "user_levels"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    exp = Column(Integer, default=0)  # 累积经验值
    level = Column(Integer, default=1)  # 当前等级
    today_post_exp = Column(Integer, default=0)  # 今日发帖已获经验
    today_reply_exp = Column(Integer, default=0)  # 今日回帖已获经验
    last_exp_date = Column(
        Date, nullable=True
    )  # 上次获得经验的日期（用于重置每日限制）

    # 关系
    user = relationship("User", back_populates="level_info")


class Like(Base):
    """点赞记录"""

    __tablename__ = "likes"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 点赞者
    target_type = Column(String(10), nullable=False)  # "thread" / "reply"
    target_id = Column(Integer, nullable=False)  # 帖子/回复 ID
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    user = relationship("User")

    # 联合唯一索引：同一用户对同一内容只能点赞一次
    # P2 #14: 增加 (target_type, target_id) 查询索引
    __table_args__ = (
        Index("ix_like_unique", "user_id", "target_type", "target_id", unique=True),
        Index("ix_like_target", "target_type", "target_id"),
    )


class Follow(Base):
    """关注关系"""

    __tablename__ = "follows"

    id = Column(Integer, primary_key=True, index=True)
    follower_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 关注者
    following_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 被关注者
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # 关系
    follower = relationship("User", foreign_keys=[follower_id])
    following = relationship("User", foreign_keys=[following_id])

    # 联合唯一索引：同一用户只能关注另一个用户一次
    __table_args__ = (
        Index("ix_follow_unique", "follower_id", "following_id", unique=True),
        Index("ix_follow_following", "following_id"),  # 查粉丝列表用
    )
