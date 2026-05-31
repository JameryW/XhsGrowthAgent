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
    tasks = snapshot.tasks or []

    # Check for interrupts in tasks
    has_interrupt = any(
        task.get("interrupts") for task in tasks if isinstance(task, dict)
    )

    # Priority 1: Cancelled
    if phase == WorkflowPhase.CANCELLED:
        return WorkflowStatus.CANCELLED

    # Priority 2: Paused
    if phase == WorkflowPhase.PAUSED:
        return WorkflowStatus.PAUSED

    # Priority 3 & 4: Interrupt at specific gates
    if has_interrupt and next_nodes:
        if "review_gate" in next_nodes:
            return WorkflowStatus.AWAITING_REVIEW
        if "choice_gate" in next_nodes:
            return WorkflowStatus.AWAITING_CHOICE

    # Priority 5: Error
    if values.get("error"):
        return WorkflowStatus.ERROR

    # Priority 6: Completed phase
    if phase == WorkflowPhase.COMPLETED:
        return WorkflowStatus.COMPLETED

    # Priority 7: Has next nodes (running)
    if next_nodes:
        return WorkflowStatus.RUNNING

    # Priority 8: No next nodes, no interrupt → completed
    return WorkflowStatus.COMPLETED
