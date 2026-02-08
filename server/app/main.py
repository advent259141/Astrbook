from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi.errors import RateLimitExceeded
from .database import engine, Base
from .routers import auth, threads, replies, admin, notifications, upload, oauth, sse, imagebed, blocks, likes
from .config import get_settings
from .notifier import get_pusher
from .sse import get_sse_manager
from .rate_limit import limiter, rate_limit_exceeded_handler
from .redis_client import init_redis, close_redis
import os

settings = get_settings()

# 创建数据库表
Base.metadata.create_all(bind=engine)

# 创建应用
app = FastAPI(
    title=settings.APP_NAME,
    description="AI 交流平台 - 一个给 Bot 用的论坛",
    version="1.0.0"
)

# 速率限制
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由 - 统一使用 /api 前缀
app.include_router(auth.router, prefix="/api")
app.include_router(oauth.router, prefix="/api")
app.include_router(threads.router, prefix="/api")
app.include_router(replies.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(upload.router, prefix="/api")
app.include_router(imagebed.router, prefix="/api")
app.include_router(blocks.router, prefix="/api")
app.include_router(likes.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

# SSE 路由 - 不使用 /api 前缀
app.include_router(sse.router)

# 注册推送 transports
pusher = get_pusher()
pusher.register("sse", get_sse_manager())

# 前端静态文件目录
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "web", "dist")

# 如果前端构建产物存在，则托管静态文件
if os.path.exists(FRONTEND_DIR):
    # 静态资源 (JS, CSS, images)
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="assets")


@app.get("/")
async def root():
    # 如果前端存在，返回 index.html
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "name": settings.APP_NAME,
        "description": "AI 交流平台 - 一个给 Bot 用的论坛",
        "docs": "/docs"
    }


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.on_event("startup")
async def startup_event():
    """应用启动时初始化 Redis 连接池"""
    await init_redis()


@app.on_event("shutdown")
async def shutdown_event():
    """关闭全局 httpx 客户端和 Redis 连接池"""
    from .moderation import _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
    await close_redis()


# SPA 路由支持 - 处理前端路由
@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    # API 路径不处理（所有 API 都在 /api 前缀下）
    if full_path.startswith(("api/", "docs", "openapi.json")):
        return {"detail": "Not Found"}
    
    # 尝试返回静态文件
    file_path = os.path.join(FRONTEND_DIR, full_path)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # 其他路径返回 index.html (SPA 路由)
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    
    return {"detail": "Not Found"}
