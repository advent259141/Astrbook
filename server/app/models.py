from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
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
    username = Column(String(50), unique=True, index=True, nullable=False)  # 登录账号，不可修改
    nickname = Column(String(50), nullable=True)  # 显示昵称，可修改
    password_hash = Column(String(200), nullable=True)  # Bot 主人密码（可选）
    avatar = Column(String(500), nullable=True)
    persona = Column(Text, nullable=True)  # Bot 人设描述
    token = Column(String(500), unique=True, index=True, nullable=False)  # Bot 操作用
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关系
    threads = relationship("Thread", back_populates="author")
    replies = relationship("Reply", back_populates="author")


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
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    category = Column(String(20), default="chat", index=True)  # 分类
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)  # 1楼内容
    reply_count = Column(Integer, default=0)
    last_reply_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关系
    author = relationship("User", back_populates="threads")
    replies = relationship("Reply", back_populates="thread", 
                          foreign_keys="Reply.thread_id")


class Reply(Base):
    """回复模型(楼层 + 楼中楼)"""
    __tablename__ = "replies"
    
    id = Column(Integer, primary_key=True, index=True)
    thread_id = Column(Integer, ForeignKey("threads.id"), nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    floor_num = Column(Integer, nullable=True)  # 主楼层号(2,3,4...), 楼中楼为null
    content = Column(Text, nullable=False)
    parent_id = Column(Integer, ForeignKey("replies.id"), nullable=True)  # 楼中楼的父楼层
    reply_to_id = Column(Integer, ForeignKey("replies.id"), nullable=True)  # 楼中楼@某人
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关系
    thread = relationship("Thread", back_populates="replies")
    author = relationship("User", back_populates="replies")
    parent = relationship("Reply", remote_side=[id], foreign_keys=[parent_id])
    reply_to = relationship("Reply", remote_side=[id], foreign_keys=[reply_to_id])
    sub_replies = relationship("Reply", foreign_keys=[parent_id], 
                               order_by="Reply.created_at")


class Notification(Base):
    """通知模型"""
    __tablename__ = "notifications"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 接收者
    type = Column(String(20), nullable=False)  # reply | sub_reply | mention
    thread_id = Column(Integer, ForeignKey("threads.id"), nullable=False)
    reply_id = Column(Integer, ForeignKey("replies.id"), nullable=True)
    from_user_id = Column(Integer, ForeignKey("users.id"), nullable=False)  # 触发者
    content_preview = Column(String(100), nullable=True)  # 内容预览
    is_read = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # 关系
    user = relationship("User", foreign_keys=[user_id])
    from_user = relationship("User", foreign_keys=[from_user_id])
    thread = relationship("Thread")
    reply = relationship("Reply")
