from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from .config import get_settings

settings = get_settings()

# 根据数据库类型配置连接参数
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

# 连接池配置
# pool_size: 常驻连接数
# max_overflow: 超出 pool_size 后可额外创建的连接数
# pool_timeout: 获取连接超时时间（秒）
# pool_recycle: 连接回收时间（秒），防止长连接被数据库断开
pool_kwargs = {}
if not settings.DATABASE_URL.startswith("sqlite"):
    # SQLite 不支持连接池配置
    pool_kwargs = {
        "pool_size": 10,
        "max_overflow": 20,
        "pool_timeout": 30,
        "pool_recycle": 1800,  # 30 minutes
    }

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,  # 自动检测连接是否有效
    **pool_kwargs
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """获取数据库会话（用于 HTTP 请求）"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    """
    获取一个短生命周期的数据库会话（用于 SSE 认证等场景）
    
    使用方式：
        db = get_db_session()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                db.expunge(user)  # 如果需要在关闭后使用对象
            return user
        finally:
            db.close()
    """
    return SessionLocal()
