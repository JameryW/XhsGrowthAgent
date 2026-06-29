"""Tests for workflow status derivation."""

from unittest.mock import MagicMock

from backend.state.enums import WorkflowPhase
from backend.state.machine import WorkflowStatus, derive_status


def make_snapshot(
    values: dict,
    next: list[str] | None = None,
    tasks: list | None = None,
    interrupts: list | None = None,
) -> MagicMock:
    """Create a mock StateSnapshot for testing."""
    snapshot = MagicMock()
    snapshot.values = values
    snapshot.next = next or []
    snapshot.tasks = tasks or []
    snapshot.interrupts = interrupts or []
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
        interrupt_mock = MagicMock()
        interrupt_mock.value = {"gate": "review"}
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.REVIEWING},
            next=["review_gate"],
            interrupts=[interrupt_mock],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_REVIEW

    def test_interrupt_at_choice_gate_returns_awaiting_choice(self):
        interrupt_mock = MagicMock()
        interrupt_mock.value = {"gate": "choice"}
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=["choice_gate"],
            interrupts=[interrupt_mock],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_CHOICE

    def test_error_in_state_returns_error(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING, "error": "API failed"},
            next=[],
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

    def test_error_with_next_nodes_returns_running(self):
        """Error in non-terminal state (has next nodes) → RUNNING (may retry)."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING, "error": "Transient failure"},
            next=["trend_scout"],
        )
        assert derive_status(snapshot) == WorkflowStatus.RUNNING

    def test_error_with_no_next_nodes_returns_error(self):
        """Error in terminal state (no next nodes) → ERROR."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING, "error": "API failed"},
            next=[],
        )
        assert derive_status(snapshot) == WorkflowStatus.ERROR

    def test_error_phase_returns_error(self):
        """Phase == ERROR always returns ERROR, even with next nodes."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.ERROR, "error": "Critical failure"},
            next=["trend_scout"],
        )
        assert derive_status(snapshot) == WorkflowStatus.ERROR

    def test_cancelled_takes_precedence_over_error(self):
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CANCELLED, "error": "Some error"},
        )
        assert derive_status(snapshot) == WorkflowStatus.CANCELLED

    def test_interrupt_before_review_gate_returns_awaiting_review(self):
        """With interrupt_before, snapshot.interrupts is empty but next has review_gate."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.REVIEWING},
            next=["review_gate"],
            interrupts=[],  # interrupt_before produces no Interrupt objects
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_REVIEW

    def test_interrupt_before_choice_gate_returns_awaiting_choice(self):
        """With interrupt_before, snapshot.interrupts is empty but next has choice_gate."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=["choice_gate"],
            interrupts=[],  # interrupt_before produces no Interrupt objects
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_CHOICE

    def test_interrupt_before_draft_gate_returns_awaiting_draft(self):
        """interrupt_before draft_gate → AWAITING_DRAFT."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=["draft_gate"],
            interrupts=[],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_DRAFT

    def test_interrupt_before_brief_gate_returns_awaiting_brief(self):
        """interrupt_before brief_gate → AWAITING_BRIEF."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.BRIEFING},
            next=["brief_gate"],
            interrupts=[],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_BRIEF

    def test_interrupt_before_ripple_gate_returns_awaiting_ripple_decision(self):
        """interrupt_before ripple_gate → AWAITING_RIPPLE_DECISION."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.PLANNING},
            next=["ripple_gate"],
            interrupts=[],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_RIPPLE_DECISION

    def test_interrupt_before_blogger_gate_returns_awaiting_blogger_selection(self):
        """interrupt_before blogger_gate → AWAITING_BLOGGER_SELECTION."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=["blogger_gate"],
            interrupts=[],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_BLOGGER_SELECTION

    def test_dynamic_interrupt_draft_gate(self):
        """Dynamic interrupt with gate=draft → AWAITING_DRAFT."""
        interrupt_mock = MagicMock()
        interrupt_mock.value = {"gate": "draft"}
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=[],
            interrupts=[interrupt_mock],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_DRAFT

    def test_dynamic_interrupt_ripple_gate(self):
        """Dynamic interrupt with gate=ripple → AWAITING_RIPPLE_DECISION."""
        interrupt_mock = MagicMock()
        interrupt_mock.value = {"gate": "ripple"}
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.PLANNING},
            next=[],
            interrupts=[interrupt_mock],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_RIPPLE_DECISION

    def test_dynamic_interrupt_blogger_gate(self):
        """Dynamic interrupt with gate=blogger → AWAITING_BLOGGER_SELECTION."""
        interrupt_mock = MagicMock()
        interrupt_mock.value = {"gate": "blogger"}
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=[],
            interrupts=[interrupt_mock],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_BLOGGER_SELECTION

    def test_dynamic_interrupt_brief_clarification(self):
        """Dynamic interrupt with gate=brief_clarification → AWAITING_BRIEF."""
        interrupt_mock = MagicMock()
        interrupt_mock.value = {"gate": "brief_clarification"}
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.BRIEFING},
            next=[],
            interrupts=[interrupt_mock],
        )
        assert derive_status(snapshot) == WorkflowStatus.AWAITING_BRIEF


class TestDeriveStatusStale:
    """Test STALE status detection with has_active_task parameter."""

    def test_next_nodes_no_active_task_returns_stale(self):
        """Next nodes present but no active background task → STALE."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING},
            next=["trend_scout"],
        )
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.STALE

    def test_next_nodes_with_active_task_returns_running(self):
        """Next nodes present with active background task → RUNNING."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING},
            next=["trend_scout"],
        )
        assert derive_status(snapshot, has_active_task=True) == WorkflowStatus.RUNNING

    def test_next_nodes_default_has_active_task_is_running(self):
        """Default has_active_task=True means next_nodes → RUNNING."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING},
            next=["trend_scout"],
        )
        assert derive_status(snapshot) == WorkflowStatus.RUNNING

    def test_no_next_nodes_no_active_task_returns_completed(self):
        """No next nodes + no active task → completed (not stale)."""
        snapshot = make_snapshot({"phase": WorkflowPhase.COMPLETED})
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.COMPLETED

    def test_stale_does_not_override_interrupt_gates(self):
        """Interrupt gates take priority over stale detection."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.REVIEWING},
            next=["review_gate"],
            interrupts=[],
        )
        # Even with no active task, review gate → awaiting_review
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.AWAITING_REVIEW

    def test_stale_does_not_override_error(self):
        """Error phase takes priority over stale detection."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.ERROR, "error": "Critical"},
            next=["trend_scout"],
        )
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.ERROR

    def test_stale_does_not_override_paused(self):
        """Paused takes priority over stale detection."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.PAUSED},
            next=["trend_scout"],
        )
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.PAUSED

    def test_stale_does_not_override_cancelled(self):
        """Cancelled takes priority over stale detection."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CANCELLED},
            next=["trend_scout"],
        )
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.CANCELLED

    def test_stale_does_not_override_draft_gate(self):
        """Draft gate takes priority over stale detection."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=["draft_gate"],
            interrupts=[],
        )
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.AWAITING_DRAFT

    def test_stale_does_not_override_brief_gate(self):
        """Brief gate takes priority over stale detection."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.BRIEFING},
            next=["brief_gate"],
            interrupts=[],
        )
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.AWAITING_BRIEF

    def test_stale_does_not_override_ripple_gate(self):
        """Ripple gate takes priority over stale detection."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.PLANNING},
            next=["ripple_gate"],
            interrupts=[],
        )
        result = derive_status(snapshot, has_active_task=False)
        assert result == WorkflowStatus.AWAITING_RIPPLE_DECISION

    def test_stale_does_not_override_blogger_gate(self):
        """Blogger gate takes priority over stale detection."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.CREATING},
            next=["blogger_gate"],
            interrupts=[],
        )
        result = derive_status(snapshot, has_active_task=False)
        assert result == WorkflowStatus.AWAITING_BLOGGER_SELECTION

    def test_stale_with_non_terminal_error_returns_stale(self):
        """Non-terminal error (next nodes present) with no active task → STALE."""
        snapshot = make_snapshot(
            values={"phase": WorkflowPhase.SCOUTING, "error": "Transient"},
            next=["trend_scout"],
        )
        assert derive_status(snapshot, has_active_task=False) == WorkflowStatus.STALE
