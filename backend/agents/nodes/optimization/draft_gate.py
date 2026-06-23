"""Draft gate node implementation - waits for user draft confirmation."""

import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def draft_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Draft confirmation gate — always pauses for user to confirm or edit.

    With interrupt_before, this node only runs on resume after submit_draft
    writes draft_content to state via aupdate_state, then calls ainvoke(None)
    to advance the graph. This node just sets the phase; the draft_content
    in state (written by submit_draft) is used by downstream nodes.
    """
    _check_cancelled(state)

    return NodeResult(
        {
            "phase": WorkflowPhase.CREATING,
        },
        "draft_gate",
    ).to_dict()
