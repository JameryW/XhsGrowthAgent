"""The dev/SQLite graph owns a non-daemon aiosqlite worker thread.

``compile_graph_dev`` stores its aiosqlite connection on the compiled graph.  If
application shutdown forgets to close it, the interpreter waits forever for the
worker thread, so ``pytest`` printed its summary but never exited and ``serve``
restarts hung.  These tests pin the shutdown helper that closes it.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_close_dev_sqlite_checkpointer_closes_connection():
    from backend.api.app import _close_dev_sqlite_checkpointer

    connection = SimpleNamespace(close=AsyncMock())
    graph = SimpleNamespace(_sqlite_conn=connection)

    await _close_dev_sqlite_checkpointer(graph)

    connection.close.assert_awaited_once()
    assert graph._sqlite_conn is None


@pytest.mark.asyncio
async def test_close_dev_sqlite_checkpointer_is_noop_for_none():
    from backend.api.app import _close_dev_sqlite_checkpointer

    await _close_dev_sqlite_checkpointer(None)


@pytest.mark.asyncio
async def test_close_dev_sqlite_checkpointer_swallows_close_errors():
    from backend.api.app import _close_dev_sqlite_checkpointer

    connection = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("already gone")))
    graph = SimpleNamespace(_sqlite_conn=connection)

    await _close_dev_sqlite_checkpointer(graph)  # must not raise
