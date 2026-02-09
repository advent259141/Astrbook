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
from .redis_client import init_redis, close_redis, get_redis
from .database import SessionLocal
from .models import Thread
import os
import asyncio
import logging

logger = logging.getLogger(__name__)

settings = get_settings()

# 浏览量回写任务引用（用于 shutdown 时取消）
_flush_views_task: asyncio.Task | None = None
# 批量审核任务引用（用于 shutdown 时取消）
_batch_moderation_task: asyncio.Task | None = None

# ---------- 浏览量定时回写 ----------
_FLUSH_INTERVAL = 60  # 每 60 秒回写一次

async def _flush_view_counts():
    """
    定时将 Redis 中累积的浏览量增量批量回写到数据库。
    使用 GETDEL 保证原子性：取出后立即删除，不会重复计入。
    """
    while True:
        try:
            await asyncio.sleep(_FLUSH_INTERVAL)
            r = get_redis()
            if not r:
                continue
            # 扫描所有 views:* 键
            cursor = "0"
            keys = []
            while True:
                cursor, batch = await r.scan(cursor=cursor, match="views:*", count=100)
                keys.extend(batch)
                if cursor == 0 or cursor == "0":
                    break
            if not keys:
                continue
            # 原子取出并删除
            updates: dict[int, int] = {}
            for key in keys:
                count_str = await r.getdel(key)
                if count_str:
                    try:
                        tid = int(key.split(":")[1])
                        updates[tid] = int(count_str)
                    except (ValueError, IndexError):
                        pass
            if not updates:
                continue
            # 批量写 DB
            db = SessionLocal()
            try:
                from sqlalchemy import func as sa_func
                for tid, cnt in updates.items():
                    db.query(Thread).filter(Thread.id == tid).update(
                        {Thread.view_count: sa_func.coalesce(Thread.view_count, 0) + cnt},
                        synchronize_session=False
                    )
                db.commit()
                logger.info(f"[ViewFlush] 回写 {len(updates)} 个帖子浏览量")
            except Exception as e:
                db.rollback()
                logger.warning(f"[ViewFlush] 回写失败: {e}")
            finally:
                db.close()
        except asyncio.CancelledError:
            # shutdown 时触发最后一次回写
            logger.info("[ViewFlush] 收到停止信号，执行最后一次回写...")
            r = get_redis()
            if r:
                cursor = "0"
                keys = []
                while True:
                    cursor, batch = await r.scan(cursor=cursor, match="views:*", count=100)
                    keys.extend(batch)
                    if cursor == 0 or cursor == "0":
                        break
                if keys:
                    updates = {}
                    for key in keys:
                        count_str = await r.getdel(key)
                        if count_str:
                            try:
                                tid = int(key.split(":")[1])
                                updates[tid] = int(count_str)
                            except (ValueError, IndexError):
                                pass
                    if updates:
                        db = SessionLocal()
                        try:
                            from sqlalchemy import func as sa_func
                            for tid, cnt in updates.items():
                                db.query(Thread).filter(Thread.id == tid).update(
                                    {Thread.view_count: sa_func.coalesce(Thread.view_count, 0) + cnt},
                                    synchronize_session=False
                                )
                            db.commit()
                            logger.info(f"[ViewFlush] 最终回写 {len(updates)} 个帖子浏览量")
                        except Exception:
                            db.rollback()
                        finally:
                            db.close()
            break
        except Exception as e:
            logger.warning(f"[ViewFlush] 异常: {e}")
            await asyncio.sleep(5)  # 异常后短暂等待再重试

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
    """应用启动时初始化 Redis 连接池 + SSE Pub/Sub 订阅器 + 浏览量回写任务 + 批量审核任务"""
    global _flush_views_task, _batch_moderation_task
    await init_redis()
    # 启动 SSE 跨实例 Pub/Sub 订阅（Redis 可用时）
    await get_sse_manager().start_subscriber()
    # 启动浏览量定时回写任务（Redis 可用时）
    if get_redis():
        _flush_views_task = asyncio.create_task(_flush_view_counts())
        logger.info("[ViewFlush] 浏览量定时回写任务已启动")
    # 启动批量审核定时任务
    from .moderation import run_batch_moderation_loop
    _batch_moderation_task = asyncio.create_task(run_batch_moderation_loop())
    logger.info("[BatchMod] 批量审核定时任务已启动")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭全局 httpx 客户端、浏览量回写任务、批量审核任务、SSE Pub/Sub 订阅器和 Redis 连接池"""
    global _flush_views_task, _batch_moderation_task
    from .moderation import _http_client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
    # 停止浏览量回写任务（会触发最后一次回写）
    if _flush_views_task and not _flush_views_task.done():
        _flush_views_task.cancel()
        try:
            await _flush_views_task
        except asyncio.CancelledError:
            pass
        _flush_views_task = None
    # 停止批量审核任务（会触发最后一次审核）
    if _batch_moderation_task and not _batch_moderation_task.done():
        _batch_moderation_task.cancel()
        try:
            await _batch_moderation_task
        except asyncio.CancelledError:
            pass
        _batch_moderation_task = None
    # 停止 SSE Pub/Sub 订阅
    await get_sse_manager().stop_subscriber()
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
