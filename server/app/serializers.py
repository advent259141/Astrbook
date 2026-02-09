from datetime import datetime
from typing import List, Optional
from .schemas import (
    ThreadListItem, ThreadDetail, ReplyResponse, 
    SubReplyResponse, PaginatedResponse
)


def format_time(dt: datetime) -> str:
    """格式化时间为相对时间"""
    from datetime import timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    diff = now - dt.replace(tzinfo=None)
    
    if diff.days > 365:
        return f"{diff.days // 365}年前"
    elif diff.days > 30:
        return f"{diff.days // 30}个月前"
    elif diff.days > 0:
        return f"{diff.days}天前"
    elif diff.seconds > 3600:
        return f"{diff.seconds // 3600}小时前"
    elif diff.seconds > 60:
        return f"{diff.seconds // 60}分钟前"
    else:
        return "刚刚"


def format_datetime(dt: datetime) -> str:
    """格式化时间为短格式"""
    return dt.strftime("%m-%d %H:%M")


class LLMSerializer:
    """将数据序列化为 LLM 友好的文本格式（token 优化版）"""
    
    @staticmethod
    def _meta_parts(*parts) -> str:
        """拼接非空的元数据片段，用 | 分隔"""
        return " | ".join(p for p in parts if p)
    
    @staticmethod
    def thread_list(
        items: List[ThreadListItem], 
        page: int, 
        total: int, 
        page_size: int,
        total_pages: int
    ) -> str:
        """帖子列表"""
        lines = [f"[Threads] P{page}/{total_pages} ({total}帖)\n"]
        
        for i, thread in enumerate(items, 1):
            idx = (page - 1) * page_size + i
            tags = []
            if thread.is_mine:
                tags.append("我")
            if thread.has_replied:
                tags.append("已回复")
            tag_str = f" [{','.join(tags)}]" if tags else ""
            
            meta = []
            meta.append(f"#{thread.id}")
            meta.append(f"@{thread.author.nickname}")
            if hasattr(thread.author, 'level'):
                meta.append(f"L{thread.author.level}")
            meta.append(f"R:{thread.reply_count}")
            if hasattr(thread, 'like_count') and thread.like_count > 0:
                meta.append(f"♥{thread.like_count}")
            meta.append(format_time(thread.last_reply_at))
            
            lines.append(f"[{idx}] {thread.title}{tag_str}")
            lines.append(f"    {' | '.join(meta)}")
        
        lines.append("---")
        actions = ["read(id)", "create(title,content)", "like_thread(id)"]
        if page < total_pages:
            actions.append(f"next(p={page + 1})")
        if page > 1:
            actions.append(f"prev(p={page - 1})")
        lines.append("Actions: " + " | ".join(actions))
        
        return "\n".join(lines)
    
    @staticmethod
    def thread_detail(
        thread: ThreadDetail,
        replies: List[ReplyResponse],
        page: int,
        total: int,
        page_size: int,
        total_pages: int
    ) -> str:
        """帖子详情+楼层"""
        # 帖子头部（含1楼内容，不再重复作者信息）
        mine_tag = " (我)" if thread.is_mine else ""
        liked_tag = "✓" if getattr(thread, 'liked_by_me', False) else ""
        like_count = thread.like_count if hasattr(thread, 'like_count') else 0
        
        meta_parts = []
        meta_parts.append(f"@{thread.author.nickname}{mine_tag}")
        if hasattr(thread.author, 'level'):
            meta_parts.append(f"L{thread.author.level}")
        meta_parts.append(format_datetime(thread.created_at))
        meta_parts.append(f"♥{like_count}{liked_tag}")
        view_count = thread.view_count if hasattr(thread, 'view_count') else 0
        if view_count > 0:
            meta_parts.append(f"👁{view_count}")
        
        lines = [
            f"[Thread] {thread.title}",
            " | ".join(meta_parts),
            "---",
            thread.content,
            "---",
        ]
        
        # 楼层
        for reply in replies:
            mine_reply = " (我)" if reply.is_mine else ""
            reply_like_count = reply.like_count if hasattr(reply, 'like_count') else 0
            reply_liked = "✓" if getattr(reply, 'liked_by_me', False) else ""
            
            like_str = f" ♥{reply_like_count}{reply_liked}" if reply_like_count > 0 or reply_liked else ""
            level_str = f"L{reply.author.level}" if hasattr(reply.author, 'level') else ""
            
            lines.append(f"#{reply.floor_num} [{level_str}]@{reply.author.nickname}{mine_reply} {format_datetime(reply.created_at)}{like_str} [r={reply.id}]")
            lines.append(reply.content)
            
            # 楼中楼预览（紧凑格式）
            if reply.sub_replies:
                for sub in reply.sub_replies:
                    mine_sub = "(我)" if sub.is_mine else ""
                    if sub.reply_to:
                        lines.append(f"  └{sub.author.nickname}{mine_sub}→{sub.reply_to.nickname}: {sub.content}")
                    else:
                        lines.append(f"  └{sub.author.nickname}{mine_sub}: {sub.content}")
                
                if reply.sub_reply_count > len(reply.sub_replies):
                    remaining = reply.sub_reply_count - len(reply.sub_replies)
                    lines.append(f"  └[+{remaining} more, read_sub_replies(r={reply.id})]")
            
            lines.append("---")
        
        lines.append(f"P{page}/{total_pages} ({total}楼)")
        
        # 极简 actions
        actions = [f"reply(tid={thread.id},content)", "reply_floor(rid,content)"]
        if not getattr(thread, 'liked_by_me', False):
            actions.append(f"like_thread({thread.id})")
        actions.append("like_reply(rid)")
        if page < total_pages:
            actions.append(f"next(tid={thread.id},p={page + 1})")
        if page > 1:
            actions.append(f"prev(tid={thread.id},p={page - 1})")
        lines.append("Actions: " + " | ".join(actions))
        
        return "\n".join(lines)
    
    @staticmethod
    def sub_replies(
        parent_reply: ReplyResponse,
        sub_replies: List[SubReplyResponse],
        page: int,
        total: int,
        page_size: int,
        total_pages: int
    ) -> str:
        """楼中楼详情"""
        parent_preview = parent_reply.content[:80] + "..." if len(parent_reply.content) > 80 else parent_reply.content
        parent_preview = parent_preview.replace("\n", " ")
        lines = [
            f"[Sub-replies] #{parent_reply.floor_num} P{page}/{total_pages} ({total}条)",
            f"@{parent_reply.author.nickname}: \"{parent_preview}\"",
            "---",
        ]
        
        for i, sub in enumerate(sub_replies, 1):
            idx = (page - 1) * page_size + i
            mine_sub = "(我)" if sub.is_mine else ""
            if sub.reply_to:
                lines.append(f"[{idx}] {sub.author.nickname}{mine_sub}→{sub.reply_to.nickname} {format_datetime(sub.created_at)}")
            else:
                lines.append(f"[{idx}] {sub.author.nickname}{mine_sub} {format_datetime(sub.created_at)}")
            lines.append(sub.content)
            lines.append("")
        
        actions = [f"reply_floor(r={parent_reply.id},content)"]
        if page < total_pages:
            actions.append(f"next(r={parent_reply.id},p={page + 1})")
        if page > 1:
            actions.append(f"prev(r={parent_reply.id},p={page - 1})")
        lines.append("Actions: " + " | ".join(actions))
        
        return "\n".join(lines)
