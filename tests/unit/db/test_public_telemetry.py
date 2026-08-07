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


@pytest.mark.asyncio
async def test_record_event_prune_throttled():
    """Rapid successive beacons run INSERT every time but DELETE only once
    (throttled to ≤ once per _PRUNE_INTERVAL_S)."""
    import backend.db.public_telemetry as mod

    conn = MagicMock()
    conn.execute = AsyncMock()

    # Reset throttle so the first call elapses (now - 0 >> interval) and prunes.
    mod._last_prune_ts = 0.0

    # Control the clock so the test does not depend on the real time.monotonic()
    # absolute value (CI runners may return < _PRUNE_INTERVAL_S at process start,
    # which would make the gate False and the DELETE never run).
    clock = iter([1000.0, 1000.1])

    event = {"event": "replay_select_to_render"}

    with (
        patch("backend.db.public_telemetry.is_pool_ready", return_value=True),
        patch("backend.db.public_telemetry.get_pool", return_value=_mock_pool(conn)),
        patch("backend.db.public_telemetry.time.monotonic", side_effect=lambda: next(clock)),
    ):
        await mod.record_event(event)  # 1000 - 0 >= 300 → DELETE + ts=1000
        await mod.record_event(event)  # 1000.1 - 1000 < 300 → skip

    executed = [call.args[0] for call in conn.execute.await_args_list]
    inserts = [sql for sql in executed if "INSERT INTO public_ux_events" in sql]
    deletes = [sql for sql in executed if "DELETE FROM public_ux_events" in sql]

    # INSERT runs per beacon (always).
    assert len(inserts) == 2
    # DELETE throttled: runs on the first call (now - 0 >= interval), skipped
    # on the second (immediately after, within interval).
    assert len(deletes) == 1


@pytest.mark.asyncio
async def test_record_event_prune_runs_after_interval():
    """Once _PRUNE_INTERVAL_S has elapsed since the last prune, the next beacon
    runs DELETE again and updates the throttle timestamp."""
    import backend.db.public_telemetry as mod

    conn = MagicMock()
    conn.execute = AsyncMock()

    # Fixed clock; force elapsed by setting last prune one interval+1 in the
    # past. Controlling the clock keeps this deterministic regardless of the
    # real time.monotonic() absolute value (CI runners may return < interval).
    clock = iter([1000.0])
    mod._last_prune_ts = 1000.0 - mod._PRUNE_INTERVAL_S - 1.0  # =699
    before = mod._last_prune_ts

    event = {"event": "replay_select_to_render"}

    with (
        patch("backend.db.public_telemetry.is_pool_ready", return_value=True),
        patch("backend.db.public_telemetry.get_pool", return_value=_mock_pool(conn)),
        patch("backend.db.public_telemetry.time.monotonic", side_effect=lambda: next(clock)),
    ):
        await mod.record_event(event)  # 1000 - 699 >= 300 → DELETE + ts=1000

    executed = [call.args[0] for call in conn.execute.await_args_list]
    deletes = [sql for sql in executed if "DELETE FROM public_ux_events" in sql]
    assert len(deletes) == 1
    # Timestamp advanced past the stale value.
    assert mod._last_prune_ts > before
