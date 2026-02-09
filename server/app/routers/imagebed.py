from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
import httpx
import logging

logger = logging.getLogger(__name__)

from ..database import get_db
from ..models import User, ImageUpload, SystemSettings
from ..auth import get_current_user
from ..config import get_settings
from ..settings_utils import get_settings_batch
from ..rate_limit import limiter
from ..redis_client import get_redis

router = APIRouter(prefix="/imagebed", tags=["图床"])
settings = get_settings()

# 默认值
DEFAULT_DAILY_LIMIT = 20
DEFAULT_MAX_SIZE = 10 * 1024 * 1024  # 10MB


def _get_imagebed_limits(db: Session) -> tuple[int, int]:
    """获取图床限制配置（1 次批量查询）"""
    s = get_settings_batch(db, ["imgbed_daily_limit", "imgbed_max_size"], defaults={
        "imgbed_daily_limit": str(DEFAULT_DAILY_LIMIT),
        "imgbed_max_size": str(DEFAULT_MAX_SIZE),
    })
    daily_limit = int(s["imgbed_daily_limit"])
    max_size = int(s["imgbed_max_size"])
    return daily_limit, max_size


@router.get("/config")
def get_imagebed_config(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取图床配置信息
    """
    daily_limit, max_size = _get_imagebed_limits(db)
    return {
        "enabled": bool(settings.IMGBED_API_TOKEN),
        "daily_limit": daily_limit,
        "max_size_mb": max_size // (1024 * 1024),
        "allowed_types": settings.IMGBED_ALLOWED_TYPES
    }


@router.get("/stats")
async def get_upload_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取当前用户今日上传统计
    """
    daily_limit, _ = _get_imagebed_limits(db)
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    
    # 今日上传数量（优先 Redis 计数器，降级 DB COUNT）
    r = get_redis()
    redis_count_key = f"imgbed:daily:{current_user.id}:{today.strftime('%Y-%m-%d')}"
    today_count = None
    
    if r:
        try:
            cached_count = await r.get(redis_count_key)
            if cached_count is not None:
                today_count = int(cached_count)
        except Exception:
            pass
    
    if today_count is None:
        # Redis 不可用或未初始化，回落 DB 查询
        today_count = db.query(func.count(ImageUpload.id)).filter(
            ImageUpload.user_id == current_user.id,
            ImageUpload.upload_date >= today
        ).scalar() or 0
        # 回写 Redis（设置当天剩余秒数为 TTL）
        if r:
            try:
                tomorrow = today + timedelta(days=1)
                ttl = int((tomorrow - datetime.now()).total_seconds())
                await r.setex(redis_count_key, max(ttl, 1), str(today_count))
            except Exception:
                pass
    
    # 总上传数量
    total_count = db.query(func.count(ImageUpload.id)).filter(
        ImageUpload.user_id == current_user.id
    ).scalar() or 0
    
    return {
        "today_uploads": today_count,
        "daily_limit": daily_limit,
        "remaining": max(0, daily_limit - today_count),
        "total_uploads": total_count
    }


@router.get("/history")
def get_upload_history(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取上传历史记录
    """
    if page_size > 50:
        page_size = 50
    
    offset = (page - 1) * page_size
    
    # 查询总数
    total = db.query(func.count(ImageUpload.id)).filter(
        ImageUpload.user_id == current_user.id
    ).scalar() or 0
    
    # 查询记录
    records = db.query(ImageUpload).filter(
        ImageUpload.user_id == current_user.id
    ).order_by(ImageUpload.created_at.desc()).offset(offset).limit(page_size).all()
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r.id,
                "original_filename": r.original_filename,
                "image_url": r.image_url,
                "file_size": r.file_size,
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in records
        ]
    }


@router.post("/upload")
@limiter.limit("10/minute")
async def upload_to_imagebed(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    上传图片到图床
    
    - 支持格式: JPEG, PNG, GIF, WebP, BMP
    - 最大大小: 10MB
    - 每人每天限制: 可配置
    """
    # 检查图床是否配置
    if not settings.IMGBED_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="图床服务未配置"
        )
    
    # 检查文件类型
    if file.content_type not in settings.IMGBED_ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {file.content_type}，支持: JPEG, PNG, GIF, WebP, BMP"
        )
    
    # 获取限额配置
    daily_limit, max_size = _get_imagebed_limits(db)
    
    # 流式读取文件内容（分块，避免一次性全部读入内存）
    chunks = []
    file_size = 0
    while chunk := await file.read(64 * 1024):  # 64KB chunks
        file_size += len(chunk)
        if file_size > max_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"文件过大，最大支持 {max_size // (1024 * 1024)}MB"
            )
        chunks.append(chunk)
    content = b"".join(chunks)
    
    # 检查今日上传限额（优先 Redis 计数器）
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    r = get_redis()
    redis_count_key = f"imgbed:daily:{current_user.id}:{today.strftime('%Y-%m-%d')}"
    today_count = None
    
    if r:
        try:
            cached_count = await r.get(redis_count_key)
            if cached_count is not None:
                today_count = int(cached_count)
        except Exception:
            pass
    
    if today_count is None:
        today_count = db.query(func.count(ImageUpload.id)).filter(
            ImageUpload.user_id == current_user.id,
            ImageUpload.upload_date >= today
        ).scalar() or 0
    
    if today_count >= daily_limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"今日上传次数已达上限 ({daily_limit} 次)，请明天再试"
        )
    
    # 调用图床 API 上传
    try:
        from ..moderation import get_http_client
        client = get_http_client(timeout_override=60.0)
        if True:
            # 准备上传请求
            upload_url = f"{settings.IMGBED_API_URL.rstrip('/')}/upload"
            headers = {
                "Authorization": f"Bearer {settings.IMGBED_API_TOKEN}"
            }
            files = {
                "file": (file.filename, content, file.content_type)
            }
            params = {
                "returnFormat": "full"  # 返回完整链接
            }
            
            response = await client.post(
                upload_url,
                headers=headers,
                files=files,
                params=params
            )
            
            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"图床上传失败: {response.text}"
                )
            
            result = response.json()
            
            # 解析返回的图片地址
            # API 返回格式: [{"src": "/file/xxx.jpg"}] 或完整 URL
            if isinstance(result, list) and len(result) > 0:
                src = result[0].get("src", "")
                # 如果是相对路径，拼接完整 URL
                if src.startswith("/"):
                    image_url = f"{settings.IMGBED_API_URL.rstrip('/')}{src}"
                else:
                    image_url = src
            else:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="图床返回格式异常"
                )
            
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"图床请求失败: {str(e)}"
        )
    
    # 保存上传记录
    upload_record = ImageUpload(
        user_id=current_user.id,
        original_filename=file.filename,
        image_url=image_url,
        file_size=file_size,
        upload_date=datetime.now()
    )
    db.add(upload_record)
    db.commit()
    db.refresh(upload_record)
    
    # 上传成功后 Redis 计数器 +1
    if r:
        try:
            tomorrow = today + timedelta(days=1)
            ttl = int((tomorrow - datetime.now()).total_seconds())
            await r.incr(redis_count_key)
            await r.expire(redis_count_key, max(ttl, 1))  # 确保 TTL 存在
        except Exception:
            pass
    
    return {
        "success": True,
        "image_url": image_url,
        "markdown": f"![{file.filename}]({image_url})",
        "original_filename": file.filename,
        "file_size": file_size,
        "remaining_today": daily_limit - today_count - 1
    }


