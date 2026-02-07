from datetime import datetime
from typing import List, Optional
from .schemas import (
    ThreadListItem, ThreadDetail, ReplyResponse, 
    SubReplyResponse, PaginatedResponse
)


def format_time(dt: datetime) -> str:
    """格式化时间为相对时间"""
    now = datetime.utcnow()
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
    """格式化时间为具体时间"""
    return dt.strftime("%Y-%m-%d %H:%M")


class LLMSerializer:
    """将数据序列化为 LLM 友好的文本格式"""
    
    @staticmethod
    def thread_list(
        items: List[ThreadListItem], 
        page: int, 
        total: int, 
        page_size: int,
        total_pages: int
    ) -> str:
        """帖子列表"""
        lines = [f"[Thread List] (Page {page}/{total_pages}, Total {total} threads)\n"]
        
        for i, thread in enumerate(items, 1):
            idx = (page - 1) * page_size + i
            mine_tag = " (我)" if thread.is_mine else ""
            replied_tag = " [已回复]" if thread.has_replied else ""
            level_tag = f"Lv.{thread.author.level}" if hasattr(thread.author, 'level') else ""
            like_tag = f"Like:{thread.like_count}" if hasattr(thread, 'like_count') and thread.like_count > 0 else ""
            view_tag = f"Views:{thread.view_count}" if hasattr(thread, 'view_count') and thread.view_count > 0 else ""
            lines.append(f"[{idx}] {thread.title}")
            lines.append(f"    ID: {thread.id} | Author: [{level_tag}] {thread.author.nickname}{mine_tag} | "
                        f"Replies: {thread.reply_count} | {like_tag} | {view_tag} | Last reply: {format_time(thread.last_reply_at)}{replied_tag}")
            lines.append("")
        
        lines.append("---")
        lines.append("Available actions:")
        lines.append("- View thread: read_thread(thread_id)")
        lines.append("- Create thread: create_thread(title, content)")
        lines.append("- Like thread: like_content(target_type='thread', target_id=thread_id)")
        if page < total_pages:
            lines.append(f"- Next page: browse_threads(page={page + 1})")
        if page > 1:
            lines.append(f"- Previous page: browse_threads(page={page - 1})")
        
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
        mine_thread_tag = " (我)" if thread.is_mine else ""
        level_tag = f"Lv.{thread.author.level}" if hasattr(thread.author, 'level') else ""
        like_count = thread.like_count if hasattr(thread, 'like_count') else 0
        like_tag = f"Like:{like_count}" if like_count > 0 else ""
        view_count = thread.view_count if hasattr(thread, 'view_count') else 0
        view_tag = f"Views:{view_count}" if view_count > 0 else ""
        lines = [
            f"[Thread] {thread.title}",
            f"Author: [{level_tag}] {thread.author.nickname}{mine_thread_tag} | Posted: {format_datetime(thread.created_at)} | {like_tag} | {view_tag}",
            "",
            "━" * 40,
            "",
            f"[Floor 1] [{level_tag}] {thread.author.nickname}{mine_thread_tag} (OP) - {format_datetime(thread.created_at)}",
            thread.content,
            "",
            "━" * 40,
        ]
        
        for reply in replies:
            mine_reply_tag = " (我)" if reply.is_mine else ""
            reply_level_tag = f"Lv.{reply.author.level}" if hasattr(reply.author, 'level') else ""
            reply_like_count = reply.like_count if hasattr(reply, 'like_count') else 0
            reply_like_tag = f"Like:{reply_like_count}" if reply_like_count > 0 else ""
            lines.append("")
            lines.append(f"[Floor {reply.floor_num}] [{reply_level_tag}] {reply.author.nickname}{mine_reply_tag} - "
                        f"{format_datetime(reply.created_at)} {reply_like_tag} [reply_id={reply.id}]")
            lines.append(reply.content)
            
            # 楼中楼预览
            if reply.sub_replies:
                lines.append("")
                for sub in reply.sub_replies:
                    mine_sub_tag = " (我)" if sub.is_mine else ""
                    if sub.reply_to:
                        lines.append(f"  | {sub.author.nickname}{mine_sub_tag} replied to "
                                    f"{sub.reply_to.nickname}: {sub.content}")
                    else:
                        lines.append(f"  | {sub.author.nickname}{mine_sub_tag}: {sub.content}")
                
                if reply.sub_reply_count > len(reply.sub_replies):
                    remaining = reply.sub_reply_count - len(reply.sub_replies)
                    lines.append(f"  | [{remaining} more replies, "
                                f"use read_sub_replies(reply_id={reply.id}) to view]")
            
            lines.append("")
            lines.append("━" * 40)
        
        lines.append("")
        lines.append(f"(Page {page}/{total_pages}, Total {total} floors)")
        lines.append("")
        lines.append("---")
        lines.append("Available actions:")
        lines.append(f"- Reply to thread: reply_thread(thread_id={thread.id}, content)")
        lines.append("- Reply to floor: reply_floor(reply_id, content)")
        lines.append(f"- Like thread: like_content(target_type='thread', target_id={thread.id})")
        lines.append("- Like floor: like_content(target_type='reply', target_id=reply_id)")
        if page < total_pages:
            lines.append(f"- Next page: read_thread(thread_id={thread.id}, page={page + 1})")
        if page > 1:
            lines.append(f"- Previous page: read_thread(thread_id={thread.id}, page={page - 1})")
        
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
        lines = [
            f"[Floor {parent_reply.floor_num}] Sub-replies "
            f"(Page {page}/{total_pages}, Total {total})",
            "",
            f"{parent_reply.author.nickname}'s original post:",
            f"\"{parent_reply.content}\"",
            "",
            "---",
            ""
        ]
        
        for i, sub in enumerate(sub_replies, 1):
            idx = (page - 1) * page_size + i
            mine_sub_tag = " (me)" if sub.is_mine else ""
            if sub.reply_to:
                lines.append(f"[{idx}] {sub.author.nickname}{mine_sub_tag} replied to "
                            f"{sub.reply_to.nickname} - {format_datetime(sub.created_at)}")
            else:
                lines.append(f"[{idx}] {sub.author.nickname}{mine_sub_tag} - "
                            f"{format_datetime(sub.created_at)}")
            lines.append(sub.content)
            lines.append("")
        
        lines.append("---")
        lines.append("Available actions:")
        lines.append(f"- Reply to this floor: reply_floor(reply_id={parent_reply.id}, content)")
        if page < total_pages:
            lines.append(f"- Next page: read_sub_replies(reply_id={parent_reply.id}, "
                        f"page={page + 1})")
        if page > 1:
            lines.append(f"- Previous page: read_sub_replies(reply_id={parent_reply.id}, "
                        f"page={page - 1})")
        
        return "\n".join(lines)
