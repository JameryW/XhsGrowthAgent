"""Workflow status derivation — single source of truth."""

from __future__ import annotations

from enum import StrEnum

from langgraph.types import StateSnapshot

from backend.state.enums import WorkflowPhase


class WorkflowStatus(StrEnum):
    """Computed workflow status (derived from state, not stored)."""

    RUNNING = "running"
    STALE = "stale"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_CHOICE = "awaiting_choice"
    AWAITING_DRAFT = "awaiting_draft"
    AWAITING_BRIEF = "awaiting_brief"
    AWAITING_RIPPLE_DECISION = "awaiting_ripple_decision"
    AWAITING_BLOGGER_SELECTION = "awaiting_blogger_selection"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


def derive_status(snapshot: StateSnapshot, *, has_active_task: bool = True) -> WorkflowStatus:
    """Derive workflow status from LangGraph state snapshot.

    Priority order (highest to lowest):
    1. Cancelled (phase flag)
    2. Paused (phase flag)
    3. Interrupt at review_gate → awaiting_review
    4. Interrupt at choice_gate → awaiting_choice
    5. Interrupt at draft_gate → awaiting_draft
    6. Error in state → error
    7. Phase is completed → completed
    8. Has next nodes but no active task → stale
    9. Has next nodes with active task → running
    10. No next nodes + no interrupt → completed

    Args:
        snapshot: LangGraph StateSnapshot from graph.aget_state()
        has_active_task: Whether a background asyncio.Task is actively running
            for this workflow. When False, next_nodes without an active task
            indicates a stale/orphaned state rather than genuine running.

    Returns:
        WorkflowStatus enum value
    """
    values = snapshot.values or {}
    phase = values.get("phase")
    next_nodes = snapshot.next or []

    # Check for interrupts — two sources:
    # 1. snapshot.interrupts: non-empty when dynamic interrupt() was called inside a node
    # 2. next_nodes containing gate names: happens with interrupt_before, where
    #    the graph pauses before the node runs and interrupts tuple is empty
    has_interrupt = bool(snapshot.interrupts)
    is_awaiting_gate = has_interrupt or bool(next_nodes)

    # Priority 1: Cancelled
    if phase == WorkflowPhase.CANCELLED:
        return WorkflowStatus.CANCELLED

    # Priority 2: Paused
    if phase == WorkflowPhase.PAUSED:
        return WorkflowStatus.PAUSED

    # Priority 3 & 4: Interrupt at specific gates
    # With interrupt_before: snapshot.interrupts is empty but next_nodes has gate name
    # With dynamic interrupt(): snapshot.interrupts is non-empty
    if is_awaiting_gate:
        if next_nodes:
            if "review_gate" in next_nodes:
                return WorkflowStatus.AWAITING_REVIEW
            if "choice_gate" in next_nodes:
                return WorkflowStatus.AWAITING_CHOICE
            if "draft_gate" in next_nodes:
                return WorkflowStatus.AWAITING_DRAFT
            if "brief_gate" in next_nodes:
                return WorkflowStatus.AWAITING_BRIEF
            if "ripple_gate" in next_nodes:
                return WorkflowStatus.AWAITING_RIPPLE_DECISION
            if "blogger_gate" in next_nodes:
                return WorkflowStatus.AWAITING_BLOGGER_SELECTION
        # Fallback: determine gate type from interrupt value (dynamic interrupt only)
        if has_interrupt:
            gate_type = None
            if snapshot.interrupts:
                interrupt_val = snapshot.interrupts[0].value
                if isinstance(interrupt_val, dict):
                    gate_type = interrupt_val.get("gate")
            if gate_type == "choice":
                return WorkflowStatus.AWAITING_CHOICE
            if gate_type == "review":
                return WorkflowStatus.AWAITING_REVIEW
            if gate_type == "draft":
                return WorkflowStatus.AWAITING_DRAFT
            if gate_type == "ripple":
                return WorkflowStatus.AWAITING_RIPPLE_DECISION
            if gate_type == "blogger":
                return WorkflowStatus.AWAITING_BLOGGER_SELECTION
            if gate_type == "brief_clarification":
                return WorkflowStatus.AWAITING_BRIEF
            # Unknown gate type with interrupt — fall through to remaining checks

    # Priority 6: Error (only when terminal — phase is ERROR or no next nodes)
    # If there are next nodes, the error may be retried, so treat as RUNNING
    if values.get("error") and (phase == WorkflowPhase.ERROR or not next_nodes):
        return WorkflowStatus.ERROR

    # Priority 7: Completed phase
    if phase == WorkflowPhase.COMPLETED:
        return WorkflowStatus.COMPLETED

    # Priority 8: Has next nodes but no active background task → stale
    if next_nodes and not has_active_task:
        return WorkflowStatus.STALE

    # Priority 9: Has next nodes with active task → running
    if next_nodes:
        return WorkflowStatus.RUNNING

    # Priority 10: No next nodes, no interrupt → completed
    return WorkflowStatus.COMPLETED
