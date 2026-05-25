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