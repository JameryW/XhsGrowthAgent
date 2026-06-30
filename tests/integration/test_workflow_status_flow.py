"""Integration test: full workflow status flow through state transitions.

Tests that derive_status correctly classifies workflow state at each
phase of the lifecycle: start → running → (review/choice/pause/cancel/error) → end.
"""

from unittest.mock import MagicMock

from backend.state.enums import ExecutionMode, WorkflowPhase
from backend.state.machine import WorkflowStatus, derive_status


def make_snapshot(
    values: dict,
    next: list[str] | None = None,
    tasks: list | None = None,
    interrupts: list | None = None,
) -> MagicMock:
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next or []
    snapshot.tasks = tasks or []
    snapshot.interrupts = interrupts or []
    return snapshot


class TestFullWorkflowLifecycle:
    """End-to-end status derivation through a typical workflow lifecycle."""

    def test_single_mode_happy_path(self):
        """Single mode happy path through all phases.

        scouting → planning → creating → reviewing → publishing →
        analyzing → engaging → completed.
        """
        # 1. Start — orchestrator dispatches to trend_scout
        snap = make_snapshot({"phase": WorkflowPhase.SCOUTING}, next=["trend_scout"])
        assert derive_status(snap) == WorkflowStatus.RUNNING

        # 2. Scouting done, planning begins
        snap = make_snapshot({"phase": WorkflowPhase.PLANNING}, next=["content_strategist"])
        assert derive_status(snap) == WorkflowStatus.RUNNING

        # 3. Creating — copywriter → visual_designer
        snap = make_snapshot({"phase": WorkflowPhase.CREATING}, next=["copywriter"])
        assert derive_status(snap) == WorkflowStatus.RUNNING

        # 4. Review gate — interrupt for human
        review_interrupt = MagicMock()
        review_interrupt.value = {"gate": "review"}
        snap = make_snapshot(
            {"phase": WorkflowPhase.REVIEWING},
            next=["review_gate"],
            interrupts=[review_interrupt],
        )
        assert derive_status(snap) == WorkflowStatus.AWAITING_REVIEW

        # 5. After approval — publishing
        snap = make_snapshot({"phase": WorkflowPhase.PUBLISHING}, next=["publisher"])
        assert derive_status(snap) == WorkflowStatus.RUNNING

        # 6. Analyzing
        snap = make_snapshot({"phase": WorkflowPhase.ANALYZING}, next=["analyst"])
        assert derive_status(snap) == WorkflowStatus.RUNNING

        # 7. Engaging (single mode → sets COMPLETED in engagement node)
        snap = make_snapshot(
            {"phase": WorkflowPhase.ENGAGING, "execution_mode": ExecutionMode.SINGLE},
            next=["engagement"],
        )
        assert derive_status(snap) == WorkflowStatus.RUNNING

        # 8. Completed
        snap = make_snapshot({"phase": WorkflowPhase.COMPLETED})
        assert derive_status(snap) == WorkflowStatus.COMPLETED

    def test_continuous_mode_loops_back(self):
        """Continuous mode: after analyzing, routes back to orchestrator."""
        # Analyzing phase with continuous mode
        snap = make_snapshot(
            {"phase": WorkflowPhase.ANALYZING, "execution_mode": ExecutionMode.CONTINUOUS},
            next=["orchestrator"],
        )
        assert derive_status(snap) == WorkflowStatus.RUNNING

    def test_choice_gate_interrupt(self):
        """Optimization choice gate triggers awaiting_choice status."""
        choice_interrupt = MagicMock()
        choice_interrupt.value = {"gate": "choice"}
        snap = make_snapshot(
            {"phase": WorkflowPhase.CREATING},
            next=["choice_gate"],
            interrupts=[choice_interrupt],
        )
        assert derive_status(snap) == WorkflowStatus.AWAITING_CHOICE

    def test_pause_interrupts_running(self):
        """Pausing during scouting changes status from running to paused."""
        # Running
        snap = make_snapshot({"phase": WorkflowPhase.SCOUTING}, next=["trend_scout"])
        assert derive_status(snap) == WorkflowStatus.RUNNING

        # After pause
        snap = make_snapshot({"phase": WorkflowPhase.PAUSED}, next=["trend_scout"])
        assert derive_status(snap) == WorkflowStatus.PAUSED

    def test_cancel_interrupts_running(self):
        """Cancelling during planning changes status to cancelled."""
        snap = make_snapshot({"phase": WorkflowPhase.CANCELLED}, next=["content_strategist"])
        assert derive_status(snap) == WorkflowStatus.CANCELLED

    def test_error_during_scouting_with_next_nodes_returns_running(self):
        """Error during scouting with next nodes → RUNNING (may retry)."""
        snap = make_snapshot(
            {"phase": WorkflowPhase.SCOUTING, "error": "API timeout"},
            next=["trend_scout"],
        )
        assert derive_status(snap) == WorkflowStatus.RUNNING

    def test_error_during_scouting_terminal_returns_error(self):
        """Error during scouting with no next nodes → ERROR (terminal)."""
        snap = make_snapshot(
            {"phase": WorkflowPhase.SCOUTING, "error": "API timeout"},
            next=[],
        )
        assert derive_status(snap) == WorkflowStatus.ERROR

    def test_cancel_takes_priority_over_error(self):
        """Cancelled + error → cancelled wins."""
        snap = make_snapshot(
            {"phase": WorkflowPhase.CANCELLED, "error": "Something went wrong"},
        )
        assert derive_status(snap) == WorkflowStatus.CANCELLED

    def test_pause_takes_priority_over_error(self):
        """Paused + error → paused wins."""
        snap = make_snapshot(
            {"phase": WorkflowPhase.PAUSED, "error": "Something went wrong"},
        )
        assert derive_status(snap) == WorkflowStatus.PAUSED

    def test_review_gate_priority_over_error(self):
        """Interrupt at review_gate → awaiting_review, even if error exists.

        Note: derive_status checks review/choice gates before error,
        because a user should still be able to approve/reject.
        """
        review_interrupt = MagicMock()
        review_interrupt.value = {"gate": "review"}
        snap = make_snapshot(
            {"phase": WorkflowPhase.REVIEWING, "error": "minor warning"},
            next=["review_gate"],
            interrupts=[review_interrupt],
        )
        assert derive_status(snap) == WorkflowStatus.AWAITING_REVIEW


