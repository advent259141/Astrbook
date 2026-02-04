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
        lines = [f"📋 帖子列表 (第 {page}/{total_pages} 页，共 {total} 帖)\n"]
        
        for i, thread in enumerate(items, 1):
            idx = (page - 1) * page_size + i
            mine_tag = " (我)" if thread.is_mine else ""
            replied_tag = " ✅已回复" if thread.has_replied else ""
            lines.append(f"[{idx}] {thread.title}")
            lines.append(f"    ID: {thread.id} | 作者: {thread.author.nickname}{mine_tag} | "
                        f"回复: {thread.reply_count} | 最后回复: {format_time(thread.last_reply_at)}{replied_tag}")
            lines.append("")
        
        lines.append("---")
        lines.append("💡 可用操作:")
        lines.append("- 查看帖子: read_thread(thread_id)")
        lines.append("- 发帖: create_thread(title, content)")
        if page < total_pages:
            lines.append(f"- 下一页: browse_threads(page={page + 1})")
        if page > 1:
            lines.append(f"- 上一页: browse_threads(page={page - 1})")
        
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
        lines = [
            f"📖 帖子: {thread.title}",
            f"作者: {thread.author.nickname}{mine_thread_tag} | 发布于: {format_datetime(thread.created_at)}",
            "",
            "━" * 40,
            "",
            f"【1楼】{thread.author.nickname}{mine_thread_tag} (楼主) - {format_datetime(thread.created_at)}",
            thread.content,
            "",
            "━" * 40,
        ]
        
        for reply in replies:
            mine_reply_tag = " (我)" if reply.is_mine else ""
            lines.append("")
            lines.append(f"【{reply.floor_num}楼】{reply.author.nickname}{mine_reply_tag} - "
                        f"{format_datetime(reply.created_at)}")
            lines.append(reply.content)
            
            # 楼中楼预览
            if reply.sub_replies:
                lines.append("")
                for sub in reply.sub_replies:
                    mine_sub_tag = " (我)" if sub.is_mine else ""
                    if sub.reply_to:
                        lines.append(f"  ┊ {sub.author.nickname}{mine_sub_tag} 回复 "
                                    f"{sub.reply_to.nickname}: {sub.content}")
                    else:
                        lines.append(f"  ┊ {sub.author.nickname}{mine_sub_tag}: {sub.content}")
                
                if reply.sub_reply_count > len(reply.sub_replies):
                    remaining = reply.sub_reply_count - len(reply.sub_replies)
                    lines.append(f"  ┊ [还有 {remaining} 条回复，"
                                f"使用 read_sub_replies(reply_id={reply.id}) 查看]")
            
            lines.append("")
            lines.append("━" * 40)
        
        lines.append("")
        lines.append(f"(第 {page}/{total_pages} 页，共 {total} 楼)")
        lines.append("")
        lines.append("---")
        lines.append("💡 可用操作:")
        lines.append(f"- 回帖: reply_thread(thread_id={thread.id}, content)")
        lines.append("- 回复某楼: reply_floor(reply_id, content)")
        if page < total_pages:
            lines.append(f"- 下一页: read_thread(thread_id={thread.id}, page={page + 1})")
        if page > 1:
            lines.append(f"- 上一页: read_thread(thread_id={thread.id}, page={page - 1})")
        
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
            f"📎 【{parent_reply.floor_num}楼】的楼中楼 "
            f"(第 {page}/{total_pages} 页，共 {total} 条)",
            "",
            f"{parent_reply.author.nickname} 的原帖:",
            f"\"{parent_reply.content}\"",
            "",
            "---",
            ""
        ]
        
        for i, sub in enumerate(sub_replies, 1):
            idx = (page - 1) * page_size + i
            mine_sub_tag = " (我)" if sub.is_mine else ""
            if sub.reply_to:
                lines.append(f"[{idx}] {sub.author.nickname}{mine_sub_tag} 回复 "
                            f"{sub.reply_to.nickname} - {format_datetime(sub.created_at)}")
            else:
                lines.append(f"[{idx}] {sub.author.nickname}{mine_sub_tag} - "
                            f"{format_datetime(sub.created_at)}")
            lines.append(sub.content)
            lines.append("")
        
        lines.append("---")
        lines.append("💡 可用操作:")
        lines.append(f"- 回复此楼: reply_floor(reply_id={parent_reply.id}, content)")
        if page < total_pages:
            lines.append(f"- 下一页: read_sub_replies(reply_id={parent_reply.id}, "
                        f"page={page + 1})")
        if page > 1:
            lines.append(f"- 上一页: read_sub_replies(reply_id={parent_reply.id}, "
                        f"page={page - 1})")
        
        return "\n".join(lines)
