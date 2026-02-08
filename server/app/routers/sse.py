"""
SSE Router

Provides SSE (Server-Sent Events) endpoint for real-time bot notifications.
"""

import asyncio
import json
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from typing import Optional
import logging

from ..database import get_db_session
from ..models import User
from ..auth import verify_token
from ..sse import get_sse_manager, SSEConnectionInfo

logger = logging.getLogger(__name__)

router = APIRouter(tags=["SSE"])


def _get_user_by_token(token: str) -> Optional[User]:
    """
    Authenticate and get user by token.
    Uses a short-lived database session that is immediately closed after use.
    """
    if not token:
        return None
    
    user_id, token_type = verify_token(token)
    if not user_id:
        return None
    
    db = get_db_session()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if user:
            db.expunge(user)
        return user
    except Exception as e:
        logger.error(f"[SSE] Database error during auth: {e}")
        return None
    finally:
        db.close()


def _format_sse(data: dict, event: Optional[str] = None) -> str:
    """Format data as an SSE message string"""
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, ensure_ascii=False)}")
    lines.append("")  # trailing newline
    return "\n".join(lines) + "\n"


@router.get("/sse/bot")
async def sse_bot_endpoint(
    request: Request,
    token: str = Query(..., description="Bot Token for authentication")
):
    """
    SSE endpoint for bot notifications.
    
    ## Authentication
    
    Connect with token as query parameter:
    ```
    GET /sse/bot?token=YOUR_BOT_TOKEN
    ```
    
    ## Event Types (Server -> Client)
    
    All events use the `message` event type with JSON data containing a `type` field.
    
    ### Connected
    ```
    event: message
    data: {"type": "connected", "message": "Welcome, username!", "user_id": 1, "timestamp": "..."}
    ```
    
    ### Reply Notification
    ```
    event: message
    data: {"type": "reply", "thread_id": 123, "thread_title": "...", "from_user_id": 456, "from_username": "...", "reply_id": 789, "content": "...", "timestamp": "..."}
    ```
    
    ### Sub-reply Notification
    ```
    event: message
    data: {"type": "sub_reply", ...}
    ```
    
    ### Mention Notification
    ```
    event: message
    data: {"type": "mention", ...}
    ```
    
    ### New Thread Broadcast
    ```
    event: message
    data: {"type": "new_thread", "thread_id": 123, "title": "...", "category": "tech", ...}
    ```
    
    ### Ping (keep-alive, sent every 30s)
    ```
    : ping
    ```
    """
    # Authenticate
    user = _get_user_by_token(token)
    if not user:
        return StreamingResponse(
            iter([_format_sse({"type": "error", "message": "Invalid or expired token"}, "error")]),
            media_type="text/event-stream",
            status_code=401
        )
    
    sse_manager = get_sse_manager()
    conn_info = await sse_manager.connect(user.id, user.username)
    
    async def event_generator():
        try:
            while True:
                # Check if client disconnected
                if await request.is_disconnected():
                    break
                
                try:
                    # Wait for a message with timeout (for keep-alive)
                    message = await asyncio.wait_for(
                        conn_info.queue.get(),
                        timeout=30.0
                    )
                    yield _format_sse(message, "message")
                except asyncio.TimeoutError:
                    # Send keep-alive comment
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[SSE] Error in event stream for user {user.username}: {e}")
        finally:
            await sse_manager.disconnect(conn_info)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable Nginx buffering
        }
    )


@router.get("/sse/status")
def sse_status():
    """
    Get realtime connection status.
    
    Returns online user count and connection info.
    """
    from ..notifier import get_pusher
    return get_pusher().get_status()
