import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from xhs_growth.realtime.websocket import WebSocketManager, WsSession
from xhs_growth.realtime.events import EventType, Event


@pytest.fixture(autouse=True)
def reset_websocket_manager():
    """每个测试重置单例"""
    WebSocketManager._instance = None


def test_ws_session_creation():
    """WsSession正确初始化"""
    mock_ws = MagicMock()
    session = WsSession(mock_ws)

    assert session.websocket == mock_ws
    assert session.subscribed_threads == set()
    assert session.last_seq == 0


def test_ws_session_subscribe():
    """WsSession订阅thread"""
    session = WsSession(MagicMock())

    session.subscribe("thread_123")
    assert "thread_123" in session.subscribed_threads

    session.subscribe("thread_456")
    assert "thread_456" in session.subscribed_threads


def test_ws_session_unsubscribe():
    """WsSession取消订阅"""
    session = WsSession(MagicMock())
    session.subscribe("thread_123")

    session.unsubscribe("thread_123")
    assert "thread_123" not in session.subscribed_threads


@pytest.mark.asyncio
async def test_ws_session_should_receive_event():
    """WsSession过滤：订阅的thread收到事件"""
    session = WsSession(AsyncMock())
    session.subscribe("thread_123")

    # 订阅的事件应接收
    event = Event(EventType.WORKFLOW_STARTED, "thread_123", {}, "2026-05-26T10:00:00Z", 0)
    assert session.should_receive_event(event) is True

    # 未订阅的事件不应接收
    event2 = Event(EventType.WORKFLOW_STARTED, "thread_456", {}, "2026-05-26T10:00:00Z", 1)
    assert session.should_receive_event(event2) is False

    # 全局事件应接收
    event3 = Event(EventType.ANALYTICS_COST_ALERT, None, {}, "2026-05-26T10:00:00Z", 2)
    assert session.should_receive_event(event3) is True


def test_websocket_manager_singleton():
    """WebSocketManager是单例"""
    mgr1 = WebSocketManager.get_instance()
    mgr2 = WebSocketManager.get_instance()
    assert mgr1 is mgr2


@pytest.mark.asyncio
async def test_handle_connection_lifecycle():
    """handle_connection生命周期：subscribe/unsubscribe/ping"""
    from xhs_growth.realtime.event_bus import EventBusService

    # Reset EventBusService singleton
    EventBusService._instance = None
    event_bus = EventBusService.get_instance()

    manager = WebSocketManager.get_instance()
    mock_ws = AsyncMock()

    # Simulate messages: subscribe, ping, unsubscribe
    messages = [
        {"action": "subscribe", "thread_id": "thread_123"},
        {"action": "ping"},
        {"action": "unsubscribe", "thread_id": "thread_123"},
    ]

    # Set up websocket to return messages then raise timeout
    mock_ws.receive_json = AsyncMock()
    mock_ws.receive_json.side_effect = messages + [asyncio.TimeoutError()]
    mock_ws.accept = AsyncMock()
    mock_ws.close = AsyncMock()
    mock_ws.send_json = AsyncMock()

    await manager.handle_connection(mock_ws)

    # Verify websocket was accepted
    mock_ws.accept.assert_called_once()

    # Verify ping response was sent
    sent_messages = [call.args[0] for call in mock_ws.send_json.call_args_list]
    assert {"action": "pong"} in sent_messages

    # Verify close was called with heartbeat timeout code
    mock_ws.close.assert_called_once_with(code=1001, reason="heartbeat timeout")

    # Verify session was cleaned up
    assert len(manager.sessions) == 0

    # Verify unsubscribe was called on event bus
    assert len(event_bus._subscribers) == 0


@pytest.mark.asyncio
async def test_handle_connection_disconnect():
    """handle_connection处理WebSocketDisconnect异常"""
    from xhs_growth.realtime.event_bus import EventBusService
    from fastapi import WebSocketDisconnect

    # Reset EventBusService singleton
    EventBusService._instance = None
    event_bus = EventBusService.get_instance()

    manager = WebSocketManager.get_instance()
    mock_ws = AsyncMock()

    # Simulate WebSocketDisconnect
    mock_ws.receive_json = AsyncMock()
    mock_ws.receive_json.side_effect = WebSocketDisconnect()
    mock_ws.accept = AsyncMock()
    mock_ws.close = AsyncMock()

    await manager.handle_connection(mock_ws)

    # Verify websocket was accepted
    mock_ws.accept.assert_called_once()

    # Verify no close call on normal disconnect (handled by finally block)
    mock_ws.close.assert_not_called()

    # Verify session was cleaned up
    assert len(manager.sessions) == 0

    # Verify unsubscribe was called
    assert len(event_bus._subscribers) == 0


@pytest.mark.asyncio
async def test_handle_client_message_get_missed():
    """_handle_client_message处理get_missed动作"""
    from xhs_growth.realtime.event_bus import EventBusService

    # Reset EventBusService singleton
    EventBusService._instance = None
    event_bus = EventBusService.get_instance()

    # Add some events to event bus
    event1 = Event(EventType.WORKFLOW_STARTED, "thread_123", {"step": 1}, "2026-05-26T10:00:00Z", 1)
    event2 = Event(EventType.WORKFLOW_AGENT_STARTED, "thread_123", {"agent": "copywriter"}, "2026-05-26T10:01:00Z", 2)
    event_bus._events = [event1, event2]

    manager = WebSocketManager.get_instance()
    mock_ws = AsyncMock()
    session = WsSession(mock_ws)

    # Test get_missed with since=0 (get all events)
    msg = {"action": "get_missed", "since": 0}
    await manager._handle_client_message(session, msg)

    # Verify response sent
    mock_ws.send_json.assert_called_once()
    response = mock_ws.send_json.call_args.args[0]
    assert response["action"] == "missed_events"
    assert len(response["events"]) == 2

    # Test get_missed with since=1 (get events after seq 1)
    mock_ws.send_json = AsyncMock()
    msg = {"action": "get_missed", "since": 1}
    await manager._handle_client_message(session, msg)

    response = mock_ws.send_json.call_args.args[0]
    assert response["action"] == "missed_events"
    assert len(response["events"]) == 1
    assert response["events"][0]["seq"] == 2