from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import os
import uuid
import shutil
from pathlib import Path

from ..database import get_db
from ..models import User
from ..schemas import UserResponse
from ..auth import get_current_user
from ..config import get_settings
from ..rate_limit import limiter

router = APIRouter(prefix="/upload", tags=["上传"])
settings = get_settings()

# 确保上传目录存在
UPLOAD_PATH = Path(settings.UPLOAD_DIR)
AVATAR_PATH = UPLOAD_PATH / "avatars"
AVATAR_PATH.mkdir(parents=True, exist_ok=True)


@router.post("/avatar", response_model=UserResponse)
@limiter.limit("5/minute")  # P3 #24: 头像上传限流
async def upload_avatar(
    request: Request,  # limiter 需要 request 参数
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    上传用户头像
    
    - 支持格式: JPEG, PNG, GIF, WebP
    - 最大大小: 2MB
    """
    # 检查文件类型
    if file.content_type not in settings.ALLOWED_AVATAR_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件类型: {file.content_type}，支持: JPEG, PNG, GIF, WebP"
        )
    
    # 生成唯一文件名
    ext = file.filename.split(".")[-1] if "." in file.filename else "jpg"
    filename = f"{current_user.id}_{uuid.uuid4().hex[:8]}.{ext}"
    filepath = AVATAR_PATH / filename
    
    # 流式写入 + 大小校验（避免整个文件读入内存）
    total_size = 0
    try:
        with open(filepath, "wb") as f:
            while chunk := await file.read(64 * 1024):  # 64KB chunks
                total_size += len(chunk)
                if total_size > settings.AVATAR_MAX_SIZE:
                    f.close()
                    filepath.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"文件过大，最大支持 {settings.AVATAR_MAX_SIZE // 1024 // 1024}MB"
                    )
                f.write(chunk)
    except HTTPException:
        raise
    except Exception:
        filepath.unlink(missing_ok=True)
        raise
    
    # 删除旧头像文件
    if current_user.avatar and current_user.avatar.startswith("/api/upload/avatars/"):
        old_filename = current_user.avatar.split("/")[-1]
        old_filepath = AVATAR_PATH / old_filename
        if old_filepath.exists():
            old_filepath.unlink()
    
    # 更新用户头像 URL
    avatar_url = f"/api/upload/avatars/{filename}"
    current_user.avatar = avatar_url
    db.commit()
    db.refresh(current_user)
    
    return UserResponse.model_validate(current_user)


@router.get("/avatars/{filename}")
def get_avatar(filename: str):
    """
    获取头像文件
    """
    # P3 #25: 防止路径穿越攻击
    import re
    if not re.match(r'^[a-zA-Z0-9_.-]+$', filename):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法文件名"
        )
    
    filepath = AVATAR_PATH / filename
    
    # 确保解析后路径仍在 AVATAR_PATH 内
    if not filepath.resolve().is_relative_to(AVATAR_PATH.resolve()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="非法文件路径"
        )
    
    if not filepath.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="头像不存在"
        )
    
    return FileResponse(
        filepath,
        headers={
            "Cache-Control": "public, max-age=86400",  # 缓存1天
        }
    )
