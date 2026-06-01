"""Review gate node implementation - human-in-the-loop checkpoint."""

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def review_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Human-in-the-loop review gate - graph interrupts before this node.

    With interrupt_before, this node only runs on resume. interrupt(None)
    simply receives the resume value (the review decision).
    """
    _check_cancelled(state)

    # Receive the review decision from Command(resume=decision)
    # decision format: {"action": "approve"} or {"action": "revise", "feedback": "..."}
    decision = interrupt(None)

    result = {
        "human_feedback": decision,
        "phase": WorkflowPhase.REVIEWING,
    }

    return NodeResult(result, "review_gate").to_dict()
