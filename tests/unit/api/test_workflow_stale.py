"""Tests for workflow done callback and stale status handling."""

import asyncio

import pytest

from backend.state.machine import WorkflowStatus


class TestOnTaskDone:
    """Test _on_task_done callback behavior."""

    @pytest.mark.asyncio
    async def test_callback_records_task_done_at(self):
        """Done callback records task_done_at in registry."""
        from backend.api.routes.workflow import _on_task_done, _workflow_registry

        thread_id = "test_thread_done_at"
        _workflow_registry[thread_id] = {"status": "completed"}

        callback = _on_task_done(thread_id)
        task = asyncio.create_task(asyncio.sleep(0))
        task.add_done_callback(callback)
        await asyncio.sleep(0.01)

        assert "task_done_at" in _workflow_registry[thread_id]
        del _workflow_registry[thread_id]

    @pytest.mark.asyncio
    async def test_callback_marks_stale_when_registry_running(self):
        """Done callback marks STALE when registry still shows running."""
        from backend.api.routes.workflow import _on_task_done, _workflow_registry

        thread_id = "test_thread_stale"
        _workflow_registry[thread_id] = {"status": "running"}

        callback = _on_task_done(thread_id)
        task = asyncio.create_task(asyncio.sleep(0))
        task.add_done_callback(callback)
        await asyncio.sleep(0.01)

        assert _workflow_registry[thread_id]["status"] == "stale"
        del _workflow_registry[thread_id]

    @pytest.mark.asyncio
    async def test_callback_records_error_on_exception(self):
        """Done callback records task_error when task raised exception."""
        from backend.api.routes.workflow import _on_task_done, _workflow_registry

        thread_id = "test_task_error"

        async def _fail():
            raise RuntimeError("test failure")

        _workflow_registry[thread_id] = {"status": "running"}

        callback = _on_task_done(thread_id)
        task = asyncio.create_task(_fail())
        task.add_done_callback(callback)
        await asyncio.sleep(0.01)

        assert _workflow_registry[thread_id].get("task_error") == "test failure"
        assert _workflow_registry[thread_id]["status"] == "stale"
        del _workflow_registry[thread_id]

    @pytest.mark.asyncio
    async def test_callback_ignores_cancelled_error(self):
        """Done callback does not record error for CancelledError."""
        from backend.api.routes.workflow import _on_task_done, _workflow_registry

        thread_id = "test_task_cancelled"
        _workflow_registry[thread_id] = {"status": "running"}

        async def _cancel_me():
            raise asyncio.CancelledError()

        callback = _on_task_done(thread_id)
        task = asyncio.create_task(_cancel_me())
        task.add_done_callback(callback)
        await asyncio.sleep(0.01)

        # CancelledError should not set task_error
        assert "task_error" not in _workflow_registry[thread_id]
        # But status should still be stale (task is done, registry was running)
        assert _workflow_registry[thread_id]["status"] == "stale"
        del _workflow_registry[thread_id]


class TestStatusToStrStale:
    """Test _status_to_str maps STALE correctly."""

    def test_stale_maps_to_stale_string(self):
        from backend.api.routes._runner import _status_to_str

        assert _status_to_str(WorkflowStatus.STALE) == "stale"

    def test_running_still_maps_to_running(self):
        from backend.api.routes._runner import _status_to_str

        assert _status_to_str(WorkflowStatus.RUNNING) == "running"