class TestStatusEdgeCases:
    """Edge cases in status derivation."""

    def test_empty_values_defaults_to_completed(self):
        """No phase, no next, no interrupt → completed."""
        snap = make_snapshot({}, next=[])
        assert derive_status(snap) == WorkflowStatus.COMPLETED

    def test_none_values_defaults_to_completed(self):
        """None values → completed."""
        snap = make_snapshot(None, next=[])
        # derive_status uses `values or {}`, so None becomes {}
        snap.values = None
        assert derive_status(snap) == WorkflowStatus.COMPLETED

    def test_interrupt_without_matching_gate(self):
        """Interrupt at unknown gate → falls through to error/running/completed."""
        unknown_interrupt = MagicMock()
        unknown_interrupt.value = {"gate": "unknown"}
        snap = make_snapshot(
            {"phase": WorkflowPhase.SCOUTING},
            next=["unknown_node"],
            interrupts=[unknown_interrupt],
        )
        # No review_gate or choice_gate match, so it falls to phase check
        assert derive_status(snap) == WorkflowStatus.RUNNING

    def test_interrupt_with_empty_next(self):
        """Interrupt but no next nodes → uses interrupt value to determine gate type."""
        review_interrupt = MagicMock()
        review_interrupt.value = {"gate": "review"}
        snap = make_snapshot(
            {"phase": WorkflowPhase.REVIEWING},
            next=[],
            interrupts=[review_interrupt],
        )
        # has_interrupt is True but next is empty, so gate check from next_nodes fails
        # Falls back to interrupt value inspection → gate="review" → awaiting_review
        assert derive_status(snap) == WorkflowStatus.AWAITING_REVIEW

    def test_idle_with_next_runs(self):
        """Idle phase with next nodes → running."""
        snap = make_snapshot({"phase": WorkflowPhase.IDLE}, next=["trend_scout"])
        assert derive_status(snap) == WorkflowStatus.RUNNING

    def test_idle_without_next_completed(self):
        """Idle phase without next nodes → completed."""
        snap = make_snapshot({"phase": WorkflowPhase.IDLE}, next=[])
        assert derive_status(snap) == WorkflowStatus.COMPLETED
