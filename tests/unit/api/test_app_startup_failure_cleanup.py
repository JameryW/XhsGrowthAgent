"""A startup failure after the dev graph opens SQLite must close it before raising.

``compile_graph_dev`` starts a non-daemon aiosqlite worker.  The lazy close after
``yield`` only covered the happy path, so any later startup raise (bad Settings,
Ripple initialisation, …) left the thread behind: uvicorn logs "startup failed"
and the process still hangs joining the worker instead of exiting with the error.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_startup_failure_closes_dev_sqlite_graph(monkeypatch):
    from fastapi import FastAPI

    app_module = importlib.import_module("backend.api.app")  # module, not the FastAPI instance

    from backend.graph import builder
    from backend.services import ripple_service

    connection = SimpleNamespace(close=AsyncMock())
    fake_graph = SimpleNamespace(_sqlite_conn=connection, checkpointer=None)

    async def fake_compile_graph_dev():
        return fake_graph

    monkeypatch.setattr(builder, "compile_graph_dev", fake_compile_graph_dev)
    monkeypatch.delenv("POSTGRES_URI", raising=False)

    class StartupBoomError(RuntimeError):
        pass

    class ExplodingRipple:
        @classmethod
        def get_instance(cls):
            raise StartupBoomError("ripple initialisation failed")

        def start_background_health_check(self, **_kwargs):  # pragma: no cover - never reached
            raise AssertionError("should not be reached")

    monkeypatch.setattr(ripple_service, "RippleService", ExplodingRipple)

    with pytest.raises(StartupBoomError):
        async with app_module.lifespan(FastAPI()):
            pytest.fail("lifespan must not reach yield when startup fails")  # pragma: no cover

    connection.close.assert_awaited_once()
    assert fake_graph._sqlite_conn is None
