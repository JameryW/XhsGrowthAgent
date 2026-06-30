"""Self-check tests for phase/progress consistency in _run_graph_and_persist.

Validates the fix for the bug where the phase/progress written to DB (read by
list/cache paths) diverged from the phase/progress that /status live-computes
when a workflow pauses at an interrupt gate (blogger_gate / draft_gate / ...).

Root cause: ``final_phase`` was taken from ``graph.ainvoke()``'s return value
(the last executed node's state-update output), which can lag behind the real
interrupt-point phase stored in ``snapshot.values``. The fix makes
``final_phase`` read from ``snapshot.values`` (the same source ``derive_status``
uses), falling back to ``result`` only when the snapshot has no phase.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routes import _runner as runner_module
from backend.state.enums import WorkflowPhase
from backend.state.machine import WorkflowStatus

_POOL_READY = "backend.db.pool.is_pool_ready"
_DB_GET = "backend.db.workflows.get_workflow"
_DB_CREATE = "backend.db.workflows.create_workflow"


def _make_snapshot(values: dict, next_nodes: list[str] | None = None) -> MagicMock:
    """Build a StateSnapshot-like mock with sync attrs (as in integration tests)."""
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next_nodes or []
    snapshot.tasks = []
    snapshot.interrupts = []
    snapshot.metadata = {}
    snapshot.config = {"configurable": {"thread_id": values.get("session_id", "test")}}
    snapshot.created_at = "2026-01-01T00:00:00Z"
    return snapshot


def _make_graph(result: dict, snapshot: MagicMock) -> MagicMock:
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=result)
    graph.aget_state = AsyncMock(return_value=snapshot)
    graph.aupdate_state = AsyncMock()
    return graph


@pytest.fixture(autouse=True)
def _isolate_runner_state():
    """Keep module-level runner registries clean across tests."""
    saved_bg = runner_module._background_tasks.copy()
    saved_status = runner_module._last_status.copy()
    runner_module._background_tasks.clear()
    runner_module._last_status.clear()
    yield
    runner_module._background_tasks.clear()
    runner_module._background_tasks.update(saved_bg)
    runner_module._last_status.clear()
    runner_module._last_status.update(saved_status)


class TestPhaseProgressConsistency:
    """Phase/progress written to DB must come from snapshot.values (the same
    source derive_status uses), not from graph.ainvoke()'s return value."""

    @pytest.mark.asyncio
    async def test_phase_at_gate_uses_snapshot_not_result(self):
        """At blogger_gate, result.phase may still be 'planning' (last node
        output) while snapshot.values.phase is 'creating' (real interrupt state).

        DB must record phase=creating / progress=40 — matching what /status
        live-computes — NOT phase=planning / progress=20 from the stale result.
        This is the exact divergence reported in the bug (DB showed
        planning/20 while /status showed creating/40).
        """
        thread_id = "xhs_test_phase_sync_blogger_001"
        config = {"configurable": {"thread_id": thread_id}}

        # ainvoke returns the LAST NODE's output — phase lagging at 'planning'
        result = {"phase": WorkflowPhase.PLANNING.value, "session_id": thread_id}
        # Real graph state at the interrupt point: phase advanced to 'creating'
        snapshot = _make_snapshot(
            {"phase": WorkflowPhase.CREATING.value, "session_id": thread_id},
            next_nodes=["blogger_gate"],
        )
        graph = _make_graph(result, snapshot)

        captured: dict = {}

        async def _capture_create(row):
            captured["row"] = row
            return row

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=None),
            patch(_DB_CREATE, new_callable=AsyncMock, side_effect=_capture_create),
        ):
            await runner_module._run_graph_and_persist(
                thread_id,
                graph,
                config,
                None,
                source="start",
            )

        assert "row" in captured, "DB create_workflow was not invoked"
        row = captured["row"]

        # Phase from snapshot.values, NOT from result
        assert row.phase == WorkflowPhase.CREATING.value
        assert row.phase != WorkflowPhase.PLANNING.value
        # Progress derived from snapshot phase (40), not result phase (20)
        assert row.progress_percent == 40
        # Status still correctly derived as awaiting blogger selection
        assert row.status == WorkflowStatus.AWAITING_BLOGGER_SELECTION.value

    @pytest.mark.asyncio
    async def test_exception_preserves_native_failure_checkpoint(self):
        """If LangGraph already has a pending failed node, do not overwrite it
        with a fallback aupdate_state. The next resume must use the native
        checkpoint with ainvoke(None).
        """
        thread_id = "xhs_test_native_failure_checkpoint_001"
        config = {"configurable": {"thread_id": thread_id}}

        failed_task = MagicMock()
        failed_task.name = "visual_designer"
        failed_task.error = RuntimeError("NotEnoughCvError")

        snapshot = _make_snapshot(
            {
                "phase": WorkflowPhase.SCOUTING.value,
                "session_id": thread_id,
                "current_agent": "orchestrator",
            },
            next_nodes=["visual_designer"],
        )
        snapshot.tasks = [failed_task]

        graph = MagicMock()
        graph.ainvoke = AsyncMock(side_effect=RuntimeError("NotEnoughCvError"))
        graph.aget_state = AsyncMock(return_value=snapshot)
        graph.aupdate_state = AsyncMock()

        with (
            patch.object(runner_module, "_db_upsert", new_callable=AsyncMock),
            pytest.raises(RuntimeError),
        ):
            await runner_module._run_graph_and_persist(
                thread_id,
                graph,
                config,
                None,
                source="start",
            )

        graph.aupdate_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_progress_consistent_with_phase_at_draft_gate(self):
        """Same consistency check at draft_gate: snapshot phase=creating must
        drive progress=40 regardless of what ainvoke returned."""
        thread_id = "xhs_test_phase_sync_draft_001"
        config = {"configurable": {"thread_id": thread_id}}

        result = {"phase": WorkflowPhase.PLANNING.value, "session_id": thread_id}
        snapshot = _make_snapshot(
            {"phase": WorkflowPhase.CREATING.value, "session_id": thread_id},
            next_nodes=["draft_gate"],
        )
        graph = _make_graph(result, snapshot)

        captured: dict = {}

        async def _capture_create(row):
            captured["row"] = row
            return row

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=None),
            patch(_DB_CREATE, new_callable=AsyncMock, side_effect=_capture_create),
        ):
            await runner_module._run_graph_and_persist(
                thread_id,
                graph,
                config,
                None,
                source="start",
            )

        row = captured["row"]
        assert row.phase == WorkflowPhase.CREATING.value
        assert row.progress_percent == 40
        assert row.status == WorkflowStatus.AWAITING_DRAFT.value

    @pytest.mark.asyncio
    async def test_phase_falls_back_to_result_when_snapshot_has_no_phase(self):
        """When snapshot.values lacks a phase key (edge case), fall back to
        result.phase so we never write 'unknown' unnecessarily."""
        thread_id = "xhs_test_phase_sync_fallback_001"
        config = {"configurable": {"thread_id": thread_id}}

        result = {"phase": WorkflowPhase.SCOUTING.value, "session_id": thread_id}
        # Snapshot has session_id but NO phase key; next=['trend_scout'], no
        # active task -> derive_status returns STALE (non-terminal, no history
        # file written).
        snapshot = _make_snapshot(
            {"session_id": thread_id, "current_agent": "trend_scout"},
            next_nodes=["trend_scout"],
        )
        graph = _make_graph(result, snapshot)

        captured: dict = {}

        async def _capture_create(row):
            captured["row"] = row
            return row

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=None),
            patch(_DB_CREATE, new_callable=AsyncMock, side_effect=_capture_create),
        ):
            await runner_module._run_graph_and_persist(
                thread_id,
                graph,
                config,
                None,
                source="start",
            )

        row = captured["row"]
        # Fallback: phase taken from result since snapshot had none
        assert row.phase == WorkflowPhase.SCOUTING.value
        assert row.progress_percent == 10  # get_progress("scouting")
        assert row.status == WorkflowStatus.STALE.value
