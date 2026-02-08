"""
SSE (Server-Sent Events) Connection Manager

Manages SSE connections for real-time notifications to bots.
Works alongside WebSocket as an alternative transport.
"""

import asyncio
import json
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
import logging

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
    - Send to specific user
    - Broadcast to all users
    """
    
    def __init__(self):
        # user_id -> list of SSEConnectionInfo
        self._connections: Dict[int, List[SSEConnectionInfo]] = {}
        # All active connections for iteration
        self._all_connections: List[SSEConnectionInfo] = []
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
    
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
            if conn_info in self._all_connections:
                self._all_connections.remove(conn_info)
        
        logger.info(f"[SSE] User {conn_info.username}(id={conn_info.user_id}) disconnected. Total connections: {len(self._all_connections)}")
    
    async def send_to_user(self, user_id: int, message: dict) -> int:
        """
        Send a message to all SSE connections of a specific user.
        Returns the number of successfully sent messages.
        """
        sent_count = 0
        
        async with self._lock:
            connections = list(self._connections.get(user_id, []))
        
        for conn_info in connections:
            try:
                if conn_info.queue.full():
                    # Drop oldest message to make room
                    try:
                        conn_info.queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                await conn_info.queue.put(message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[SSE] Failed to queue message for user {user_id}: {e}")
        
        return sent_count
    
    async def broadcast(self, message: dict, exclude_user_id: Optional[int] = None):
        """Broadcast a message to all connected users"""
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
    
    def get_online_users(self) -> Dict[int, str]:
        """Get all online user IDs and usernames"""
        return {
            user_id: conns[0].username
            for user_id, conns in self._connections.items()
            if conns
        }
    
    def is_user_online(self, user_id: int) -> bool:
        """Check if a user is online"""
        return user_id in self._connections and bool(self._connections[user_id])
    
    def get_connection_count(self) -> int:
        """Get total number of connections"""
        return len(self._all_connections)


# Global SSE manager instance
sse_manager = SSEManager()


def get_sse_manager() -> SSEManager:
    """Get the global SSE manager"""
    return sse_manager
