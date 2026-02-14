"""
迁移脚本：添加关注(Follow)表

Usage:
    python -m server.migrate_add_follow
    # 或
    cd server && python migrate_add_follow.py
"""
import sys
import os

# 添加 server 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, Base
from app.models import Follow

def migrate():
    """创建 follows 表"""
    print("正在创建 follows 表...")
    
    # 只创建新表（不影响已有表）
    Follow.__table__.create(bind=engine, checkfirst=True)
    
    print("✅ follows 表创建成功！")
    print("  - follower_id: 关注者用户ID")
    print("  - following_id: 被关注者用户ID")
    print("  - created_at: 关注时间")
    print("  - 联合唯一索引: (follower_id, following_id)")

if __name__ == "__main__":
    migrate()
