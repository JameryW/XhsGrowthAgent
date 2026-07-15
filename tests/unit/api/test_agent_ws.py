"""Regression tests for mode preservation in the agent websocket route."""

from __future__ import annotations

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
