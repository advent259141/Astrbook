"""
内容审核模块 - 使用 OpenAI 兼容接口进行内容安全审核

支持"先发后审"机制：
- 帖子/评论发布时直接通过，标记为 moderated=False
- 后台定时任务批量审核所有 moderated=False 的内容
- 审核不通过时自动删除内容并发送通知
"""
import httpx
import json
import logging
import time as _time
import asyncio
from typing import Optional
from dataclasses import dataclass
from sqlalchemy.orm import Session
from sqlalchemy import func
from .models import SystemSettings, ModerationLog, Thread, Reply, Notification
from .redis_client import get_redis

logger = logging.getLogger(__name__)

# 全局 httpx 客户端 - 复用 TCP 连接
_http_client: Optional[httpx.AsyncClient] = None


def _get_http_client() -> httpx.AsyncClient:
    """获取全局 httpx 客户端（连接复用）"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


def get_http_client(timeout_override: Optional[float] = None) -> httpx.AsyncClient:
    """公共接口：获取全局 httpx 客户端（P2 #17: 各路由复用，消除重复 TCP 握手）
    
    如需不同超时，传 timeout_override 创建独立客户端（仍会被全局引用复用）。
    默认使用 30s 超时的全局客户端。
    """
    if timeout_override and timeout_override != 30.0:
        # 特殊超时需求（如图床上传 60s）使用独立客户端
        return httpx.AsyncClient(timeout=timeout_override)
    return _get_http_client()

# 默认审核 Prompt
DEFAULT_MODERATION_PROMPT = """你是内容安全审核员。请逐条判断以下内容是否存在严重违规。

审核原则：宽松审核，仅拦截直白露骨的违规内容。
- 允许：正常讨论、玩笑调侃、轻微擦边、二次元内容、情感表达
- 允许：历史讨论、时事评论、观点表达（非极端）
- 允许：虚构创作、角色扮演、艺术表达

仅在以下情况拒绝：
1. 色情内容（sexual）：直白露骨的性行为描写、真人色情内容
2. 暴力内容（violence）：具体详细的伤害教程、真实暴力威胁
3. 极端内容（extreme）：煽动仇恨、恐怖主义、严重违法信息

如有疑虑，倾向于通过。

请以 JSON 数组格式回复，数组中每个元素对应一条内容（按 id 对应），不要包含其他内容：
[{"id": 1, "passed": true, "category": "none", "reason": ""},...]

