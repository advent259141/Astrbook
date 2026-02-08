"""
Notification Pusher

Unified notification push layer that dispatches to all registered transports
(SSE, etc.) without coupling them together.
"""

import asyncio
from typing import Dict, Optional, List, Protocol
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class Transport(Protocol):
    """Interface that any realtime transport must implement."""

    async def send_to_user(self, user_id: int, message: dict) -> int: ...
    async def broadcast(self, message: dict, exclude_user_id: Optional[int] = None) -> None: ...
    def get_online_users(self) -> Dict[int, str]: ...
    def get_connection_count(self) -> int: ...


class NotificationPusher:
    """
    Manages multiple transports and provides unified push + status APIs.
    
    Transports (SSE, etc.) register themselves here.
    Business code only talks to this class, never to individual transports.
    """

    def __init__(self):
        self._transports: Dict[str, Transport] = {}

    def register(self, name: str, transport: Transport):
        """Register a transport (e.g. 'ws', 'sse')."""
        self._transports[name] = transport
        logger.info(f"[Notifier] Registered transport: {name}")

    def unregister(self, name: str):
        """Unregister a transport."""
        self._transports.pop(name, None)

    # ==================== Push ====================

    async def send_to_user(self, user_id: int, message: dict) -> int:
        """Send a message to a user via all transports. Returns total sent count."""
        total = 0
        for name, transport in self._transports.items():
            try:
                sent = await transport.send_to_user(user_id, message)
                if sent > 0:
                    logger.info(f"[{name.upper()}] Pushed to user {user_id} ({sent} connections)")
                total += sent
            except Exception as e:
                logger.warning(f"[{name.upper()}] Failed to push to user {user_id}: {e}")
        return total

    async def broadcast(self, message: dict, exclude_user_id: Optional[int] = None):
        """Broadcast a message via all transports."""
        for name, transport in self._transports.items():
            try:
                await transport.broadcast(message, exclude_user_id=exclude_user_id)
            except Exception as e:
                logger.warning(f"[{name.upper()}] Failed to broadcast: {e}")

    # ==================== Status ====================

    def get_status(self) -> dict:
        """Get combined status across all transports."""
        all_online: Dict[int, str] = {}
        transport_details = {}
        total_connections = 0

        for name, transport in self._transports.items():
            count = transport.get_connection_count()
            online = transport.get_online_users()
            transport_details[f"{name}_connections"] = count
            total_connections += count
            all_online.update(online)

        return {
            "status": "running",
            "total_connections": total_connections,
            **transport_details,
            "online_users": len(all_online),
            "users": [
                {"user_id": uid, "username": uname}
                for uid, uname in all_online.items()
            ],
        }


# ==================== Helpers ====================

async def push_notification(
    user_id: int,
    notification_type: str,
    thread_id: int,
    thread_title: str,
    from_user_id: int,
    from_username: str,
    reply_id: Optional[int] = None,
    content: Optional[str] = None,
) -> int:
    """
    Push a notification to a user via all registered transports.

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
        "content": content,
        "timestamp": datetime.utcnow().isoformat(),
    }
    return await pusher.send_to_user(user_id, message)


# Global instance
pusher = NotificationPusher()


def get_pusher() -> NotificationPusher:
    """Get the global notification pusher."""
    return pusher
