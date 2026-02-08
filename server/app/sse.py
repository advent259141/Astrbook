"""
SSE (Server-Sent Events) Connection Manager

Manages SSE connections for real-time notifications to bots.

Redis Pub/Sub 支持（Phase 1）：
- 跨实例消息通过 Redis Pub/Sub 频道分发
- 在线状态通过 Redis Set `sse:online` 共享
- Redis 不可用时降级回单实例本地推送
"""

import asyncio
import json
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import logging

from .redis_client import get_redis

logger = logging.getLogger(__name__)


@dataclass
class SSEConnectionInfo:
    """Store info about an SSE connection"""
    queue: asyncio.Queue
    user_id: int
    username: str
    connected_at: datetime = field(default_factory=datetime.utcnow)


class SSEManager:
    """
    Manages SSE connections for bot notifications.
    
    Features:
    - Multiple connections per user (same bot from different instances)
    - Send to specific user (local + Redis Pub/Sub)
    - Broadcast to all users (local + Redis Pub/Sub)
    - Online status shared via Redis Set `sse:online`
    """
    
    def __init__(self):
        # user_id -> list of SSEConnectionInfo
        self._connections: Dict[int, List[SSEConnectionInfo]] = {}
        # All active connections for iteration
        self._all_connections: List[SSEConnectionInfo] = []
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
        # Pub/Sub subscriber task
        self._subscriber_task: Optional[asyncio.Task] = None
    
    async def connect(self, user_id: int, username: str) -> SSEConnectionInfo:
        """Register a new SSE connection"""
        conn_info = SSEConnectionInfo(
            queue=asyncio.Queue(maxsize=100),
            user_id=user_id,
            username=username
        )
        
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(conn_info)
            self._all_connections.append(conn_info)
        
        logger.info(f"[SSE] User {username}(id={user_id}) connected. Total connections: {len(self._all_connections)}")
        
        # Redis: 标记用户在线
        r = get_redis()
        if r:
            try:
                await r.sadd("sse:online", str(user_id))
            except Exception:
                pass
        
        # Push welcome event
        await conn_info.queue.put({
            "type": "connected",
            "message": f"Welcome, {username}!",
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return conn_info
    
    async def disconnect(self, conn_info: SSEConnectionInfo):
        """Remove an SSE connection"""
        async with self._lock:
            user_id = conn_info.user_id
            if user_id in self._connections:
                if conn_info in self._connections[user_id]:
                    self._connections[user_id].remove(conn_info)
                if not self._connections[user_id]:
                    del self._connections[user_id]
                    # Redis: 该用户无本地连接了，标记离线
                    r = get_redis()
                    if r:
                        try:
                            await r.srem("sse:online", str(user_id))
                        except Exception:
                            pass
            if conn_info in self._all_connections:
                self._all_connections.remove(conn_info)
        
        logger.info(f"[SSE] User {conn_info.username}(id={conn_info.user_id}) disconnected. Total connections: {len(self._all_connections)}")
    
    async def _send_to_local_user(self, user_id: int, message: dict) -> int:
        """Send a message to local SSE connections only (no Redis publish)."""
        sent_count = 0
        
        async with self._lock:
            connections = list(self._connections.get(user_id, []))
        
        for conn_info in connections:
            try:
                if conn_info.queue.full():
                    try:
                        conn_info.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await conn_info.queue.put(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[SSE] Failed to queue message for user {user_id}: {e}")
        
        return sent_count
    
    async def _broadcast_local(self, message: dict, exclude_user_id: Optional[int] = None):
        """Broadcast a message to all local connections only (no Redis publish)."""
        async with self._lock:
            connections = list(self._all_connections)
        
        for conn_info in connections:
            if exclude_user_id and conn_info.user_id == exclude_user_id:
                continue
            try:
                if conn_info.queue.full():
                    try:
                        conn_info.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await conn_info.queue.put(message)
            except Exception:
                pass
    
    async def send_to_user(self, user_id: int, message: dict) -> int:
        """
        Send a message to all SSE connections of a specific user.
        
        如果 Redis 可用，通过 Pub/Sub 发布到 `sse:user:{user_id}` 频道，
        让所有实例都能收到并转发给本地连接。
        如果 Redis 不可用，仅发送到本地连接。
        
        Returns the number of locally sent messages.
        """
        r = get_redis()
        if r:
            try:
                payload = json.dumps({
                    "_target": "user",
                    "_user_id": user_id,
                    **message
                }, ensure_ascii=False)
                await r.publish(f"sse:user:{user_id}", payload)
                # Pub/Sub 会触发所有实例（包括自己）的本地分发
                # 所以这里不再直接调用 _send_to_local_user
                return 0  # 实际发送在 subscriber 中计数
            except Exception as e:
                logger.warning(f"[SSE] Redis publish failed, falling back to local: {e}")
        
        # 降级：仅本地发送
        return await self._send_to_local_user(user_id, message)
    
    async def broadcast(self, message: dict, exclude_user_id: Optional[int] = None):
        """Broadcast a message to all connected users via Redis Pub/Sub."""
        r = get_redis()
        if r:
            try:
                payload = json.dumps({
                    "_target": "broadcast",
                    "_exclude_user_id": exclude_user_id,
                    **message
                }, ensure_ascii=False)
                await r.publish("sse:broadcast", payload)
                return
            except Exception as e:
                logger.warning(f"[SSE] Redis broadcast publish failed, falling back to local: {e}")
        
        # 降级：仅本地广播
        await self._broadcast_local(message, exclude_user_id)
    
    def get_online_users(self) -> Dict[int, str]:
        """Get all online user IDs and usernames (local view)
        
        注意：多实例环境下，这只返回本实例的在线用户。
        如需全局视图，使用 get_online_users_global()。
        """
        return {
            user_id: conns[0].username
            for user_id, conns in self._connections.items()
            if conns
        }
    
    async def get_online_users_global(self) -> set:
        """获取全局在线用户 ID 集合（从 Redis Set 读取）"""
        r = get_redis()
        if r:
            try:
                members = await r.smembers("sse:online")
                return {int(uid) for uid in members}
            except Exception:
                pass
        # 降级：返回本地视图
        return set(self._connections.keys())
    
    def is_user_online(self, user_id: int) -> bool:
        """Check if a user is online (local view)"""
        return user_id in self._connections and bool(self._connections[user_id])
    
    async def is_user_online_global(self, user_id: int) -> bool:
        """检查用户是否全局在线（Redis Set）"""
        r = get_redis()
        if r:
            try:
                return await r.sismember("sse:online", str(user_id))
            except Exception:
                pass
        return self.is_user_online(user_id)
    
    def get_connection_count(self) -> int:
        """Get total number of local connections"""
        return len(self._all_connections)
    
    # ==================== Redis Pub/Sub Subscriber ====================
    
    async def start_subscriber(self):
        """启动 Redis Pub/Sub 订阅任务（app startup 时调用）
        
        订阅两类频道：
        - `sse:user:*`  — 定向推送
        - `sse:broadcast` — 全局广播
        """
        r = get_redis()
        if not r:
            logger.info("[SSE] Redis 不可用，Pub/Sub 订阅器未启动")
            return
        
        self._subscriber_task = asyncio.create_task(self._subscriber_loop())
        logger.info("[SSE] Redis Pub/Sub 订阅器已启动")
    
    async def stop_subscriber(self):
        """停止 Pub/Sub 订阅任务（app shutdown 时调用）"""
        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                pass
            self._subscriber_task = None
            logger.info("[SSE] Redis Pub/Sub 订阅器已停止")
    
    async def _subscriber_loop(self):
        """后台 Pub/Sub 订阅循环"""
        while True:
            r = get_redis()
            if not r:
                await asyncio.sleep(5)
                continue
            
            try:
                pubsub = r.pubsub()
                await pubsub.psubscribe("sse:user:*", "sse:broadcast")
                logger.info("[SSE] Pub/Sub 已订阅 sse:user:* 和 sse:broadcast")
                
                async for raw_msg in pubsub.listen():
                    if raw_msg["type"] not in ("pmessage",):
                        continue
                    
                    try:
                        data = json.loads(raw_msg["data"])
                        target = data.pop("_target", None)
                        
                        if target == "user":
                            user_id = data.pop("_user_id", None)
                            if user_id is not None:
                                await self._send_to_local_user(int(user_id), data)
                        elif target == "broadcast":
                            exclude = data.pop("_exclude_user_id", None)
                            await self._broadcast_local(data, exclude_user_id=exclude)
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning(f"[SSE] Failed to process Pub/Sub message: {e}")
                        
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(f"[SSE] Pub/Sub connection lost, reconnecting in 3s: {e}")
                await asyncio.sleep(3)


# Global SSE manager instance
sse_manager = SSEManager()


def get_sse_manager() -> SSEManager:
    """Get the global SSE manager"""
    return sse_manager
