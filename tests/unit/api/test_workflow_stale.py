"""Tests for workflow done callback and stale status handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.state.machine import WorkflowStatus

_POOL_READY = "backend.api.routes.workflow.is_pool_ready"
_DB_GET = "backend.api.routes.workflow.db_get"
_DB_UPDATE = "backend.api.routes.workflow.db_update"


class TestOnTaskDone:
    """Test _on_task_done callback behavior."""

    @pytest.mark.asyncio
    async def test_callback_records_task_done_at(self):
        """Done callback schedules DB update with task_done_at."""
        from backend.api.routes.workflow import _on_task_done

        thread_id = "test_thread_done_at"

        with patch(_POOL_READY, return_value=False):
            callback = _on_task_done(thread_id)
            task = asyncio.create_task(asyncio.sleep(0))
            task.add_done_callback(callback)
            await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_callback_marks_stale_when_db_running(self):
        """Done callback marks STALE when DB row still shows running."""
        from backend.api.routes.workflow import _on_task_done

        thread_id = "test_thread_stale"

        mock_row = MagicMock()
        mock_row.status = "running"

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=mock_row),
            patch(_DB_UPDATE, new_callable=AsyncMock) as mock_update,
        ):
            callback = _on_task_done(thread_id)
            task = asyncio.create_task(asyncio.sleep(0))
            task.add_done_callback(callback)
            await asyncio.sleep(0.05)

            if mock_update.called:
                call_kwargs = mock_update.call_args
                assert call_kwargs[0][0] == thread_id
                assert "status" in call_kwargs[1]
                assert call_kwargs[1]["status"] == "stale"

    @pytest.mark.asyncio
    async def test_callback_records_error_on_exception(self):
        """Done callback records task_error when task raised exception."""
        from backend.api.routes._runner import _background_tasks
        from backend.api.routes.workflow import _on_task_done

        thread_id = "test_task_error"

        async def _fail():
            raise RuntimeError("test failure")

        mock_row = MagicMock()
        mock_row.status = "running"

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=mock_row),
            patch(_DB_UPDATE, new_callable=AsyncMock) as mock_update,
        ):
            callback = _on_task_done(thread_id)
            task = asyncio.create_task(_fail())
            # Register the task so the callback's "replaced by a newer task"
            # guard does not early-return (matches production wiring).
            _background_tasks[thread_id] = task
            task.add_done_callback(callback)
            for _ in range(100):
                if mock_update.called:
                    break
                await asyncio.sleep(0.01)
            try:
                assert mock_update.called
                call_kwargs = mock_update.call_args
                assert call_kwargs[0][0] == thread_id
                assert "task_error" in call_kwargs[1]
                # ponytail: generic + typename, NOT raw str(e).
                assert call_kwargs[1]["task_error"] == "后台任务异常: RuntimeError"
                assert "error" in call_kwargs[1]
                assert call_kwargs[1]["error"] == "后台任务异常: RuntimeError"
            finally:
                _background_tasks.pop(thread_id, None)

    @pytest.mark.asyncio
    async def test_callback_does_not_leak_raw_exception_text(self):
        """Done callback must not leak raw str(e) (paths/SQL) to DB columns."""
        from backend.api.routes._runner import _background_tasks
        from backend.api.routes.workflow import _on_task_done

        thread_id = "test_task_error_leak"

        secret = "secret internal path /etc/passwd"

        async def _fail():
            raise ValueError(secret)

        mock_row = MagicMock()
        mock_row.status = "running"

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=mock_row),
            patch(_DB_UPDATE, new_callable=AsyncMock) as mock_update,
        ):
            callback = _on_task_done(thread_id)
            task = asyncio.create_task(_fail())
            _background_tasks[thread_id] = task
            task.add_done_callback(callback)
            # The callback schedules the DB update via asyncio.ensure_future;
            # poll until it runs (deterministic across slow CI runners).
            for _ in range(100):
                if mock_update.called:
                    break
                await asyncio.sleep(0.01)
            try:
                assert mock_update.called, "DB update should fire on task error"
                call_kwargs = mock_update.call_args
                task_error = call_kwargs[1].get("task_error", "")
                error = call_kwargs[1].get("error", "")
                # Generic + typename only; raw message must not leak.
                assert task_error == "后台任务异常: ValueError"
                assert error == "后台任务异常: ValueError"
                assert secret not in task_error
                assert secret not in error
            finally:
                _background_tasks.pop(thread_id, None)

    @pytest.mark.asyncio
    async def test_callback_ignores_cancelled_error(self):
        """Done callback does not record error for CancelledError."""
        from backend.api.routes.workflow import _on_task_done

        thread_id = "test_task_cancelled"

        async def _cancel_me():
            raise asyncio.CancelledError()

        mock_row = MagicMock()
        mock_row.status = "running"

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=mock_row),
            patch(_DB_UPDATE, new_callable=AsyncMock) as mock_update,
        ):
            callback = _on_task_done(thread_id)
            task = asyncio.create_task(_cancel_me())
            task.add_done_callback(callback)
            await asyncio.sleep(0.05)

            if mock_update.called:
                call_kwargs = mock_update.call_args
                assert "task_error" not in call_kwargs[1]


class TestStatusToStrStale:
    """Test _status_to_str maps STALE correctly."""

    def test_stale_maps_to_stale_string(self):
        from backend.api.routes._runner import _status_to_str

        assert _status_to_str(WorkflowStatus.STALE) == "stale"

    def test_running_still_maps_to_running(self):
        from backend.api.routes._runner import _status_to_str

        assert _status_to_str(WorkflowStatus.RUNNING) == "running"
