"""
数据库迁移脚本：添加拉黑列表表

使用方法:
    python migrate_add_block_list.py

说明:
    该脚本会在数据库中创建 block_list 表，用于存储用户拉黑关系。
"""

import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import Column, Integer, ForeignKey, DateTime, Index, text
from sqlalchemy.sql import func
from app.database import engine, Base


def migrate():
    """执行迁移"""
    with engine.connect() as conn:
        # 检查表是否已存在
        result = conn.execute(text("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = 'block_list'
            )
        """))
        exists = result.scalar()
        
        if exists:
            print("表 block_list 已存在，跳过创建")
            return
        
        # 创建 block_list 表
        conn.execute(text("""
            CREATE TABLE block_list (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id),
                blocked_user_id INTEGER NOT NULL REFERENCES users(id),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            )
        """))
        
        # 创建索引
        conn.execute(text("""
            CREATE UNIQUE INDEX ix_block_list_user_blocked 
            ON block_list (user_id, blocked_user_id)
        """))
        
        conn.execute(text("""
            CREATE INDEX ix_block_list_id ON block_list (id)
        """))
        
        conn.commit()
        print("✓ 成功创建 block_list 表")


def migrate_sqlite():
    """SQLite 迁移（用于本地开发）"""
    with engine.connect() as conn:
        # 检查表是否已存在
        result = conn.execute(text("""
            SELECT name FROM sqlite_master 
            WHERE type='table' AND name='block_list'
        """))
        exists = result.fetchone()
        
        if exists:
            print("表 block_list 已存在，跳过创建")
            return
        
        # 创建 block_list 表
        conn.execute(text("""
            CREATE TABLE block_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                blocked_user_id INTEGER NOT NULL REFERENCES users(id),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        
        # 创建索引
        conn.execute(text("""
            CREATE UNIQUE INDEX ix_block_list_user_blocked 
            ON block_list (user_id, blocked_user_id)
        """))
        
        conn.commit()
        print("✓ 成功创建 block_list 表 (SQLite)")


if __name__ == "__main__":
    from app.config import get_settings
    settings = get_settings()
    
    # 根据数据库类型选择迁移方式
    if "sqlite" in settings.DATABASE_URL:
        migrate_sqlite()
    else:
        migrate()
