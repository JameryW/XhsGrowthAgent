"""Tests for _db_upsert skip-unchanged optimization.

/status polls every 5s and calls _db_upsert with the same phase/status/progress
each tick. The skip-unchanged guard avoids a no-op UPDATE (DB round trip + row
lock) when the fetched row already matches all passed fields. Callers that
mutate state (start/resume/pause/cancel) always pass a differing field, so they
still write.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.routes import _runner as runner_module
from backend.db.workflows import WorkflowRow

_POOL_READY = "backend.db.pool.is_pool_ready"
_DB_GET = "backend.db.workflows.get_workflow"
_DB_UPDATE = "backend.db.workflows.update_workflow"
_DB_CREATE = "backend.db.workflows.create_workflow"


def _existing_row(**overrides) -> WorkflowRow:
    base = WorkflowRow(thread_id="t1")
    return replace(base, **overrides)


class TestFieldsDiffer:
    def test_all_fields_match_returns_false(self):
        row = _existing_row(phase="scouting", status="running", progress_percent=10)
        assert (
            runner_module._fields_differ(
                {"phase": "scouting", "status": "running", "progress_percent": 10},
                row,
            )
            is False
        )

    def test_one_field_differs_returns_true(self):
        row = _existing_row(phase="scouting", status="running", progress_percent=10)
        assert runner_module._fields_differ({"progress_percent": 20}, row) is True

    def test_missing_attribute_on_existing_returns_true(self):
        row = _existing_row()
        assert runner_module._fields_differ({"nonexistent_field": "x"}, row) is True

    def test_empty_fields_returns_false(self):
        row = _existing_row()
        assert runner_module._fields_differ({}, row) is False


class TestDbUpsertSkipUnchanged:
    @pytest.mark.asyncio
    async def test_skips_update_when_fields_match_existing(self):
        existing = _existing_row(phase="scouting", status="running", progress_percent=10)
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, AsyncMock(return_value=existing)),
            patch(_DB_UPDATE, AsyncMock()) as update_mock,
            patch(_DB_CREATE, AsyncMock()) as create_mock,
        ):
            await runner_module._db_upsert(
                "t1", phase="scouting", status="running", progress_percent=10
            )
        update_mock.assert_not_called()
        create_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_writes_when_field_differs(self):
        existing = _existing_row(phase="scouting", status="running", progress_percent=10)
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, AsyncMock(return_value=existing)),
            patch(_DB_UPDATE, AsyncMock()) as update_mock,
        ):
            await runner_module._db_upsert("t1", progress_percent=20)
        update_mock.assert_awaited_once_with("t1", progress_percent=20)

    @pytest.mark.asyncio
    async def test_creates_when_no_existing_row(self):
        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, AsyncMock(return_value=None)),
            patch(_DB_UPDATE, AsyncMock()) as update_mock,
            patch(_DB_CREATE, AsyncMock()) as create_mock,
        ):
            await runner_module._db_upsert("t1", phase="scouting", status="running")
        update_mock.assert_not_called()
        create_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_noop_when_pool_not_ready(self):
        with (
            patch(_POOL_READY, return_value=False),
            patch(_DB_GET, AsyncMock()) as get_mock,
        ):
            await runner_module._db_upsert("t1", phase="scouting")
        get_mock.assert_not_called()
