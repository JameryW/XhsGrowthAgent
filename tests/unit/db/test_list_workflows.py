"""list_workflows single-query (COUNT(*) OVER()) contract tests.

`list_workflows` collapsed from 2 round-trips (COUNT + SELECT) to 1 via the
``COUNT(*) OVER() AS full_count`` window function. These tests pin the
``total`` derivation across the pagination boundary and verify filters /
order_by / limit / offset are still threaded into the single SQL statement.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.db.workflows import list_workflows


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
    async def cursor_context(*_args: Any, **_kwargs: Any) -> Any:
        yield cursor

    conn.cursor = cursor_context
    return conn


def _row(thread_id: str, full_count: int, **overrides: Any) -> dict[str, Any]:
    base = {
        "thread_id": thread_id,
        "account_id": overrides.get("account_id", "acct-1"),
        "status": overrides.get("status", "completed"),
        "phase": "completed",
        "progress_percent": 100,
        "label": "",
        "workflow_mode": "trend",
        "showcase_visibility": overrides.get("showcase_visibility", "private"),
        "public_id": None,
        "showcase_featured": False,
        "featured_rank": None,
        "public_title": None,
        "public_summary": None,
        "approved_at": None,
        "approved_by": None,
        "redaction_version": "v1",
        "dry_run": False,
        "auto_publish": False,
        "error": None,
        "task_error": None,
        "task_done_at": None,
        "created_at": overrides.get("created_at", "2026-08-06T00:00:00+00:00"),
        "updated_at": overrides.get("updated_at", "2026-08-06T00:00:00+00:00"),
        # Window-function column — must be ignored by _row_from_dict.
        "full_count": full_count,
    }
    return base


@pytest.mark.asyncio
async def test_zero_rows_total_is_zero_and_single_query():
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[])
    conn = _mock_connection(cursor)

    with patch("backend.db.workflows.get_pool", return_value=_mock_pool(conn)):
        rows, total = await list_workflows()

    assert rows == []
    assert total == 0
    # Exactly one query (window fn) — not the old COUNT + SELECT pair.
    assert cursor.execute.await_count == 1
    sql = cursor.execute.await_args.args[0]
    assert "COUNT(*) OVER() AS full_count" in sql


@pytest.mark.asyncio
async def test_rows_below_limit_total_equals_row_count():
    # 3 matching rows, limit 20 → total is the full_count stamped on each row.
    rows_data = [
        _row("t1", full_count=3),
        _row("t2", full_count=3),
        _row("t3", full_count=3),
    ]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows_data)
    conn = _mock_connection(cursor)

    with patch("backend.db.workflows.get_pool", return_value=_mock_pool(conn)):
        rows, total = await list_workflows()

    assert [r.thread_id for r in rows] == ["t1", "t2", "t3"]
    assert total == 3
    assert cursor.execute.await_count == 1


@pytest.mark.asyncio
async def test_pagination_boundary_total_exceeds_returned_rows():
    # DB has 5 matching rows but LIMIT 2 returns only 2; total must still be 5.
    rows_data = [
        _row("t1", full_count=5),
        _row("t2", full_count=5),
    ]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows_data)
    conn = _mock_connection(cursor)

    with patch("backend.db.workflows.get_pool", return_value=_mock_pool(conn)):
        rows, total = await list_workflows(limit=2, offset=0)

    assert len(rows) == 2
    assert total == 5  # full_count reflects pre-LIMIT total, not returned rows
    assert total > len(rows)
    # limit/offset threaded into the single query params.
    params = cursor.execute.await_args.args[1]
    assert params[-2] == 2  # limit
    assert params[-1] == 0  # offset


@pytest.mark.asyncio
async def test_filters_account_id_status_showcase_visibility_in_where_and_params():
    rows_data = [
        _row(
            "t1", full_count=1, account_id="acct-A", status="running", showcase_visibility="public"
        )
    ]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows_data)
    conn = _mock_connection(cursor)

    with patch("backend.db.workflows.get_pool", return_value=_mock_pool(conn)):
        rows, total = await list_workflows(
            account_id="acct-A",
            status="running",
            showcase_visibility="public",
            limit=10,
            offset=5,
        )

    assert len(rows) == 1
    assert total == 1
    sql = cursor.execute.await_args.args[0]
    assert "account_id = %s" in sql
    assert "status = %s" in sql
    assert "showcase_visibility = %s" in sql
    params = cursor.execute.await_args.args[1]
    assert params == ["acct-A", "running", "public", 10, 5]


@pytest.mark.asyncio
async def test_order_by_updated_at_selects_correct_column():
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[])
    conn = _mock_connection(cursor)

    with patch("backend.db.workflows.get_pool", return_value=_mock_pool(conn)):
        await list_workflows(order_by="updated_at")

    sql = cursor.execute.await_args.args[0]
    assert "ORDER BY updated_at DESC" in sql


@pytest.mark.asyncio
async def test_full_count_key_does_not_leak_into_workflow_row():
    """_row_from_dict must ignore the extra full_count window column."""
    rows_data = [_row("t1", full_count=7)]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows_data)
    conn = _mock_connection(cursor)

    with patch("backend.db.workflows.get_pool", return_value=_mock_pool(conn)):
        rows, total = await list_workflows()

    assert total == 7
    row = rows[0]
    assert row.thread_id == "t1"
    # WorkflowRow is a dataclass without a full_count field.
    assert not hasattr(row, "full_count")
