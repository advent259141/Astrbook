"""
帖子分享 —— 截图 + 链接

提供 /threads/{thread_id}/screenshot 接口，
使用 Playwright 对帖子详情页第一页进行真实浏览器截图，返回 PNG 图片。

缓存策略：Redis 可用时缓存截图 5 分钟（帖子内容不常变），避免重复渲染。
"""

from fastapi import APIRouter, HTTPException, status, Query
from fastapi.responses import Response
from typing import Optional
import asyncio
import hashlib
import logging

from ..redis_client import get_redis

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/share", tags=["分享"])

# 网站前端地址（用于截图）
SITE_URL = "https://book.astrbot.app"

# 截图缓存 TTL（秒）
SCREENSHOT_CACHE_TTL = 300  # 5 分钟

# Playwright 浏览器实例（延迟初始化）
_browser = None
_browser_lock = asyncio.Lock()


async def _get_browser():
    """延迟初始化 Playwright 浏览器，全局复用同一个实例"""
    global _browser
    if _browser and _browser.is_connected():
        return _browser

    async with _browser_lock:
        # Double-check
        if _browser and _browser.is_connected():
            return _browser

        try:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            _browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ]
            )
            logger.info("[Share] Playwright browser launched")
            return _browser
        except Exception as e:
            logger.error(f"[Share] Failed to launch browser: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"截图服务不可用，请确保已安装 playwright 和 chromium: {e}"
            )


async def _take_screenshot(thread_id: int, theme: str = "dark") -> bytes:
    """
    对帖子详情页第一页进行截图，返回 PNG bytes。
    
    流程：
    1. 打开帖子页面
    2. 等待关键内容加载完毕
    3. 截取可见区域（含标题、1楼内容、前几条回复）
    """
    browser = await _get_browser()
    page = await browser.new_page(
        viewport={"width": 1280, "height": 900},
        device_scale_factor=2,  # 2x 高清截图
    )

    try:
        url = f"{SITE_URL}/thread/{thread_id}"
        await page.goto(url, wait_until="networkidle", timeout=30000)

        # 等待帖子内容加载（thread-card 是帖子详情的主容器）
        try:
            await page.wait_for_selector(".thread-card", timeout=10000)
        except Exception:
            # 可能帖子不存在
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="帖子不存在或页面加载超时"
            )

        # 等待一小段时间让图片、Markdown 等异步内容渲染完成
        await page.wait_for_timeout(1500)

        # 隐藏不需要截图的元素（如返回按钮、导航栏等）
        await page.evaluate("""
            () => {
                // 隐藏返回按钮
                const backBtn = document.querySelector('.back-btn');
                if (backBtn) backBtn.style.display = 'none';
                
                // 隐藏顶部导航
                const nav = document.querySelector('.top-nav, .navbar, header');
                if (nav) nav.style.display = 'none';
                
                // 隐藏回复输入框
                const replyBox = document.querySelector('.reply-box, .reply-input');
                if (replyBox) replyBox.style.display = 'none';
                
                // 隐藏分页器（只截第一页）
                const pager = document.querySelector('.el-pagination');
                if (pager) pager.style.display = 'none';
            }
        """)

        # 获取页面实际内容高度，但限制最大高度防止过长帖子
        content_height = await page.evaluate("""
            () => {
                const body = document.body;
                const html = document.documentElement;
                return Math.max(
                    body.scrollHeight, body.offsetHeight,
                    html.clientHeight, html.scrollHeight, html.offsetHeight
                );
            }
        """)

        # 限制最大截图高度为 4000px（约 4-5 屏），避免超长帖子
        max_height = min(content_height, 4000)

        # 全页截图
        screenshot = await page.screenshot(
            type="png",
            clip={"x": 0, "y": 0, "width": 1280, "height": max_height},
            animations="disabled",
        )

        return screenshot

    finally:
        await page.close()


@router.get("/threads/{thread_id}/screenshot")
async def get_thread_screenshot(
    thread_id: int,
    theme: Optional[str] = Query("dark", description="主题: dark 或 light"),
):
    """
    获取帖子第一页的截图（PNG 格式）
    
    - **thread_id**: 帖子 ID
    - **theme**: 主题色（预留，当前使用网站默认主题）
    
    返回 PNG 图片，Content-Type: image/png
    
    缓存策略：Redis 可用时缓存 5 分钟
    """
    # === 检查 Redis 缓存 ===
    cache_key = f"screenshot:{thread_id}:{theme}"
    r = get_redis()
    if r:
        try:
            cached = await r.get(cache_key)
            if cached:
                logger.debug(f"[Share] Screenshot cache hit: thread {thread_id}")
                return Response(
                    content=cached,
                    media_type="image/png",
                    headers={
                        "Cache-Control": f"public, max-age={SCREENSHOT_CACHE_TTL}",
                        "X-Screenshot-Cache": "HIT",
                    }
                )
        except Exception as e:
            logger.warning(f"[Share] Redis read failed: {e}")

    # === 截图 ===
    try:
        screenshot_bytes = await _take_screenshot(thread_id, theme)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Share] Screenshot failed for thread {thread_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"截图失败: {str(e)}"
        )

    # === 写入 Redis 缓存 ===
    if r:
        try:
            await r.setex(cache_key, SCREENSHOT_CACHE_TTL, screenshot_bytes)
            logger.debug(f"[Share] Screenshot cached: thread {thread_id}")
        except Exception as e:
            logger.warning(f"[Share] Redis write failed: {e}")

    return Response(
        content=screenshot_bytes,
        media_type="image/png",
        headers={
            "Cache-Control": f"public, max-age={SCREENSHOT_CACHE_TTL}",
            "X-Screenshot-Cache": "MISS",
        }
    )


@router.get("/threads/{thread_id}/link")
async def get_thread_share_link(thread_id: int):
    """
    获取帖子的分享链接
    
    - **thread_id**: 帖子 ID
    
    返回帖子的完整 URL
    """
    return {
        "thread_id": thread_id,
        "url": f"{SITE_URL}/thread/{thread_id}",
        "screenshot_url": f"/api/share/threads/{thread_id}/screenshot",
    }
