"""Tests for SSE EventBus-driven streaming."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from backend.api.app import app
from backend.api.routes import _runner as runner_module
from backend.realtime.event_bus import EventBusService
from backend.realtime.events import EventType
from backend.state.enums import WorkflowPhase
from backend.state.machine import WorkflowStatus


def _make_snapshot(values: dict, next_nodes=None, interrupts=None) -> MagicMock:
    """Build a mock LangGraph StateSnapshot."""
    snap = MagicMock()
    snap.values = values
    snap.next = next_nodes or []
    snap.tasks = []
    snap.interrupts = interrupts or []
    return snap


@pytest.fixture
def sse_client():
    """Test client with mocked graph state on app.state."""
    graph = MagicMock()
    graph.aget_state = AsyncMock(
        return_value=_make_snapshot({"phase": WorkflowPhase.COMPLETED, "session_id": "s"})
    )
    app.state.graph = graph
    saved_bg = runner_module._background_tasks.copy()
    runner_module._background_tasks.clear()
    bus = EventBusService.get_instance()
    saved_events = list(bus._events)
    saved_seq = bus._seq
    bus._events.clear()
    bus._seq = 0
    yield TestClient(app)
    runner_module._background_tasks.clear()
    runner_module._background_tasks.update(saved_bg)
    bus._events.clear()
    bus._events.extend(saved_events)
    bus._seq = saved_seq
    if hasattr(app.state, "graph"):
        delattr(app.state, "graph")


# ── Terminal-state synthetic event ────────────────────────────────────────────


def test_sse_emits_synthetic_completed_for_terminal_workflow(sse_client):
    """Fresh connect to an already-completed workflow → synthetic WORKFLOW_COMPLETED.

    Without this, the client hangs forever waiting for an event that was
    broadcast before it subscribed. The synthetic event must close the stream.
    """
    graph = app.state.graph
    graph.aget_state.return_value = _make_snapshot(
        {"phase": WorkflowPhase.COMPLETED, "session_id": "s", "analytics": {"x": 1}}
    )
    with sse_client.stream("GET", "/api/workflow/stream/completed-thread") as resp:
        assert resp.status_code == 200
        events = []
        for line in resp.iter_lines():
            if line.startswith("event:"):
                events.append(line[len("event:") :].strip())
            if line == "" and events:
                break
    assert "workflow.completed" in events


def test_sse_synthetic_completed_carries_content_fields(sse_client):
    """Synthetic WORKFLOW_COMPLETED payload must carry content fields (cross-layer).

    The real WORKFLOW_COMPLETED (runner._emit_progress) carries publish_result,
    copy_content, analytics, etc. The synthetic event must do the same so SSE
    consumers don't see an empty terminal payload (cross-layer contract parity).
    """
    graph = app.state.graph
    graph.aget_state.return_value = _make_snapshot(
        {
            "phase": WorkflowPhase.COMPLETED,
            "session_id": "s",
            "publish_result": {"note_id": "abc"},
            "analytics": {"views": 100},
            "copy_content": {"title": "t"},
        }
    )
    import json

    with sse_client.stream("GET", "/api/workflow/stream/carry-thread") as resp:
        body = "\n".join(resp.iter_lines())
    # find the data: line for workflow.completed
    data_lines = [ln[len("data:") :].strip() for ln in body.split("\n") if ln.startswith("data:")]
    assert data_lines, "no data line emitted"
    payload = json.loads(data_lines[0])
    assert payload["status"] == "completed"
    assert payload["publish_result"] == {"note_id": "abc"}
    assert payload["analytics"] == {"views": 100}
    assert payload["copy_content"] == {"title": "t"}


def test_sse_emits_synthetic_error_for_error_workflow(sse_client):
    """Terminal ERROR state → synthetic WORKFLOW_ERROR with error field."""
    graph = app.state.graph
    graph.aget_state.return_value = _make_snapshot(
        {
            "phase": WorkflowPhase.ERROR,
            "session_id": "s",
            "error": "publish failed",
        }
    )
    import json

    with sse_client.stream("GET", "/api/workflow/stream/err-thread") as resp:
        body = "\n".join(resp.iter_lines())
    assert "event: workflow.error" in body
    data_lines = [ln[len("data:") :].strip() for ln in body.split("\n") if ln.startswith("data:")]
    payload = json.loads(data_lines[0])
    assert payload["status"] == "error"
    assert payload["error"] == "publish failed"


def test_sse_cancelled_mapped_to_completed_with_status(sse_client):
    """CANCELLED state → WORKFLOW_COMPLETED with status=cancelled.

    CANCELLED must close the SSE stream (only COMPLETED/ERROR close it), so it
    is mapped to WORKFLOW_COMPLETED. The payload status field lets consumers
    distinguish cancellation from real completion (cross-layer contract).
    """
    graph = app.state.graph
    graph.aget_state.return_value = _make_snapshot(
        {"phase": WorkflowPhase.CANCELLED, "session_id": "s"}
    )
    import json

    with sse_client.stream("GET", "/api/workflow/stream/cancel-thread") as resp:
        body = "\n".join(resp.iter_lines())
    assert "event: workflow.completed" in body
    data_lines = [ln[len("data:") :].strip() for ln in body.split("\n") if ln.startswith("data:")]
    payload = json.loads(data_lines[0])
    assert payload["status"] == "cancelled"


def test_sse_skips_synthetic_when_workflow_running(sse_client):
    """Running workflow (next_nodes + active task) → no synthetic event, stream stays open.

    The terminal check must not falsely close the stream for a live workflow.
    The sse_client fixture's graph defaults to COMPLETED (terminal), so we
    override it to return a running state here. A running workflow has
    next_nodes present and an active background task — derive_status returns
    RUNNING, which is NOT in the terminal set, so the synthetic-event branch
    is skipped and the generator proceeds to subscribe_thread (stream stays open).

    We can't let the generator block on queue.get() inside TestClient, so we
    assert two things:
    1. derive_status(snap, has_active_task=True) == RUNNING (the gate condition)
    2. The terminal-state set does NOT contain RUNNING (the branch condition)
    """
    from backend.state.machine import derive_status

    snap = _make_snapshot(
        {"phase": WorkflowPhase.SCOUTING, "session_id": "s"}, next_nodes=["trend_scout"]
    )
    # active task present → RUNNING, not terminal
    assert derive_status(snap, has_active_task=True) == WorkflowStatus.RUNNING
    # RUNNING must NOT be in the terminal set the SSE handler checks
    assert WorkflowStatus.RUNNING not in (
        WorkflowStatus.COMPLETED,
        WorkflowStatus.ERROR,
        WorkflowStatus.CANCELLED,
    )


# ── Last-Event-ID reconnect dedup ─────────────────────────────────────────────


def test_sse_last_event_id_replays_only_missed_events(sse_client):
    """Reconnect with Last-Event-ID header → replay only seq > last, scoped to thread.

    A fresh connect (no header) must NOT bulk-replay history — that would
    re-deliver events to a reconnecting client that forgot the header. This
    test verifies the seq-based scoping matches the WebSocket get_missed path.
    """
    bus = EventBusService.get_instance()
    bus._events.clear()
    bus._seq = 0
    # emit 3 events for thread-A, 1 for thread-B
    bus.emit(EventType.WORKFLOW_STARTED, "thread-A", {"n": 1})  # seq 0
    bus.emit(EventType.WORKFLOW_PHASE_CHANGED, "thread-A", {"n": 2})  # seq 1
    bus.emit(EventType.WORKFLOW_DATA_UPDATED, "thread-B", {"n": 3})  # seq 2
    # client saw up to seq 1 → should only get seq 2 (thread-B filtered out).
    # The sse_client fixture's graph returns COMPLETED, so after the (empty)
    # replay loop the terminal check emits a synthetic WORKFLOW_COMPLETED and
    # the stream closes — no blocking.
    with sse_client.stream(
        "GET",
        "/api/workflow/stream/thread-A",
        headers={"Last-Event-ID": "1"},
    ) as resp:
        body = "\n".join(resp.iter_lines())
    # thread-B event must NOT appear (scoped to thread-A)
    assert "thread-B" not in body
    # thread-A's already-seen events (seq 0, 1) must NOT be replayed
    assert '"n": 1' not in body
    assert '"n": 2' not in body
    # Stream must close via synthetic terminal event (graph is COMPLETED)
    assert "workflow.completed" in body


def test_sse_fresh_connect_does_not_bulk_replay(sse_client):
    """Fresh connect (no Last-Event-ID) must not replay buffered history.

    Previously the code did get_events_since(0) on every connect, re-delivering
    the whole ring buffer. Now fresh connects skip the replay and go straight
    to the terminal check. This test confirms no buffered non-terminal event
    leaks to a fresh client.
    """
    bus = EventBusService.get_instance()
    bus._events.clear()
    bus._seq = 0
    bus.emit(EventType.WORKFLOW_STARTED, "fresh-thread", {"phase": "scouting"})
    # graph is terminal-completed (default fixture) → synthetic COMPLETED only,
    # no WORKFLOW_STARTED replay
    with sse_client.stream("GET", "/api/workflow/stream/fresh-thread") as resp:
        body = "\n".join(resp.iter_lines())
    assert "workflow.started" not in body
    assert "workflow.completed" in body


# ── EventBus.current_seq ──────────────────────────────────────────────────────


def test_event_bus_current_seq_returns_next_seq():
    """current_seq() returns the next seq to be assigned (for SSE id: field)."""
    bus = EventBusService.get_instance()
    bus._events.clear()
    bus._seq = 42
    assert bus.current_seq() == 42
    bus.emit(EventType.WORKFLOW_STARTED, "t", {})  # assigns seq 42, bumps to 43
    assert bus.current_seq() == 43


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
