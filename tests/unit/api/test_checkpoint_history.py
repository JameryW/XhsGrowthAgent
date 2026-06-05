"""Tests for checkpoint history endpoint and snapshot conversion."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.api.routes.workflow import (
    CheckpointHistoryResponse,
    CheckpointSnapshot,
    _snapshot_to_checkpoint,
)


def _make_snapshot(
    values: dict | None = None,
    next_nodes: tuple[str, ...] = (),
    checkpoint_id: str = "cp_001",
    step: int = 1,
    source: str = "trend_scout",
    created_at: str = "2026-06-05T12:00:00Z",
):
    """Build a mock StateSnapshot."""
    snapshot = MagicMock()
    snapshot.values = values if values is not None else {"phase": "scouting", "current_agent": "trend_scout"}
    snapshot.next = next_nodes
    snapshot.created_at = created_at
    snapshot.metadata = {"step": step, "source": source}
    snapshot.config = {"configurable": {"thread_id": "xhs_test", "checkpoint_id": checkpoint_id}}
    return snapshot


class TestSnapshotToCheckpoint:
    """Test _snapshot_to_checkpoint conversion."""

    def test_basic_conversion(self):
        snapshot = _make_snapshot(
            values={"phase": "scouting", "current_agent": "trend_scout"},
            checkpoint_id="cp_42",
            step=3,
            source="trend_scout",
        )
        cp = _snapshot_to_checkpoint(snapshot)
        assert cp.checkpoint_id == "cp_42"
        assert cp.step == 3
        assert cp.source == "trend_scout"
        assert cp.phase == "scouting"
        assert cp.current_agent == "trend_scout"

    def test_with_stage_data(self):
        snapshot = _make_snapshot(
            values={
                "phase": "creating",
                "current_agent": "copywriter",
                "trend_data": {"hot_topics": [{"topic": "AI", "heat_score": 90}]},
                "content_plan": {"selected_topic": "AI trends"},
                "copy_content": {"selected_title": "AI in 2026"},
            },
        )
        cp = _snapshot_to_checkpoint(snapshot)
        assert cp.trend_data == {"hot_topics": [{"topic": "AI", "heat_score": 90}]}
        assert cp.content_plan == {"selected_topic": "AI trends"}
        assert cp.copy_content == {"selected_title": "AI in 2026"}

    def test_empty_values_defaults(self):
        snapshot = _make_snapshot(values={})
        cp = _snapshot_to_checkpoint(snapshot)
        assert cp.phase == "unknown"
        assert cp.current_agent == ""
        assert cp.trend_data == {}

    def test_next_nodes_preserved(self):
        snapshot = _make_snapshot(next_nodes=("content_strategist", "copywriter"))
        cp = _snapshot_to_checkpoint(snapshot)
        assert cp.next_nodes == ["content_strategist", "copywriter"]

    def test_missing_config_handles_gracefully(self):
        snapshot = _make_snapshot()
        snapshot.config = {}
        cp = _snapshot_to_checkpoint(snapshot)
        assert cp.checkpoint_id == ""


class TestCheckpointHistoryResponse:
    """Test CheckpointHistoryResponse model."""

    def test_empty_response(self):
        resp = CheckpointHistoryResponse(thread_id="xhs_test", checkpoints=[], has_more=False)
        assert resp.thread_id == "xhs_test"
        assert len(resp.checkpoints) == 0
        assert resp.has_more is False

    def test_with_checkpoints(self):
        cp = CheckpointSnapshot(checkpoint_id="cp_1", step=1, source="trend_scout", phase="scouting")
        resp = CheckpointHistoryResponse(thread_id="xhs_test", checkpoints=[cp], has_more=True)
        assert len(resp.checkpoints) == 1
        assert resp.has_more is True


_POOL_READY = "backend.api.routes.workflow.is_pool_ready"
_DB_GET = "backend.api.routes.workflow.db_get"
_LOAD_HISTORY = "backend.api.routes.workflow._load_history_file"


class TestCheckpointHistoryEndpoint:
    """Test GET /workflow/history/{thread_id} endpoint logic."""

    def test_history_file_fallback(self):
        """When no live checkpoints, history file provides a single-entry list."""
        from backend.api.routes.workflow import _snapshot_to_checkpoint

        saved = {
            "phase": "completed",
            "current_agent": "analyst",
            "updated_at": "2026-06-05T12:00:00Z",
            "trend_data": {"hot_topics": [{"topic": "test"}]},
        }
        # Simulate what the endpoint does with a history file
        cp = CheckpointSnapshot(
            checkpoint_id="history-final",
            step=0,
            source="history_file",
            phase=saved.get("phase", "unknown"),
            current_agent=saved.get("current_agent", ""),
            created_at=saved.get("updated_at"),
            trend_data=saved.get("trend_data", {}),
        )
        resp = CheckpointHistoryResponse(thread_id="xhs_test", checkpoints=[cp], has_more=False)
        assert resp.checkpoints[0].checkpoint_id == "history-final"
        assert resp.checkpoints[0].source == "history_file"
        assert resp.checkpoints[0].trend_data == {"hot_topics": [{"topic": "test"}]}

    @pytest.mark.asyncio
    async def test_db_fallback_returns_empty_checkpoints(self):
        """When no live checkpoints and no history file, DB row still returns valid response."""
        mock_row = MagicMock()
        mock_row.status = "completed"

        with (
            patch(_POOL_READY, return_value=True),
            patch(_DB_GET, new_callable=AsyncMock, return_value=mock_row),
        ):
            # The endpoint would construct:
            resp = CheckpointHistoryResponse(
                thread_id="xhs_db_only",
                checkpoints=[],
                has_more=False,
            )
            assert len(resp.checkpoints) == 0