待审核内容：
{content}"""


@dataclass
class ModerationResult:
    """审核结果"""
    passed: bool
    category: str = "none"  # none / sexual / violence / political
    reason: str = ""
    error: Optional[str] = None


class ContentModerator:
    """内容审核器"""
    
    def __init__(self, db: Session):
        self.db = db
        self._load_settings()
    
    def _load_settings(self):
        """从数据库批量加载配置（1次查询代替5次）"""
        keys = [
            "moderation_enabled", "moderation_api_base",
            "moderation_api_key", "moderation_model", "moderation_prompt"
        ]
        settings = self.db.query(SystemSettings).filter(
            SystemSettings.key.in_(keys)
        ).all()
        settings_map = {s.key: s.value for s in settings if s.value}
        
        self.enabled = settings_map.get("moderation_enabled", "false") == "true"
        self.api_base = settings_map.get("moderation_api_base", "https://api.openai.com/v1")
        self.api_key = settings_map.get("moderation_api_key", "")
        self.model = settings_map.get("moderation_model", "gpt-4o-mini")
        self.prompt = settings_map.get("moderation_prompt", DEFAULT_MODERATION_PROMPT)
    
    async def check(
        self,
        content: str,
        content_type: str,
        user_id: int,
        content_id: Optional[int] = None
    ) -> ModerationResult:
        """
        审核内容
        
        Args:
            content: 待审核内容
            content_type: 内容类型 (thread / reply / sub_reply)
            user_id: 发布者 ID
            content_id: 内容 ID（可选，审核通过后会有）
        
        Returns:
            ModerationResult: 审核结果
        """
        # 如果未启用审核，直接通过
        if not self.enabled:
            return ModerationResult(passed=True)
        
        # 检查配置是否完整
        if not self.api_key or not self.api_base or not self.model:
            logger.warning("审核配置不完整，跳过审核")
            return ModerationResult(passed=True)
        
        try:
            batch_items = [{"id": 1, "content": content[:500]}]
            results = await self._call_llm_batch(batch_items)
            result = results[0]
            
            # 记录审核日志
            self._log_moderation(
                content_type=content_type,
                content_id=content_id,
                user_id=user_id,
                content_preview=content[:500] if content else "",
                passed=result.passed,
                flagged_category=result.category if not result.passed else None,
                reason=result.reason if not result.passed else None,
                model_used=self.model
            )
            
            return result
            
        except Exception as e:
            logger.error(f"审核请求失败: {e}")
            # 审核失败时默认通过（可配置）
            return ModerationResult(passed=True, error=str(e))
    
    async def _call_llm_batch(self, items: list[dict]) -> list[ModerationResult]:
        """统一审核接口：将多条内容合并为一次 LLM 请求
        
        帖子和评论都使用此方法，通过管理员自定义 Prompt 审核。
        Prompt 中的 {content} 占位符会被替换为带编号的内容列表。
        
        Args:
            items: [{"id": <编号>, "content": <内容>}, ...]
        
        Returns:
            与 items 等长的 ModerationResult 列表
        """
        # 构建带编号的内容列表，替换 Prompt 中的 {content}
        numbered_list = "\n".join(
            f"[{item['id']}] {item['content']}" for item in items
        )
        full_prompt = self.prompt.replace("{content}", numbered_list)
        
        url = f"{self.api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": full_prompt}
            ],
            "temperature": 0,
            "max_tokens": 150 * len(items)  # 按条目数动态分配
        }
        
        client = _get_http_client()
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        reply_text = data["choices"][0]["message"]["content"].strip()
        return self._parse_batch_result(reply_text, len(items))

    @staticmethod
    def _parse_batch_result(reply_text: str, expected_count: int) -> list[ModerationResult]:
        """解析批量审核 JSON 数组响应
        
        容错策略：解析失败时全部默认通过
        """
        try:
            cleaned = reply_text
            if cleaned.startswith("```"):
                cleaned = cleaned.split("```")[1]
                if cleaned.startswith("json"):
                    cleaned = cleaned[4:]
                cleaned = cleaned.strip()
            
            results_raw = json.loads(cleaned)
            
            if not isinstance(results_raw, list):
                logger.warning(f"批量审核响应不是数组: {reply_text[:200]}")
                return [ModerationResult(passed=True)] * expected_count
            
            # 按 id 字段建立映射（id 从 1 开始）
            result_map = {}
            for item in results_raw:
                if isinstance(item, dict):
                    idx = item.get("id")
                    if idx is not None:
                        result_map[int(idx)] = ModerationResult(
                            passed=item.get("passed", True),
                            category=item.get("category", "none"),
                            reason=item.get("reason", "")
                        )
            
            # 按顺序组装结果，缺失的默认通过
            results = []
            for i in range(1, expected_count + 1):
                results.append(result_map.get(i, ModerationResult(passed=True)))
            return results
        
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning(f"无法解析批量审核响应: {e} | {reply_text[:200]}")
            return [ModerationResult(passed=True)] * expected_count
    
    def _log_moderation(
        self,
        content_type: str,
        content_id: Optional[int],
        user_id: int,
        content_preview: str,
        passed: bool,
        flagged_category: Optional[str],
        reason: Optional[str],
        model_used: str
    ):
        """记录审核日志"""
        log = ModerationLog(
            content_type=content_type,
            content_id=content_id,
            user_id=user_id,
            content_preview=content_preview,
            passed=passed,
            flagged_category=flagged_category,
            reason=reason,
            model_used=model_used
        )
        self.db.add(log)
        # 注意：不在这里 commit，由调用方统一处理


async def fetch_available_models(api_base: str, api_key: str) -> list[str]:
    """从 API 获取可用模型列表（使用全局客户端）"""
    url = f"{api_base.rstrip('/')}/models"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    client = _get_http_client()
    response = await client.get(url, headers=headers)
    response.raise_for_status()
    data = response.json()
    
    # 提取模型 ID 列表
    models = []
    for model in data.get("data", []):
        model_id = model.get("id", "")
        if model_id:
            models.append(model_id)
    
    # 按名称排序
    models.sort()
    return models


# ===== 审核器配置缓存（60秒TTL） =====
# P2 #13: 只缓存配置字典，不缓存 ContentModerator 实例（避免 Session 交叉污染）
_moderator_config_cache: Optional[dict] = None
_moderator_config_cache_time: float = 0
_MODERATOR_CACHE_TTL = 60  # 秒


def get_moderator(db: Session) -> ContentModerator:
    """获取审核器实例
    
    P2 #13: 只缓存配置字典（线程安全），每次请求创建新的 ContentModerator 实例。
    避免全局缓存实例导致并发请求的 Session 交叉污染。
    """
    global _moderator_config_cache, _moderator_config_cache_time
    now = _time.time()
    
    if _moderator_config_cache is None or (now - _moderator_config_cache_time) > _MODERATOR_CACHE_TTL:
        # 从 DB 加载配置并缓存为字典
        moderator = ContentModerator(db)
        _moderator_config_cache = {
            "enabled": moderator.enabled,
            "api_base": moderator.api_base,
            "api_key": moderator.api_key,
            "model": moderator.model,
            "prompt": moderator.prompt,
        }
        _moderator_config_cache_time = now
        return moderator
    
    # 用缓存的配置创建新实例（不触发 DB 查询）
    moderator = ContentModerator.__new__(ContentModerator)
    moderator.db = db
    moderator.enabled = _moderator_config_cache["enabled"]
    moderator.api_base = _moderator_config_cache["api_base"]
    moderator.api_key = _moderator_config_cache["api_key"]
    moderator.model = _moderator_config_cache["model"]
    moderator.prompt = _moderator_config_cache["prompt"]
    return moderator


async def invalidate_moderation_cache():
    """失效审核配置缓存（管理员修改配置时调用）
    
    同时清除进程级内存缓存和 Redis 缓存，
    确保所有实例在下次请求时重新加载配置。
    """
    global _moderator_config_cache, _moderator_config_cache_time
    _moderator_config_cache = None
    _moderator_config_cache_time = 0
    
    r = get_redis()
    if r:
        try:
            await r.delete("settings:moderation")
        except Exception:
            pass


# ===== 定时批量审核 =====

def get_moderation_interval(db: Session) -> int:
    """获取审核间隔（秒），默认60秒"""
    setting = db.query(SystemSettings).filter(
        SystemSettings.key == "moderation_interval"
    ).first()
    if setting and setting.value:
        try:
            return max(10, int(setting.value))  # 最小10秒
        except (ValueError, TypeError):
            pass
    return 60


def get_moderation_batch_size(db: Session) -> int:
    """获取每次审核的评论数，默认5条"""
    setting = db.query(SystemSettings).filter(
        SystemSettings.key == "moderation_batch_size"
    ).first()
    if setting and setting.value:
        try:
            return max(1, min(50, int(setting.value)))
        except (ValueError, TypeError):
            pass
    return 5


async def _batch_moderate_content():
    """
    批量审核所有 moderated=False 的帖子和评论。
    
    审核不通过时：
    1. 删除帖子/评论及相关数据
    2. 给作者发送审核不通过的通知
    """
    from .database import SessionLocal
    
    db = SessionLocal()
    try:
        moderator = ContentModerator(db)
        
        if not moderator.enabled:
            # 审核未开启，把所有未审核的标记为已审核
            db.query(Thread).filter(Thread.moderated == False).update(
                {Thread.moderated: True}, synchronize_session=False
            )
            db.query(Reply).filter(Reply.moderated == False).update(
                {Reply.moderated: True}, synchronize_session=False
            )
            db.commit()
            return
        
        if not moderator.api_key or not moderator.api_base or not moderator.model:
            # 配置不完整，标记为已审核
            db.query(Thread).filter(Thread.moderated == False).update(
                {Thread.moderated: True}, synchronize_session=False
            )
            db.query(Reply).filter(Reply.moderated == False).update(
                {Reply.moderated: True}, synchronize_session=False
            )
            db.commit()
            return
        
        # === 审核未审核的帖子 ===
        unmoderated_threads = db.query(Thread).filter(
            Thread.moderated == False
        ).all()
        
        for thread in unmoderated_threads:
            try:
                content_to_check = f"{thread.title}\n{thread.content}"
                batch_items = [{"id": 1, "content": content_to_check[:500]}]
                results = await moderator._call_llm_batch(batch_items)
                result = results[0]
                
                # 记录审核日志
                moderator._log_moderation(
                    content_type="thread",
                    content_id=thread.id,
                    user_id=thread.author_id,
                    content_preview=content_to_check[:500],
                    passed=result.passed,
                    flagged_category=result.category if not result.passed else None,
                    reason=result.reason if not result.passed else None,
                    model_used=moderator.model
                )
                
                if result.passed:
                    thread.moderated = True
                else:
                    # 审核不通过：删帖 + 发通知
                    logger.info(f"[BatchMod] 帖子 #{thread.id} 审核不通过: {result.reason}")
                    _delete_thread_and_notify(
                        db, thread, result.reason or "包含违规内容"
                    )
                
            except Exception as e:
                logger.error(f"[BatchMod] 审核帖子 #{thread.id} 失败: {e}")
                # 审核失败时默认通过
                thread.moderated = True
        
        # === 审核未审核的评论（批量打包，每 BATCH_SIZE 条一个请求） ===
        BATCH_SIZE = get_moderation_batch_size(db)
        unmoderated_replies = db.query(Reply).filter(
            Reply.moderated == False
        ).all()
        
        for batch_start in range(0, len(unmoderated_replies), BATCH_SIZE):
            batch_replies = unmoderated_replies[batch_start:batch_start + BATCH_SIZE]
            
            try:
                # 构建批量审核请求
                batch_items = [
                    {
                        "id": idx + 1,
                        "content": (rpl.content or "")[:500]
                    }
                    for idx, rpl in enumerate(batch_replies)
                ]
                
                batch_results = await moderator._call_llm_batch(batch_items)
                
                # 逐条处理结果
                for rpl, result in zip(batch_replies, batch_results):
                    content_type = "sub_reply" if rpl.parent_id else "reply"
                    
                    # 记录审核日志
                    moderator._log_moderation(
                        content_type=content_type,
                        content_id=rpl.id,
                        user_id=rpl.author_id,
                        content_preview=rpl.content[:500] if rpl.content else "",
                        passed=result.passed,
                        flagged_category=result.category if not result.passed else None,
                        reason=result.reason if not result.passed else None,
                        model_used=moderator.model
                    )
                    
                    if result.passed:
                        rpl.moderated = True
                    else:
                        logger.info(f"[BatchMod] 评论 #{rpl.id} 审核不通过: {result.reason}")
                        _delete_reply_and_notify(
                            db, rpl, result.reason or "包含违规内容"
                        )
            
            except Exception as e:
                logger.error(f"[BatchMod] 批量审核评论失败: {e}")
                # 整批审核失败时全部默认通过
                for rpl in batch_replies:
                    rpl.moderated = True
        
        db.commit()
        
        total = len(unmoderated_threads) + len(unmoderated_replies)
        if total > 0:
            logger.info(f"[BatchMod] 本轮审核完成: {len(unmoderated_threads)} 帖子, {len(unmoderated_replies)} 评论")
    
    except Exception as e:
        db.rollback()
        logger.error(f"[BatchMod] 批量审核异常: {e}")
    finally:
        db.close()


def _delete_thread_and_notify(db: Session, thread: Thread, reason: str):
    """删除帖子并给作者发审核不通过通知"""
    author_id = thread.author_id
    thread_id = thread.id
    thread_title = thread.title
    
    # 先给作者发通知（此时帖子还存在，FK约束OK）
    notification = Notification(
        user_id=author_id,
        from_user_id=author_id,  # 系统通知，发送者为自己
        type="moderation",
        thread_id=thread_id,
        content_preview=f"您的帖子「{thread_title[:50]}」未通过内容审核，已被删除。原因：{reason}"
    )
    db.add(notification)
    db.flush()  # 先写入通知，获得通知ID
    notification_id = notification.id
    
    # Redis: 未读计数 +1
    r = get_redis()
    if r:
        from .redis_client import fire_and_forget
        fire_and_forget(r.incr(f"unread:{author_id}"))
    
    # 获取所有回复ID
    reply_ids = [
        r.id for r in db.query(Reply.id).filter(Reply.thread_id == thread_id).all()
    ]
    
    # 删除相关通知（外键约束）—— 但保留刚创建的审核通知
    db.query(Notification).filter(
        Notification.thread_id == thread_id,
        Notification.id != notification_id
    ).delete(synchronize_session=False)
    if reply_ids:
        db.query(Notification).filter(Notification.reply_id.in_(reply_ids)).delete(
            synchronize_session=False
        )
    
    # 清除回复中的引用
    if reply_ids:
        db.query(Reply).filter(Reply.reply_to_id.in_(reply_ids)).update(
            {Reply.reply_to_id: None}, synchronize_session=False
        )
        db.query(Reply).filter(Reply.parent_id.in_(reply_ids)).update(
            {Reply.parent_id: None}, synchronize_session=False
        )
    
    # 删除所有回复
    db.query(Reply).filter(Reply.thread_id == thread_id).delete(
        synchronize_session=False
    )
    
    # 把审核通知的 thread_id 置空（帖子即将被删除）
    # 需要 thread_id nullable，或者先解除FK
    # 为了兼容性，我们把通知的 thread_id 保留（帖子删除后FK会报错）
    # 所以先把通知的 thread_id 通过原生SQL设为NULL
    from sqlalchemy import text
    db.execute(
        text("UPDATE notifications SET thread_id = NULL WHERE id = :nid"),
        {"nid": notification_id}
    )
    
    # 删除帖子
    db.delete(thread)


def _delete_reply_and_notify(db: Session, reply: Reply, reason: str):
    """删除评论并给作者发审核不通过通知"""
    author_id = reply.author_id
    reply_id = reply.id
    thread_id = reply.thread_id
    content_preview = reply.content[:50] if reply.content else ""
    is_sub_reply = reply.parent_id is not None
    
    # 先给作者发通知（此时关联数据还存在）
    notification = Notification(
        user_id=author_id,
        from_user_id=author_id,
        type="moderation",
        thread_id=thread_id,
        reply_id=None,  # 不关联即将被删除的评论
        content_preview=f"您的{'楼中楼' if is_sub_reply else '回复'}「{content_preview}」未通过内容审核，已被删除。原因：{reason}"
    )
    db.add(notification)
    db.flush()
    
    # Redis: 未读计数 +1
    r = get_redis()
    if r:
        from .redis_client import fire_and_forget
        fire_and_forget(r.incr(f"unread:{author_id}"))
    
    if not is_sub_reply:
        # 主楼层：删除其下所有楼中楼
        sub_reply_ids = [
            r.id for r in db.query(Reply.id).filter(Reply.parent_id == reply_id).all()
        ]
        
        # 删除相关通知
        all_ids = sub_reply_ids + [reply_id]
        db.query(Notification).filter(Notification.reply_id.in_(all_ids)).delete(
            synchronize_session=False
        )
        
        # 清除引用
        if sub_reply_ids:
            db.query(Reply).filter(Reply.reply_to_id.in_(sub_reply_ids)).update(
                {Reply.reply_to_id: None}, synchronize_session=False
            )
        db.query(Reply).filter(Reply.parent_id == reply_id).update(
            {Reply.reply_to_id: None}, synchronize_session=False
        )
        # 删除楼中楼
        db.query(Reply).filter(Reply.parent_id == reply_id).delete(
            synchronize_session=False
        )
        
        # 更新帖子回复数
        deleted_count = 1 + len(sub_reply_ids)
        db.query(Thread).filter(Thread.id == thread_id).update(
            {Thread.reply_count: func.greatest(
                func.coalesce(Thread.reply_count, 0) - deleted_count, 0
            )},
            synchronize_session=False
        )
    else:
        # 楼中楼：清除对它的引用
        db.query(Reply).filter(Reply.reply_to_id == reply_id).update(
            {Reply.reply_to_id: None}, synchronize_session=False
        )
        # 删除相关通知
        db.query(Notification).filter(Notification.reply_id == reply_id).delete(
            synchronize_session=False
        )
    
    # 删除评论本身
    db.delete(reply)


async def run_batch_moderation_loop():
    """
    定时批量审核后台任务（在 main.py startup 中启动）
    
    每隔 moderation_interval 秒执行一次批量审核。
    """
    from .database import SessionLocal
    
    while True:
        try:
            # 获取当前审核间隔
            db = SessionLocal()
            try:
                interval = get_moderation_interval(db)
            finally:
                db.close()
            
            await asyncio.sleep(interval)
            await _batch_moderate_content()
            
        except asyncio.CancelledError:
            logger.info("[BatchMod] 收到停止信号，执行最后一次审核...")
            try:
                await _batch_moderate_content()
            except Exception:
                pass
            break
        except Exception as e:
            logger.error(f"[BatchMod] 循环异常: {e}")
            await asyncio.sleep(10)
