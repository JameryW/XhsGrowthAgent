"""Tests for SSE EventBus-driven streaming."""

import asyncio
import pytest
from backend.realtime.event_bus import EventBusService
from backend.realtime.events import EventType


@pytest.mark.asyncio
async def test_subscribe_thread_returns_queue():
    """EventBus should support per-thread subscription with asyncio.Queue."""
    bus = EventBusService.get_instance()

    queue = bus.subscribe_thread("test-thread-123")
    assert queue is not None

    bus.emit(EventType.WORKFLOW_STARTED, "test-thread-123", {"phase": "scouting"})

    event = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert event.thread_id == "test-thread-123"

    bus.unsubscribe_thread("test-thread-123", queue)


@pytest.mark.asyncio
async def test_multiple_subscribers_same_thread():
    """Multiple SSE clients for same thread should each get their own queue."""
    bus = EventBusService.get_instance()

    q1 = bus.subscribe_thread("multi-thread")
    q2 = bus.subscribe_thread("multi-thread")

    bus.emit(EventType.WORKFLOW_STARTED, "multi-thread", {"test": True})

    e1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    e2 = await asyncio.wait_for(q2.get(), timeout=1.0)

    assert e1.thread_id == "multi-thread"
    assert e2.thread_id == "multi-thread"

    bus.unsubscribe_thread("multi-thread", q1)
    bus.unsubscribe_thread("multi-thread", q2)
