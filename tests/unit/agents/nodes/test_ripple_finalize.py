"""Unit tests for ripple_finalize_node."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.nodes.ripple_finalize import ripple_finalize_node
from backend.state.schema import WorkflowPhase


def _state(**overrides):
    """Build a minimal state dict for ripple_finalize."""
    base = {
        "session_id": "thread-123",
        "phase": WorkflowPhase.PLANNING,
        "reselect_count": 0,
    }
    base.update(overrides)
    return base


def _store_item(value):
    """Build a mock store Item with .value."""
    item = MagicMock()
    item.value = value
    return item


class TestRippleFinalizeNode:
    """Tests for ripple_finalize_node store-read and interrupt logic."""

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.aget = AsyncMock(return_value=None)
        store.aput = AsyncMock()
        return store

    @pytest.mark.asyncio
    async def test_blocking_mode_passthrough(self, mock_store):
        """ripple_pending=False (blocking mode) → pass-through, no store read."""
        state = _state(ripple_pending=False)
        result = await ripple_finalize_node(state, store=mock_store)
        assert "ripple_prediction" not in result
        assert "ripple_pmf" not in result
        mock_store.aget.assert_not_called()

    @pytest.mark.asyncio
    async def test_acceptable_result_writes_prediction(self, mock_store):
        """ripple_pending=True + acceptable result → writes prediction/pmf, no interrupt."""
        state = _state(ripple_pending=True)
        mock_store.aget = AsyncMock(
            return_value=_store_item(
                {
                    "ripple_pending": False,
                    "ripple_prediction": {"viral_probability": 0.8},
                    "ripple_pmf": {"pmf_score": 0.7},
                }
            )
        )
        with patch("backend.agents.nodes.ripple_finalize.interrupt") as mock_int:
            result = await ripple_finalize_node(state, store=mock_store)
        mock_int.assert_not_called()
        assert result["ripple_pending"] is False
        assert result["ripple_prediction"] == {"viral_probability": 0.8}
        assert result["ripple_pmf"] == {"pmf_score": 0.7}

    @pytest.mark.asyncio
    async def test_suboptimal_under_limit_interrupts(self, mock_store):
        """ripple_pending=True + suboptimal + reselect<2 → calls interrupt."""
        state = _state(ripple_pending=True, reselect_count=0)
        mock_store.aget = AsyncMock(
            return_value=_store_item(
                {
                    "ripple_pending": False,
                    "ripple_prediction": {"viral_probability": 0.1},
                    "ripple_pmf": {"pmf_score": 0.2},
                }
            )
        )
        with patch(
            "backend.agents.nodes.ripple_finalize.interrupt",
            return_value={"action": "accept"},
        ) as mock_int:
            result = await ripple_finalize_node(state, store=mock_store)
        mock_int.assert_called_once()
        assert result["ripple_decision"] == {"action": "accept", "source": "user"}

    @pytest.mark.asyncio
    async def test_suboptimal_at_limit_accepts(self, mock_store):
        """ripple_pending=True + suboptimal + reselect>=2 → accepts, no interrupt."""
        state = _state(ripple_pending=True, reselect_count=2)
        mock_store.aget = AsyncMock(
            return_value=_store_item(
                {
                    "ripple_pending": False,
                    "ripple_prediction": {"viral_probability": 0.1},
                    "ripple_pmf": {"pmf_score": 0.2},
                }
            )
        )
        with patch("backend.agents.nodes.ripple_finalize.interrupt") as mock_int:
            result = await ripple_finalize_node(state, store=mock_store)
        mock_int.assert_not_called()
        assert result["ripple_pending"] is False

    @pytest.mark.asyncio
    async def test_store_none_keeps_pending(self, mock_store):
        """ripple_pending=True + store None (still running) → keep ripple_pending=True.

        Finalize no longer consumes the pending flag when the store is empty;
        the late-arriving result is recovered by ripple_late_recheck after
        visual_designer. ripple_reason is set to "pending" so downstream can
        tell the prediction is not yet available.
        """
        state = _state(ripple_pending=True)
        mock_store.aget = AsyncMock(return_value=None)
        result = await ripple_finalize_node(state, store=mock_store)
        assert result["ripple_pending"] is True
        assert result["ripple_reason"] == "pending"
        assert "ripple_prediction" not in result

    @pytest.mark.asyncio
    async def test_timeout_reason_passes_through(self, mock_store):
        """ripple_pending=True + reason=timeout → pass-through with ripple_reason."""
        state = _state(ripple_pending=True)
        mock_store.aget = AsyncMock(
            return_value=_store_item({"ripple_pending": False, "ripple_reason": "timeout"})
        )
        result = await ripple_finalize_node(state, store=mock_store)
        assert result["ripple_reason"] == "timeout"
        assert "ripple_prediction" not in result

    @pytest.mark.asyncio
    async def test_missing_thread_id_passthrough(self, mock_store):
        """thread_id missing → pass-through, no store read."""
        state = _state()
        state.pop("session_id")
        result = await ripple_finalize_node(state, store=mock_store)
        mock_store.aget.assert_not_called()
        assert "ripple_prediction" not in result
