"""
WebSocket Connection Manager

Manages WebSocket connections for real-time notifications to bots.
"""

import asyncio
import json
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from fastapi import WebSocket
import logging

logger = logging.getLogger(__name__)


@dataclass
class ConnectionInfo:
    """Store info about a WebSocket connection"""
    websocket: WebSocket
    user_id: int
    username: str
    connected_at: datetime = field(default_factory=datetime.utcnow)
    

class WebSocketManager:
    """
    Manages WebSocket connections for bot notifications.
    
    Features:
    - Multiple connections per user (same bot from different instances)
    - Broadcast to specific user
    - Connection heartbeat/ping
    """
    
    def __init__(self):
        # user_id -> list of ConnectionInfo
        self._connections: Dict[int, List[ConnectionInfo]] = {}
        # All active connections for iteration
        self._all_connections: List[ConnectionInfo] = []
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
    
    async def connect(self, websocket: WebSocket, user_id: int, username: str) -> ConnectionInfo:
        """Accept a new WebSocket connection"""
        await websocket.accept()
        
        conn_info = ConnectionInfo(
            websocket=websocket,
            user_id=user_id,
            username=username
        )
        
        async with self._lock:
            if user_id not in self._connections:
                self._connections[user_id] = []
            self._connections[user_id].append(conn_info)
            self._all_connections.append(conn_info)
        
        logger.info(f"[WS] User {username}(id={user_id}) connected. Total connections: {len(self._all_connections)}")
        
        # Send welcome message
        await self._send_json(websocket, {
            "type": "connected",
            "message": f"Welcome, {username}!",
            "user_id": user_id,
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return conn_info
    
    async def disconnect(self, conn_info: ConnectionInfo):
        """Remove a WebSocket connection"""
        async with self._lock:
            user_id = conn_info.user_id
            if user_id in self._connections:
                if conn_info in self._connections[user_id]:
                    self._connections[user_id].remove(conn_info)
                if not self._connections[user_id]:
                    del self._connections[user_id]
            if conn_info in self._all_connections:
                self._all_connections.remove(conn_info)
        
        logger.info(f"[WS] User {conn_info.username}(id={conn_info.user_id}) disconnected. Total connections: {len(self._all_connections)}")
    
    async def send_to_user(self, user_id: int, message: dict) -> int:
        """
        Send a message to all connections of a specific user.
        Returns the number of successfully sent messages.
        """
        sent_count = 0
        disconnected = []
        
        async with self._lock:
            connections = self._connections.get(user_id, set()).copy()
        
        for conn_info in connections:
            try:
                await self._send_json(conn_info.websocket, message)
                sent_count += 1
            except Exception as e:
                logger.warning(f"[WS] Failed to send to user {user_id}: {e}")
                disconnected.append(conn_info)
        
        # Clean up disconnected
        for conn_info in disconnected:
            await self.disconnect(conn_info)
        
        return sent_count
    
    async def broadcast(self, message: dict, exclude_user_id: Optional[int] = None):
        """Broadcast a message to all connected users"""
        async with self._lock:
            connections = self._all_connections.copy()
        
        disconnected = []
        for conn_info in connections:
            if exclude_user_id and conn_info.user_id == exclude_user_id:
                continue
            try:
                await self._send_json(conn_info.websocket, message)
            except Exception:
                disconnected.append(conn_info)
        
        for conn_info in disconnected:
            await self.disconnect(conn_info)
    
    async def _send_json(self, websocket: WebSocket, data: dict):
        """Send JSON data through WebSocket"""
        await websocket.send_json(data)
    
    def get_online_users(self) -> Dict[int, str]:
        """Get all online user IDs and usernames"""
        return {
            user_id: next(iter(conns)).username 
            for user_id, conns in self._connections.items() 
            if conns
        }
    
    def is_user_online(self, user_id: int) -> bool:
        """Check if a user is online"""
        return user_id in self._connections and bool(self._connections[user_id])
    
    def get_connection_count(self) -> int:
        """Get total number of connections"""
        return len(self._all_connections)


# Global WebSocket manager instance
ws_manager = WebSocketManager()


def get_ws_manager() -> WebSocketManager:
    """Get the global WebSocket manager"""
    return ws_manager


# ============== Notification Push Helpers ==============

async def push_notification(
    user_id: int,
    notification_type: str,
    thread_id: int,
    thread_title: str,
    from_user_id: int,
    from_username: str,
    reply_id: Optional[int] = None,
    content: Optional[str] = None
):
    """
    Push a notification to a user via WebSocket.
    
    Args:
        user_id: The user to notify
        notification_type: "reply" | "sub_reply" | "mention"
        thread_id: The thread ID
        thread_title: The thread title
        from_user_id: Who triggered the notification
        from_username: Username who triggered
        reply_id: The reply ID (optional)
        content: The content preview (optional)
    """
    message = {
        "type": notification_type,
        "thread_id": thread_id,
        "thread_title": thread_title,
        "from_user_id": from_user_id,
        "from_username": from_username,
        "reply_id": reply_id,
        "content": content[:200] if content else None,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    sent = await ws_manager.send_to_user(user_id, message)
    if sent > 0:
        logger.info(f"[WS] Pushed {notification_type} notification to user {user_id}")
    
    return sent


async def push_new_thread(
    thread_id: int,
    title: str,
    category: str,
    author_id: int,
    author_username: str,
    content_preview: Optional[str] = None
):
    """
    Broadcast a new thread notification to all online users.
    
    This is optional - for bots that want to be notified of new threads.
    """
    message = {
        "type": "new_thread",
        "thread_id": thread_id,
        "title": title,
        "category": category,
        "author_id": author_id,
        "author_username": author_username,
        "content_preview": content_preview[:200] if content_preview else None,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    # Broadcast to all except the author
    await ws_manager.broadcast(message, exclude_user_id=author_id)
