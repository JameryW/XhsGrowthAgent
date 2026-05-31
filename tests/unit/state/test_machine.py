"""Tests for workflow status derivation."""

import pytest
from unittest.mock import MagicMock

from backend.state.machine import WorkflowStatus, derive_status
from backend.state.enums import WorkflowPhase


def make_snapshot(
    values: dict,
    next: list[str] | None = None,
    tasks: list | None = None,
) -> MagicMock:
    """Create a mock StateSnapshot for testing."""
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next or []
    snapshot.tasks = tasks or []
    return snapshot


class TestDeriveStatus:
    """Test derive_status priority order."""

    def test_cancelled_phase_returns_cancelled(self):
        snapshot = make_snapshot({"phase": WorkflowPhase.CANCELLED})
        assert derive_status(snapshot) == WorkflowStatus.CANCELLED

    def test_paused_phase_returns_paused(self):
        snapshot = make_snapshot({"phase": WorkflowPhase.PAUSED})
        assert derive_status(snapshot) == WorkflowStatus.PAUSED

    def test_interrupt_at_review_gate_returns_awaiting_review(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.REVIEWING},
            next=["review_gate"],
            tasks=[{"interrupts": [{}]}],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_REVIEW

    def test_interrupt_at_choice_gate_returns_awaiting_choice(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=["choice_gate"],
            tasks=[{"interrupts": [{}]}],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_CHOICE

    def test_error_in_state_returns_error(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING, "error": "API failed"},
            next=["trend_scout"],
        )
        assert derive_status(snapshot) == WorkflowStatus.ERROR

    def test_completed_phase_returns_completed(self):
        snapshot = make_snapshot({"phase": WorkflowPhase.COMPLETED})
        assert derive_status(snapshot) == WorkflowStatus.COMPLETED

    def test_has_next_nodes_returns_running(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING},
            next=["trend_scout"],
            tasks=[],
        )
        assert derive_status(snapshot) == WorkflowStatus.RUNNING

    def test_no_next_no_interrupt_returns_completed(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.ANALYZING},
            next=[],
            tasks=[],
        )
        assert derive_status(snapshot) == WorkflowStatus.COMPLETED

    def test_error_takes_precedence_over_running(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING, "error": "Failed"},
            next=["content_strategist"],
        )
        assert derive_status(snapshot) == WorkflowStatus.ERROR

    def test_cancelled_takes_precedence_over_error(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CANCELLED, "error": "Some error"},
        )
        assert derive_status(snapshot) == WorkflowStatus.CANCELLED
