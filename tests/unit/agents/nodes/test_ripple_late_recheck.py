"""Unit tests for ripple_late_recheck_node."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.nodes.ripple_late_recheck import ripple_late_recheck_node
from backend.state.schema import WorkflowPhase


def _state(**overrides):
    """Build a minimal state dict for ripple_late_recheck."""
    base = {
        "session_id": "thread-123",
        "phase": WorkflowPhase.CREATING,
        "reselect_count": 0,
    }
    base.update(overrides)
    return base


def _store_item(value):
    """Build a mock store Item with .value."""
    item = MagicMock()
    item.value = value
    return item


class TestRippleLateRecheckNode:
    """Tests for ripple_late_recheck_node poll / interrupt / fail-open logic."""

    @pytest.fixture
    def mock_store(self):
        store = AsyncMock()
        store.aget = AsyncMock(return_value=None)
        return store

    @pytest.mark.asyncio
    async def test_blocking_mode_passthrough(self, mock_store):
        """ripple_pending=False (blocking mode or already handled) → pass-through, no store read."""
        state = _state(ripple_pending=False)
        result = await ripple_late_recheck_node(state, store=mock_store)
        assert "ripple_prediction" not in result
        assert "ripple_pmf" not in result
        mock_store.aget.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_thread_id_passthrough(self, mock_store):
        """thread_id missing → pass-through, no store read."""
        state = _state(ripple_pending=True)
        state.pop("session_id")
        result = await ripple_late_recheck_node(state, store=mock_store)
        mock_store.aget.assert_not_called()
        assert "ripple_prediction" not in result

    @pytest.mark.asyncio
    async def test_poll_acceptable_writes_prediction(self, mock_store):
        """poll gets acceptable result → writes prediction/pmf, clears pending, no interrupt."""
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
        with patch("backend.agents.nodes.ripple_late_recheck.interrupt") as mock_int:
            result = await ripple_late_recheck_node(state, store=mock_store)
        mock_int.assert_not_called()
        assert result["ripple_pending"] is False
        assert result["ripple_prediction"] == {"viral_probability": 0.8}
        assert result["ripple_pmf"] == {"pmf_score": 0.7}

    @pytest.mark.asyncio
    async def test_poll_suboptimal_under_limit_interrupts(self, mock_store):
        """poll gets suboptimal result + reselect<2 → calls interrupt."""
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
            "backend.agents.nodes.ripple_late_recheck.interrupt",
            return_value={"action": "accept"},
        ) as mock_int:
            result = await ripple_late_recheck_node(state, store=mock_store)
        mock_int.assert_called_once()
        payload = mock_int.call_args.args[0]
        assert payload["gate"] == "ripple"
        assert payload["ripple_summary"]["source"] == "late_recheck"
        assert result["ripple_decision"] == {"action": "accept", "source": "user"}

    @pytest.mark.asyncio
    async def test_poll_suboptimal_at_limit_accepts(self, mock_store):
        """poll gets suboptimal result + reselect>=2 → accepts, no interrupt."""
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
        with patch("backend.agents.nodes.ripple_late_recheck.interrupt") as mock_int:
            result = await ripple_late_recheck_node(state, store=mock_store)
        mock_int.assert_not_called()
        assert result["ripple_pending"] is False
        assert result["ripple_prediction"] == {"viral_probability": 0.1}

    @pytest.mark.asyncio
    async def test_interrupt_reangle_increments_reselect(self, mock_store):
        """poll suboptimal + reangle decision → reselect_count incremented."""
        state = _state(ripple_pending=True, reselect_count=1)
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
            "backend.agents.nodes.ripple_late_recheck.interrupt",
            return_value={"action": "reangle"},
        ) as mock_int:
            result = await ripple_late_recheck_node(state, store=mock_store)
        mock_int.assert_called_once()
        assert result["ripple_decision"] == {"action": "reangle", "source": "user"}
        assert result["reselect_count"] == 2

    @pytest.mark.asyncio
    async def test_poll_timeout_reason_passes_through(self, mock_store):
        """poll gets reason=timeout → write reason, clear pending, pass-through."""
        state = _state(ripple_pending=True)
        mock_store.aget = AsyncMock(
            return_value=_store_item({"ripple_pending": False, "ripple_reason": "timeout"})
        )
        result = await ripple_late_recheck_node(state, store=mock_store)
        assert result["ripple_reason"] == "timeout"
        assert result["ripple_pending"] is False
        assert "ripple_prediction" not in result

    @pytest.mark.asyncio
    async def test_poll_unreachable_reason_passes_through(self, mock_store):
        """poll gets reason=unreachable → write reason, clear pending, pass-through."""
        state = _state(ripple_pending=True)
        mock_store.aget = AsyncMock(
            return_value=_store_item({"ripple_pending": False, "ripple_reason": "unreachable"})
        )
        result = await ripple_late_recheck_node(state, store=mock_store)
        assert result["ripple_reason"] == "unreachable"
        assert result["ripple_pending"] is False

    @pytest.mark.asyncio
    async def test_poll_cap_exceeded_fails_open(self, mock_store):
        """poll never gets a result within cap → fail open (pending reason, no block)."""
        state = _state(ripple_pending=True)
        mock_store.aget = AsyncMock(return_value=None)
        with (
            patch("backend.config.settings.Settings") as mock_settings,
            patch(
                "backend.agents.nodes.ripple_late_recheck.asyncio.sleep", new=AsyncMock()
            ) as mock_sleep,
        ):
            mock_settings.return_value.ripple.late_recheck_timeout = 0
            result = await ripple_late_recheck_node(state, store=mock_store)
        assert result["ripple_pending"] is False
        assert result["ripple_reason"] == "pending"
        assert "ripple_prediction" not in result
        # cap=0 → loop body checks remaining<=0 immediately, no sleep
        mock_sleep.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_eventually_succeeds_after_nones(self, mock_store):
        """poll returns None a few times then a result → writes prediction."""
        state = _state(ripple_pending=True)
        good = _store_item(
            {
                "ripple_pending": False,
                "ripple_prediction": {"viral_probability": 0.9},
                "ripple_pmf": {"pmf_score": 0.8},
            }
        )
        mock_store.aget = AsyncMock(side_effect=[None, None, good])
        with (
            patch("backend.config.settings.Settings") as mock_settings,
            patch("backend.agents.nodes.ripple_late_recheck.asyncio.sleep", new=AsyncMock()),
        ):
            mock_settings.return_value.ripple.late_recheck_timeout = 60
            result = await ripple_late_recheck_node(state, store=mock_store)
        assert result["ripple_pending"] is False
        assert result["ripple_prediction"] == {"viral_probability": 0.9}
        assert mock_store.aget.await_count == 3
