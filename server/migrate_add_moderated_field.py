"""
迁移脚本：为 threads 和 replies 表添加 moderated 字段

用于支持"先发后审"的审核机制：
- moderated = True: 已审核（或不需要审核）
- moderated = False: 尚未审核（等待定时任务批量审核）

同时修改 notifications.thread_id 为可空（审核删帖后通知无关联帖子）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from app.database import engine
from sqlalchemy import text

def migrate():
    with engine.connect() as conn:
        # 检查数据库类型
        dialect = engine.dialect.name

        # 为 threads 表添加 moderated 字段
        try:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE threads ADD COLUMN moderated BOOLEAN DEFAULT TRUE"))
            else:
                conn.execute(text("ALTER TABLE threads ADD COLUMN moderated BOOLEAN NOT NULL DEFAULT TRUE"))
            print("✅ threads 表已添加 moderated 字段")
        except Exception as e:
            if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                print("ℹ️ threads.moderated 字段已存在，跳过")
            else:
                print(f"⚠️ threads 表添加 moderated 字段失败: {e}")

        # 为 replies 表添加 moderated 字段
        try:
            if dialect == "sqlite":
                conn.execute(text("ALTER TABLE replies ADD COLUMN moderated BOOLEAN DEFAULT TRUE"))
            else:
                conn.execute(text("ALTER TABLE replies ADD COLUMN moderated BOOLEAN NOT NULL DEFAULT TRUE"))
            print("✅ replies 表已添加 moderated 字段")
        except Exception as e:
            if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                print("ℹ️ replies.moderated 字段已存在，跳过")
            else:
                print(f"⚠️ replies 表添加 moderated 字段失败: {e}")

        # 修改 notifications.thread_id 为可空（PostgreSQL）
        if dialect == "postgresql":
            try:
                conn.execute(text("ALTER TABLE notifications ALTER COLUMN thread_id DROP NOT NULL"))
                print("✅ notifications.thread_id 已改为可空")
            except Exception as e:
                print(f"⚠️ 修改 notifications.thread_id 失败: {e}")
        elif dialect == "sqlite":
            print("ℹ️ SQLite 不支持 ALTER COLUMN，notifications.thread_id 保持不变（SQLite 默认允许 NULL）")

        conn.commit()
    print("\n✅ 迁移完成")

if __name__ == "__main__":
    migrate()
