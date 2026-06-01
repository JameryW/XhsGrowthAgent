"""Workflow status derivation — single source of truth."""

from __future__ import annotations

from enum import StrEnum

from langgraph.types import StateSnapshot

from backend.state.enums import WorkflowPhase


class WorkflowStatus(StrEnum):
    """Computed workflow status (derived from state, not stored)."""

    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    AWAITING_CHOICE = "awaiting_choice"
    PAUSED = "paused"
    COMPLETED = "completed"
    ERROR = "error"
    CANCELLED = "cancelled"


def derive_status(snapshot: StateSnapshot) -> WorkflowStatus:
    """Derive workflow status from LangGraph state snapshot.

    Priority order (highest to lowest):
    1. Cancelled (phase flag)
    2. Paused (phase flag)
    3. Interrupt at review_gate → awaiting_review
    4. Interrupt at choice_gate → awaiting_choice
    5. Error in state → error
    6. Phase is completed → completed
    7. Has next nodes → running
    8. No next nodes + no interrupt → completed

    Args:
        snapshot: LangGraph StateSnapshot from graph.aget_state()

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
            # Unknown gate type with interrupt — fall through to remaining checks

    # Priority 5: Error (only when terminal — phase is ERROR or no next nodes)
    # If there are next nodes, the error may be retried, so treat as RUNNING
    if values.get("error") and (phase == WorkflowPhase.ERROR or not next_nodes):
        return WorkflowStatus.ERROR

    # Priority 6: Completed phase
    if phase == WorkflowPhase.COMPLETED:
        return WorkflowStatus.COMPLETED

    # Priority 7: Has next nodes (running)
    if next_nodes:
        return WorkflowStatus.RUNNING

    # Priority 8: No next nodes, no interrupt → completed
    return WorkflowStatus.COMPLETED
