"""Regression tests for mode preservation in the agent websocket route."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest
from fastapi import WebSocketDisconnect

from backend.api.routes.agent import agent_ws
from backend.services.omp_bridge import ClientMessageType

pytestmark = pytest.mark.asyncio


class _FakeSession:
    def __init__(self, session_id: str, mode: str) -> None:
        self.session_id = session_id
        self.mode = mode
        self.is_ready = True
        self.callbacks = []

    def on_event(self, callback) -> None:
        self.callbacks.append(callback)

    def remove_event_callback(self, callback) -> None:
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    async def send_message(self, _content: str) -> None:
        return None


class _FakeManager:
    def __init__(self) -> None:
        self.initial = _FakeSession("initial", "free")
        self.replacement = _FakeSession("replacement", "free")
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def get_or_create_session(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.initial if len(self.calls) == 1 else self.replacement

    def start_idle_timer(self, _session_id: str) -> None:
        return None


class _FakeWebSocket:
    query_params = {"mode": "free"}

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive_text(self) -> str:
        if len(self.sent) == 1:
            return json.dumps({"type": ClientMessageType.NEW_SESSION})
        raise WebSocketDisconnect()


async def test_new_session_preserves_free_creation_mode() -> None:
    websocket = _FakeWebSocket()
    manager = _FakeManager()

    with patch("backend.api.routes.agent.get_bridge_manager", return_value=manager):
        await agent_ws(websocket)  # type: ignore[arg-type]

    assert websocket.accepted
    assert manager.calls[0] == ((None,), {"mode": "free"})
    assert manager.calls[1] == ((), {"mode": "free"})
    assert websocket.sent[-1]["session_id"] == "replacement"


# ── Reconnect replay + heartbeat protocol ──────────────────────────────────


class _ReplaySession:
    """Fake session with a replay buffer, as OmpSession exposes it."""

    def __init__(self, session_id: str, mode: str = "workflow") -> None:
        self.session_id = session_id
        self.mode = mode
        self.is_ready = True
        self.callbacks = []
        self.current_seq = 5
        self._buffered = [
            {"type": "agent_message", "text": "missed-1", "seq": 4, "session_id": session_id},
            {"type": "agent_message", "text": "missed-2", "seq": 5, "session_id": session_id},
        ]

    def on_event(self, callback) -> None:
        self.callbacks.append(callback)

    def remove_event_callback(self, callback) -> None:
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    def events_after(self, last_seq: int, high_water: int | None = None) -> list[dict]:
        upper = self.current_seq if high_water is None else high_water
        return [e for e in self._buffered if last_seq < e["seq"] <= upper]


class _ReplayManager:
    def __init__(self) -> None:
        self.session = _ReplaySession("omp_x")

    def get_session(self, session_id: str | None):
        if session_id == self.session.session_id:
            return self.session
        return None

    async def get_or_create_session(self, session_id=None, mode="workflow"):
        return self.session

    def start_idle_timer(self, _session_id: str) -> None:
        return None


class _ReplayWebSocket:
    """Reconnect with a replay cursor; disconnects once replay is flushed."""

    query_params = {"session_id": "omp_x", "last_seq": "3"}

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.accepted = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive_text(self) -> str:
        # Give the sender task a moment to flush the replayed events
        for _ in range(100):
            if any(m.get("text") == "missed-2" for m in self.sent):
                break
            await asyncio.sleep(0.01)
        raise WebSocketDisconnect()


async def test_reconnect_replays_missed_events_for_resumed_session() -> None:
    websocket = _ReplayWebSocket()
    manager = _ReplayManager()

    with patch("backend.api.routes.agent.get_bridge_manager", return_value=manager):
        await agent_ws(websocket)  # type: ignore[arg-type]

    connected = websocket.sent[0]
    assert connected["status"] == "connected"
    assert connected["resumed"] is True
    texts = [m.get("text") for m in websocket.sent if m.get("type") == "agent_message"]
    assert texts == ["missed-1", "missed-2"]


class _PongWebSocket:
    query_params: dict = {}

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._sent_pong = False

    async def accept(self) -> None:
        return None

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive_text(self) -> str:
        if not self._sent_pong:
            self._sent_pong = True
            return json.dumps({"type": "pong"})
        raise WebSocketDisconnect()


async def test_pong_heartbeat_reply_is_silently_ignored() -> None:
    websocket = _PongWebSocket()
    manager = _ReplayManager()

    with patch("backend.api.routes.agent.get_bridge_manager", return_value=manager):
        await agent_ws(websocket)  # type: ignore[arg-type]

    # Fresh session (no session_id param) → not resumed; no unknown-type error
    assert websocket.sent[0]["resumed"] is False
    errors = [m for m in websocket.sent if m.get("type") == "error"]
    assert errors == []


# ── Client-facing exception sanitization ────────────────────────────────────


class _StatusErrorSession:
    """Session whose get_status() raises — exercises the ws catch-all branch."""

    def __init__(self, session_id: str = "err1", mode: str = "free") -> None:
        self.session_id = session_id
        self.mode = mode
        self.is_ready = True
        self.callbacks = []

    def on_event(self, callback) -> None:
        self.callbacks.append(callback)

    def remove_event_callback(self, callback) -> None:
        if callback in self.callbacks:
            self.callbacks.remove(callback)

    async def get_status(self):
        raise RuntimeError("secret internal path /etc/passwd")


class _StatusErrorManager:
    def __init__(self) -> None:
        self.session = _StatusErrorSession()

    async def get_or_create_session(self, session_id=None, mode="workflow"):
        return self.session

    def start_idle_timer(self, _session_id: str) -> None:
        return None


class _StatusErrorWebSocket:
    query_params: dict = {}

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self.accepted = False
        self._asked = False

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def receive_text(self) -> str:
        if not self._asked:
            self._asked = True
            return json.dumps({"type": ClientMessageType.GET_STATUS})
        raise WebSocketDisconnect()


async def test_ws_handler_error_does_not_leak_raw_exception_text() -> None:
    """Catch-all ws error must send a generic message, not raw str(e)."""
    websocket = _StatusErrorWebSocket()
    manager = _StatusErrorManager()

    with patch("backend.api.routes.agent.get_bridge_manager", return_value=manager):
        await agent_ws(websocket)  # type: ignore[arg-type]

    errors = [m for m in websocket.sent if m.get("type") == "error"]
    assert errors, "expected an error message after get_status() raised"
    # Generic message only; raw exception text must not leak.
    assert errors[-1]["message"] == "internal error"
    assert "secret internal path" not in errors[-1]["message"]
    assert "/etc/passwd" not in errors[-1]["message"]


class _PrewarmManager:
    def __init__(self, *, ready_mode: str | None = None) -> None:
        self.created: list[str] = []
        self._ready_mode = ready_mode
        self._session = _FakeSession("warm1", ready_mode or "free")

    @property
    def session_ids(self) -> list[str]:
        return ["warm1"] if self._ready_mode else []

    def get_session(self, session_id: str):
        if self._ready_mode and session_id == "warm1":
            return self._session
        return None

    async def get_or_create_session(self, session_id=None, mode: str = "workflow"):
        self.created.append(mode)
        await asyncio.sleep(0)
        return _FakeSession("new", mode)


async def test_prewarm_agent_session_returns_ready_when_live() -> None:
    from backend.api.routes.agent import prewarm_agent_session

    manager = _PrewarmManager(ready_mode="free")
    with patch("backend.api.routes.agent.get_bridge_manager", return_value=manager):
        resp = await prewarm_agent_session(mode="free", _user={"id": "u1"})

    assert resp.success is True
    assert resp.data == {"status": "ready", "mode": "free", "session_id": "warm1"}
    assert manager.created == []


async def test_prewarm_agent_session_fires_background_create() -> None:
    from backend.api.routes import agent as agent_mod
    from backend.api.routes.agent import prewarm_agent_session

    agent_mod._prewarm_tasks.clear()
    manager = _PrewarmManager(ready_mode=None)
    with patch("backend.api.routes.agent.get_bridge_manager", return_value=manager):
        resp = await prewarm_agent_session(mode="free", _user={"id": "u1"})
        assert resp.data["status"] == "warming"
        # Let background task run
        task = agent_mod._prewarm_tasks.get("free")
        if task is not None:
            await task

    assert "free" in manager.created
