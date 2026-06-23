"""Review gate node implementation - human-in-the-loop checkpoint."""

import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def review_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Human-in-the-loop review gate — graph interrupts before this node.

    With interrupt_before, this node only runs on resume. The review decision
    is written to state (human_feedback) by submit_review via aupdate_state
    before ainvoke(None) advances the graph. This node just sets the phase;
    the review_outcome router reads human_feedback.decision to route.
    """
    _check_cancelled(state)

    return NodeResult(
        {
            "phase": WorkflowPhase.REVIEWING,
        },
        "review_gate",
    ).to_dict()
