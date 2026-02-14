"""
迁移脚本：添加私聊(DM)系统表

创建三个表：
1. dm_conversations - 私聊会话
2. dm_messages - 私聊消息
3. dm_reads - 用户已读游标

Usage:
    python -m server.migrate_add_dm
    # 或
    cd server && python migrate_add_dm.py
"""
import sys
import os

# 添加 server 目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.database import engine, Base
from app.models import DMConversation, DMMessage, DMRead

def migrate():
    """创建私聊相关表"""
    print("正在创建私聊系统表...")
    
    # 按依赖顺序创建表
    tables_to_create = [
        (DMConversation, "dm_conversations", "私聊会话"),
        (DMMessage, "dm_messages", "私聊消息"),
        (DMRead, "dm_reads", "用户已读游标"),
    ]
    
    for model, table_name, description in tables_to_create:
        try:
            model.__table__.create(bind=engine, checkfirst=True)
            print(f"✅ {table_name} 表创建成功！ ({description})")
        except Exception as e:
            print(f"❌ {table_name} 创建失败: {e}")
            raise
    
    print("\n私聊系统表结构：")
    print("  1. dm_conversations (私聊会话)")
    print("     - user_low_id / user_high_id: 标准化的用户对")
    print("     - message_count: 消息计数")
    print("     - last_message_*: 最后消息信息")
    print("     - 唯一索引: (user_low_id, user_high_id)")
    print("  2. dm_messages (私聊消息)")
    print("     - conversation_id: 所属会话")
    print("     - sender_id: 发送者")
    print("     - content: 消息内容")
    print("     - client_msg_id: 客户端去重ID (可选)")
    print("  3. dm_reads (已读游标)")
    print("     - conversation_id + user_id: 复合主键")
    print("     - last_read_message_id: 已读位置")

if __name__ == "__main__":
    migrate()
