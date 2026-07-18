"""Unit coverage for privacy-safe public UX telemetry aggregation."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _mock_pool(conn: MagicMock) -> MagicMock:
    pool = MagicMock()

    @asynccontextmanager
    async def connection_context():
        yield conn

    pool.connection = connection_context
    return pool


def _mock_connection(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()

    @asynccontextmanager
    async def cursor_context(*_args, **_kwargs):
        yield cursor

    conn.cursor = cursor_context
    return conn


@pytest.mark.asyncio
async def test_summary_keeps_cached_as_an_anonymous_dimension():
    from backend.db.public_telemetry import summarize_events

    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(
        return_value=[
            {
                "event_name": "replay_select_to_render",
                "cached": True,
                "event_count": 2,
                "measured_count": 2,
                "p50_duration_ms": 0,
                "p75_duration_ms": 0,
            }
        ]
    )
    conn = _mock_connection(cursor)

    with (
        patch("backend.db.public_telemetry.is_pool_ready", return_value=True),
        patch("backend.db.public_telemetry.get_pool", return_value=_mock_pool(conn)),
    ):
        rows = await summarize_events()

    assert rows[0]["cached"] is True
    sql = cursor.execute.await_args.args[0]
    assert "cached," in sql
    assert "view_mode, cached" in sql
    assert "decision, period, old_period" in sql


@pytest.mark.asyncio
async def test_ensure_tables_backfills_cached_column_for_old_deploys():
    """Old deploys created the table before `cached` existed; CREATE TABLE IF
    NOT EXISTS skips. ensure_tables must ADD COLUMN IF NOT EXISTS so summarize_events
    doesn't UndefinedColumn."""
    from backend.db.public_telemetry import _ADD_COLUMN_SQL, ensure_tables

    conn = MagicMock()
    conn.execute = AsyncMock()

    with (
        patch("backend.db.public_telemetry.is_pool_ready", return_value=True),
        patch("backend.db.public_telemetry.get_pool", return_value=_mock_pool(conn)),
    ):
        await ensure_tables()

    executed = [call.args[0] for call in conn.execute.await_args_list]
    add_column_sqls = [sql for sql in executed if "ADD COLUMN IF NOT EXISTS" in sql]
    # every column listed in _ADD_COLUMN_SQL ran
    assert len(add_column_sqls) == len(_ADD_COLUMN_SQL)
    assert any("ADD COLUMN IF NOT EXISTS cached BOOLEAN" in sql for sql in add_column_sqls)
    assert any("ADD COLUMN IF NOT EXISTS decision TEXT" in sql for sql in add_column_sqls)
    assert any("ADD COLUMN IF NOT EXISTS old_period TEXT" in sql for sql in add_column_sqls)
