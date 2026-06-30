# backend/api/routes/realtime.py

"""WebSocket and SSE routes for realtime workflow updates."""

from fastapi import APIRouter, Query, WebSocket

from backend.api.responses import success
from backend.realtime.event_bus import EventBusService
from backend.realtime.websocket import WebSocketManager

router = APIRouter()


@router.websocket_route("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket 端点 - 实时事件推送

    客户端连接后可执行以下操作：
    - subscribe:订阅特定工作流 {\"action\": \"subscribe\", \"thread_id\": \"xxx\"}
    - unsubscribe:取消订阅 {\"action\": \"unsubscribe\", \"thread_id\": \"xxx\"}
    - ping:心跳检测 {\"action\": \"ping\"}
    - get_missed:补传丢失事件 {\"action\": \"get_missed\", \"since\": 123}

    服务端推送事件格式：
    {
        "event_type": "workflow_progress",
        "thread_id": "xxx",
        "phase": "creating",
        "agent": "copywriter",
        "timestamp": "2026-05-27T..."
    }
    """
    await WebSocketManager.get_instance().handle_connection(websocket)


@router.get("/events/missed")
async def get_missed_events(since: int = Query(0, ge=0, description="最后收到的事件序号")):
    """HTTP 接口 - 获取丢失的事件

    当 WebSocket 连接中断后，可通过此接口补传丢失的事件。

    Args:
        since: 最后收到的事件序号 (seq)

    Returns:
        {"events": [...]} 事件列表，按序号排序
    """
    events = EventBusService.get_instance().get_events_since(since)
    return success(
        data={
            "events": [e.to_dict() for e in events],
            "count": len(events),
        }
    )