@router.delete("/{image_id}")
async def delete_image(
    image_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    删除上传记录和图床上的文件
    """
    # 查找记录
    record = db.query(ImageUpload).filter(
        ImageUpload.id == image_id,
        ImageUpload.user_id == current_user.id
    ).first()
    
    if not record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="记录不存在或无权删除"
        )
    
    # 尝试从图床删除文件
    imgbed_deleted = False
    if record.image_url and settings.IMGBED_API_TOKEN:
        try:
            # 从 URL 提取文件路径
            # URL 格式: https://image.astrdark.cyou/file/xxx.jpg
            # 需要提取: file/xxx.jpg
            url = record.image_url
            base_url = settings.IMGBED_API_URL.rstrip('/')
            if url.startswith(base_url):
                file_path = url[len(base_url):].lstrip('/')
            else:
                # 尝试从 URL 中提取 /file/ 之后的部分
                if '/file/' in url:
                    file_path = 'file/' + url.split('/file/')[-1]
                else:
                    file_path = url.split('/')[-1]
            
            # 调用图床删除 API
            from ..moderation import get_http_client
            client = get_http_client()
            if True:
                delete_url = f"{base_url}/api/manage/delete/{file_path}"
                headers = {
                    "Authorization": f"Bearer {settings.IMGBED_API_TOKEN}"
                }
                response = await client.get(delete_url, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    imgbed_deleted = result.get("success", False)
        except Exception as e:
            # 图床删除失败不影响本地记录删除
            logger.warning(f"图床删除失败: {e}")
    
    # 删除本地记录
    db.delete(record)
    db.commit()
    
    return {
        "success": True, 
        "message": "删除成功",
        "imgbed_deleted": imgbed_deleted
    }
