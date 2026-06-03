"""Brief gate node — pauses for user clarification when brief is vague."""

import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def brief_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Brief clarification gate — interrupts when brief needs user input.

    If brief_clarification.resolved is True, skip interrupt and proceed.
    Otherwise, interrupt so the user can answer clarification questions.
    Uses interrupt_before pattern (configured in graph.compile()).
    """
    _check_cancelled(state)

    clarification = state.get("brief_clarification", {})

    # Already resolved or no clarification needed — proceed
    if not clarification or clarification.get("resolved", True):
        logger.debug("Brief clarification resolved or not needed, proceeding")
        return NodeResult({
            "phase": WorkflowPhase.BRIEFING,
        }, "brief_gate").to_dict()

    # Brief needs clarification — the interrupt is handled by interrupt_before
    # in graph.compile(), so this code runs after the user resumes
    logger.info("Brief gate: clarification needed, user will be prompted")
    return NodeResult({
        "phase": WorkflowPhase.BRIEFING,
    }, "brief_gate").to_dict()
