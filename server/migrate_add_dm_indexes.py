"""
为DM系统添加性能优化索引
运行方式：cd server && python migrate_add_dm_indexes.py
"""
from app.database import engine


def add_dm_indexes():
    """添加DM系统性能优化索引"""
    # CONCURRENTLY 索引不能在事务中创建，需要使用原始连接
    raw_conn = engine.raw_connection()
    
    try:
        # 设置 autocommit 模式
        raw_conn.set_isolation_level(0)
        cursor = raw_conn.cursor()
        
        print("开始添加DM性能优化索引...")
        
        # 1. DMConversation查询优化索引
        print("添加DMConversation索引...")
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dm_conversation_user_low_last_message
            ON dm_conversations (user_low_id, last_message_id DESC NULLS LAST);
        """)
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dm_conversation_user_high_last_message
            ON dm_conversations (user_high_id, last_message_id DESC NULLS LAST);
        """)
        
        # 2. DMMessage查询优化索引 (conversation_id + id倒序用于分页查询)
        print("添加DMMessage索引...")
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dm_message_conv_id_desc
            ON dm_messages (conversation_id, id DESC);
        """)
        
        # 3. DMRead查询优化索引
        print("添加DMRead索引...")
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_dm_read_user_conv
            ON dm_reads (user_id, conversation_id);
        """)
        
        # 4. Follow联合查询优化索引
        print("添加Follow复合索引...")
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_follow_follower_following
            ON follows (follower_id, following_id);
        """)
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_follow_following_follower
            ON follows (following_id, follower_id);
        """)
        
        # 5. BlockList联合查询优化索引
        print("添加BlockList复合索引...")
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blocklist_user_blocked
            ON block_list (user_id, blocked_user_id);
        """)
        cursor.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_blocklist_blocked_user
            ON block_list (blocked_user_id, user_id);
        """)
        
        cursor.close()
        print("✅ DM性能优化索引添加成功！")
        
        # 显示索引信息
        print("\n📊 索引统计：")
        cursor = raw_conn.cursor()
        cursor.execute("""
            SELECT
                t.relname AS table_name,
                i.relname AS index_name,
                pg_size_pretty(pg_relation_size(i.oid)) AS index_size
            FROM pg_class t
            JOIN pg_index ix ON t.oid = ix.indrelid
            JOIN pg_class i ON i.oid = ix.indexrelid
            WHERE t.relname IN ('dm_conversations', 'dm_messages', 'dm_reads', 'follows', 'block_list')
                AND i.relname LIKE 'idx_%'
            ORDER BY t.relname, i.relname;
        """)
        
        for row in cursor.fetchall():
            print(f"  {row[0]}.{row[1]}: {row[2]}")
        
        cursor.close()
        
    except Exception as e:
        print(f"❌ 添加索引失败：{e}")
        raise
    finally:
        raw_conn.close()


if __name__ == "__main__":
    print("=" * 60)
    print("DM系统性能优化索引迁移脚本")
    print("=" * 60)
    add_dm_indexes()
    print("\n✅ 迁移完成！")
