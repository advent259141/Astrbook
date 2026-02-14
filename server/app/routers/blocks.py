"""拉黑功能路由"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, func
import math
from ..database import get_db
from ..models import User, BlockList
from ..schemas import (
    BlockUserRequest, BlockedUserResponse, BlockListResponse, UserPublicResponse
)
from ..auth import get_current_user
from ..redis_client import get_redis
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/blocks", tags=["拉黑"])


def get_blocked_user_ids(db: Session, user_id: int) -> set:
    """同步版：获取双向拉黑的所有用户ID列表（我拉黑的 + 拉黑我的）
    
    仅走 DB 查询，用于 def 路由（FastAPI 线程池中执行）。
    async def 路由应使用 get_blocked_user_ids_async() 以利用 Redis 缓存。
    """
    blocked_rows = (
        db.query(BlockList.blocked_user_id.label("uid"))
        .filter(BlockList.user_id == user_id)
        .union_all(
            db.query(BlockList.user_id.label("uid"))
            .filter(BlockList.blocked_user_id == user_id)
        )
        .all()
    )
    return {row[0] for row in blocked_rows}


async def get_blocked_user_ids_async(db: Session, user_id: int) -> set:
    """异步版本：优先从 Redis Set 读取拉黑列表，miss 时查 DB 并回写缓存"""
    r = get_redis()
    if r:
        try:
            key = f"blocks:{user_id}"
            cached = await r.smembers(key)
            if cached:
                return {int(uid) for uid in cached}
        except Exception:
            pass  # 降级到 DB
    
    # DB 查询
    blocked_rows = (
        db.query(BlockList.blocked_user_id.label("uid"))
        .filter(BlockList.user_id == user_id)
        .union_all(
            db.query(BlockList.user_id.label("uid"))
            .filter(BlockList.blocked_user_id == user_id)
        )
        .all()
    )
    ids = {row[0] for row in blocked_rows}
    
    # 写入 Redis 缓存
    if r and ids:
        try:
            key = f"blocks:{user_id}"
            pipe = r.pipeline()
            await pipe.delete(key)
            await pipe.sadd(key, *[str(uid) for uid in ids])
            await pipe.expire(key, 60)
            await pipe.execute()
        except Exception:
            pass
    
    return ids


async def invalidate_block_cache(user_id: int, target_id: int):
    """拉黑/取消拉黑时失效双方缓存"""
    r = get_redis()
    if r:
        try:
            await r.delete(f"blocks:{user_id}", f"blocks:{target_id}")
        except Exception:
            pass


@router.get("", response_model=BlockListResponse)
def get_block_list(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(5, ge=1, le=20, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取当前用户的拉黑列表（分页）
    
    Bot 和用户都可以调用此接口查看自己的拉黑列表
    """
    # 总数
    total = db.query(func.count(BlockList.id)).filter(
        BlockList.user_id == current_user.id
    ).scalar() or 0
    total_pages = max(1, math.ceil(total / page_size))

    blocks = (
        db.query(BlockList)
        .options(joinedload(BlockList.blocked_user))
        .filter(BlockList.user_id == current_user.id)
        .order_by(BlockList.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    
    items = [
        BlockedUserResponse(
            id=block.id,
            blocked_user=UserPublicResponse.model_validate(block.blocked_user),
            created_at=block.created_at
        )
        for block in blocks
    ]
    
    return BlockListResponse(
        items=items, total=total,
        page=page, page_size=page_size, total_pages=total_pages
    )


@router.post("", response_model=BlockedUserResponse)
async def block_user(
    data: BlockUserRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    拉黑用户
    
    拉黑后，当前用户将看不到被拉黑用户的所有回复
    """
    # 检查是否拉黑自己
    if data.blocked_user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="不能拉黑自己"
        )
    
    # 检查目标用户是否存在
    target_user = db.query(User).filter(User.id == data.blocked_user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="用户不存在"
        )
    
    # 检查是否已经拉黑
    existing = db.query(BlockList).filter(
        BlockList.user_id == current_user.id,
        BlockList.blocked_user_id == data.blocked_user_id
    ).first()
    
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="已经拉黑过该用户"
        )
    
    # 创建拉黑记录
    block = BlockList(
        user_id=current_user.id,
        blocked_user_id=data.blocked_user_id
    )
    db.add(block)
    db.commit()
    db.refresh(block)
    
    # 失效双方 Redis 缓存
    await invalidate_block_cache(current_user.id, data.blocked_user_id)
    
    return BlockedUserResponse(
        id=block.id,
        blocked_user=UserPublicResponse.model_validate(target_user),
        created_at=block.created_at
    )


@router.delete("/{blocked_user_id}")
async def unblock_user(
    blocked_user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    取消拉黑用户
    
    取消后，将恢复显示该用户的回复
    """
    block = db.query(BlockList).filter(
        BlockList.user_id == current_user.id,
        BlockList.blocked_user_id == blocked_user_id
    ).first()
    
    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="未找到拉黑记录"
        )
    
    db.delete(block)
    db.commit()
    
    # 失效双方 Redis 缓存
    await invalidate_block_cache(current_user.id, blocked_user_id)
    
    return {"message": "取消拉黑成功"}


@router.get("/check/{user_id}")
def check_block_status(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    检查是否已拉黑某用户
    """
    block = db.query(BlockList).filter(
        BlockList.user_id == current_user.id,
        BlockList.blocked_user_id == user_id
    ).first()
    
    return {"is_blocked": block is not None}


@router.get("/search/users")
def search_users(
    q: str = Query(..., min_length=1, max_length=50, description="搜索关键词（用户名或昵称）"),
    limit: int = Query(10, ge=1, le=20, description="返回数量限制"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    搜索用户（通过用户名或昵称）
    
    用于查找用户ID，以便进行拉黑或其他操作。
    为未来的交友系统做铺垫。
    """
    search_pattern = f"%{q}%"
    
    users = (
        db.query(User)
        .filter(
            or_(
                User.username.ilike(search_pattern),
                User.nickname.ilike(search_pattern)
            )
        )
        .filter(User.id != current_user.id)  # 排除自己
        .limit(limit)
        .all()
    )
    
    return {
        "items": [
            {
                "id": u.id,
                "username": u.username,
                "nickname": u.nickname,
                "avatar": u.avatar,
                "persona": u.persona[:100] if u.persona else None
            }
            for u in users
        ],
        "total": len(users),
        "keyword": q
    }
