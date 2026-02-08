from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """应用配置"""
    APP_NAME: str = "Astrbook"
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/astrbook"
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    
    # GitHub OAuth 配置
    GITHUB_CLIENT_ID: str = ""
    GITHUB_CLIENT_SECRET: str = ""
    GITHUB_CALLBACK_URL: str = "http://localhost:8000/api/auth/github/callback"
    
    # LinuxDo OAuth 配置
    LINUXDO_CLIENT_ID: str = ""
    LINUXDO_CLIENT_SECRET: str = ""
    LINUXDO_CALLBACK_URL: str = "http://localhost:8000/api/auth/linuxdo/callback"
    
    FRONTEND_URL: str = "http://localhost:5173"  # 前端地址，用于 OAuth 回调后跳转
    
    # 分页默认值
    DEFAULT_PAGE_SIZE: int = 20
    MAX_PAGE_SIZE: int = 100
    
    # 楼中楼预览数量
    SUB_REPLY_PREVIEW_COUNT: int = 3
    
    # 头像上传配置
    UPLOAD_DIR: str = "uploads"
    AVATAR_MAX_SIZE: int = 2 * 1024 * 1024  # 2MB
    ALLOWED_AVATAR_TYPES: list = ["image/jpeg", "image/png", "image/gif", "image/webp"]
    
    # Redis 配置（为空时禁用 Redis，全部降级回本地内存/DB 直查）
    REDIS_URL: str = ""
    
    # 图床配置 (CloudFlare ImgBed)
    IMGBED_API_URL: str = "https://image.astrdark.cyou"  # 图床 API 地址
    IMGBED_API_TOKEN: str = ""  # 图床 API Token
    # IMGBED_DAILY_LIMIT 和 IMGBED_MAX_SIZE 通过管理后台配置
    IMGBED_ALLOWED_TYPES: list = ["image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"]
    
    class Config:
        env_file = "../.env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
