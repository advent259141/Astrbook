"""
添加 moderation_logs 表的 raw_content 列

运行方法:
    python migrate_add_raw_content.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import create_engine, text
from app.config import get_settings

settings = get_settings()

def migrate():
    engine = create_engine(settings.DATABASE_URL)
    
    with engine.connect() as conn:
        # 检查列是否已存在
        result = conn.execute(text("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = 'moderation_logs' AND column_name = 'raw_content'
        """))
        
        if result.fetchone() is None:
            print("正在添加 raw_content 列...")
            conn.execute(text("ALTER TABLE moderation_logs ADD COLUMN raw_content TEXT"))
            conn.commit()
            print("✅ raw_content 列已添加")
        else:
            print("✅ raw_content 列已存在，无需迁移")

if __name__ == "__main__":
    migrate()
