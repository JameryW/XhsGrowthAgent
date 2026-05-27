# xhs_growth/api/routes/realtime.py

"""WebSocket and event recovery HTTP routes."""

from fastapi import APIRouter, WebSocket

from backend.realtime.websocket import WebSocketManager
from backend.realtime.event_bus import EventBusService


router = APIRouter()


@router.websocket_route("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket端点 - 实时事件推送.

    客户端连接后可：
    - subscribe/unsubscribe工作流
    - ping心跳
    - get_missed补传事件
    """
    await WebSocketManager.get_instance().handle_connection(websocket)


@router.get("/events/missed")
async def get_missed_events(since: int = 0) -> dict:
    """HTTP接口 - 获取丢失的事件.

    Args:
        since: 最后收到的事件seq

    Returns:
        {"events": [...]}事件列表
    """
    events = EventBusService.get_instance().get_events_since(since)
    return {"events": [e.to_dict() for e in events]}