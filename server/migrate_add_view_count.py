"""
数据库迁移脚本：添加帖子浏览量字段

此脚本执行以下操作：
1. 为 threads 表添加 view_count 列（如果不存在）
2. 将所有现有帖子的浏览量初始化为 0

使用方法：
    cd server
    python migrate_add_view_count.py
"""

import sys
import os

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import text, inspect
from app.database import engine, SessionLocal


def check_column_exists(engine, table_name, column_name):
    """检查列是否存在"""
    inspector = inspect(engine)
    columns = [col['name'] for col in inspector.get_columns(table_name)]
    return column_name in columns


def migrate():
    """执行迁移"""
    print("=" * 50)
    print("开始执行数据库迁移：添加帖子浏览量字段")
    print("=" * 50)
    
    db = SessionLocal()
    
    try:
        # 检查 view_count 列是否已存在
        if check_column_exists(engine, 'threads', 'view_count'):
            print("\n[INFO] view_count 列已存在，跳过添加列步骤")
        else:
            print("\n[STEP 1] 添加 view_count 列...")
            with engine.connect() as conn:
                conn.execute(text(
                    "ALTER TABLE threads ADD COLUMN view_count INTEGER DEFAULT 0"
                ))
                conn.commit()
            print("[OK] view_count 列添加成功")
        
        # 将所有现有帖子的浏览量初始化为 0
        print("\n[STEP 2] 初始化现有帖子浏览量...")
        with engine.connect() as conn:
            result = conn.execute(text(
                "UPDATE threads SET view_count = 0 WHERE view_count IS NULL"
            ))
            conn.commit()
            updated_count = result.rowcount
        print(f"[OK] 已更新 {updated_count} 个帖子")
        
        print("\n" + "=" * 50)
        print("迁移完成！")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n[ERROR] 迁移失败: {e}")
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
