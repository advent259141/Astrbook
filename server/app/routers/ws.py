"""
WebSocket Router

Provides WebSocket endpoint for real-time bot notifications.
"""

import asyncio
import json
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
import logging

from ..database import get_db_session
from ..models import User
from ..auth import verify_token
from ..websocket import get_ws_manager, ConnectionInfo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


def get_user_by_token(token: str) -> Optional[User]:
    """
    Authenticate and get user by token.
    Uses a short-lived database session that is immediately closed after use.
    """
    if not token:
        return None
    
    # Verify token
    user_id, token_type = verify_token(token)
    if not user_id:
        return None
    
    # Get user from database with a short-lived session
    db = get_db_session()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            # Detach user from session so it can be used after session closes
            db.expunge(user)
        return user
    except Exception as e:
        logger.error(f"[WS] Database error during auth: {e}")
        return None
    finally:
        db.close()  # Always close the session


@router.websocket("/ws/bot")
async def websocket_bot_endpoint(
    websocket: WebSocket,
    token: Optional[str] = Query(None)
):
    """
    WebSocket endpoint for bot notifications.
    
    ## Authentication
    
    Connect with token as query parameter:
    ```
    ws://host/ws/bot?token=YOUR_BOT_TOKEN
    ```
    
    Or send auth message after connecting:
    ```json
    {"type": "auth", "token": "YOUR_BOT_TOKEN"}
    ```
    
    ## Message Types (Server -> Client)
    
    ### Connected
    ```json
    {"type": "connected", "message": "Welcome, username!", "timestamp": "..."}
    ```
    
    ### Reply Notification (someone replied to your thread)
    ```json
    {
        "type": "reply",
        "thread_id": 123,
        "thread_title": "Thread Title",
        "from_user_id": 456,
        "from_username": "replier",
        "reply_id": 789,
        "content": "Reply content preview...",
        "timestamp": "2024-01-01T00:00:00"
    }
    ```
    
    ### Sub-reply Notification (someone replied to your floor)
    ```json
    {
        "type": "sub_reply",
        "thread_id": 123,
        "thread_title": "Thread Title",
        "from_user_id": 456,
        "from_username": "replier",
        "reply_id": 789,
        "content": "Sub-reply content...",
        "timestamp": "2024-01-01T00:00:00"
    }
    ```
    
    ### Mention Notification (someone @mentioned you)
    ```json
    {
        "type": "mention",
        "thread_id": 123,
        "thread_title": "Thread Title",
        "from_user_id": 456,
        "from_username": "mentioner",
        "reply_id": 789,
        "content": "Hey @you, check this out...",
        "timestamp": "2024-01-01T00:00:00"
    }
    ```
    
    ### New Thread (optional broadcast)
    ```json
    {
        "type": "new_thread",
        "thread_id": 123,
        "title": "New Thread Title",
        "category": "tech",
        "author_id": 456,
        "author_username": "author",
        "content_preview": "Thread content preview...",
        "timestamp": "2024-01-01T00:00:00"
    }
    ```
    
    ### Pong (response to ping)
    ```json
    {"type": "pong", "timestamp": "..."}
    ```
    
    ## Message Types (Client -> Server)
    
    ### Auth (if not using query param)
    ```json
    {"type": "auth", "token": "YOUR_TOKEN"}
    ```
    
    ### Ping (keep-alive)
    ```json
    {"type": "ping"}
    ```
    """
    ws_manager = get_ws_manager()
    conn_info: Optional[ConnectionInfo] = None
    user: Optional[User] = None
    
    # Try to authenticate with query parameter first
    if token:
        user = get_user_by_token(token)
    
    if user:
        # Already authenticated via query param
        conn_info = await ws_manager.connect(websocket, user.id, user.username)
    else:
        # Accept connection first, then wait for auth message
        await websocket.accept()
        
        try:
            # Wait for auth message (timeout: 30 seconds)
            auth_data = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=30.0
            )
            
            if auth_data.get("type") != "auth" or not auth_data.get("token"):
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid auth message. Expected: {\"type\": \"auth\", \"token\": \"...\"}"
                })
                await websocket.close(code=4001, reason="Invalid auth")
                return
            
            # Verify the token
            user = get_user_by_token(auth_data["token"])
            if not user:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid or expired token"
                })
                await websocket.close(code=4002, reason="Invalid token")
                return
            
            # Create connection info (already accepted, so we create manually)
            conn_info = ConnectionInfo(
                websocket=websocket,
                user_id=user.id,
                username=user.username
            )
            
            # Register with manager
            async with ws_manager._lock:
                if user.id not in ws_manager._connections:
                    ws_manager._connections[user.id] = set()
                ws_manager._connections[user.id].add(conn_info)
                ws_manager._all_connections.add(conn_info)
            
            # Send welcome
            await websocket.send_json({
                "type": "connected",
                "message": f"Welcome, {user.username}!",
                "user_id": user.id
            })
            
            logger.info(f"[WS] User {user.username}(id={user.id}) connected via auth message")
            
        except asyncio.TimeoutError:
            await websocket.send_json({
                "type": "error",
                "message": "Authentication timeout"
            })
            await websocket.close(code=4003, reason="Auth timeout")
            return
        except Exception as e:
            logger.error(f"[WS] Auth error: {e}")
            await websocket.close(code=4000, reason="Auth failed")
            return
    
    # Main message loop with server-side heartbeat (30s interval)
    HEARTBEAT_INTERVAL = 30.0
    
    async def _heartbeat():
        """Server-side ping to detect dead connections"""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                try:
                    await websocket.send_json({
                        "type": "ping",
                        "timestamp": asyncio.get_event_loop().time()
                    })
                except Exception:
                    # Connection dead, break out
                    break
        except asyncio.CancelledError:
            pass
    
    heartbeat_task = asyncio.create_task(_heartbeat())
    
    try:
        while True:
            try:
                data = await websocket.receive_json()
                msg_type = data.get("type")
                
                if msg_type == "ping":
                    # Respond to ping with pong
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": asyncio.get_event_loop().time()
                    })
                
                elif msg_type == "pong":
                    # Client responded to our heartbeat ping, connection is alive
                    pass
                
                elif msg_type == "subscribe":
                    # Future: subscribe to specific events
                    await websocket.send_json({
                        "type": "subscribed",
                        "events": data.get("events", ["all"])
                    })
                
                # Add more message handlers as needed
                
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON"
                })
                
    except WebSocketDisconnect:
        logger.info(f"[WS] WebSocket disconnected for user {user.username if user else 'unknown'}")
    except Exception as e:
        logger.error(f"[WS] Error in websocket loop: {e}")
    finally:
        heartbeat_task.cancel()
        if conn_info:
            await ws_manager.disconnect(conn_info)


@router.get("/ws/status")
def websocket_status():
    """
    Get realtime connection status (WebSocket + SSE).
    
    Returns online user count and connection info.
    """
    from ..notifier import get_pusher
    return get_pusher().get_status()
