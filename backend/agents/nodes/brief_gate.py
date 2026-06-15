"""Brief gate node — pauses for user clarification when brief is vague."""

import logging
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.types import interrupt

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.graph.nodes")


async def brief_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Brief clarification gate — interrupts when brief needs user input.

    If brief_clarification.resolved is True, skip interrupt and proceed.
    Otherwise, interrupt so the user can answer clarification questions or skip.
    """
    _check_cancelled(state)

    clarification = state.get("brief_clarification", {})

    # Already resolved or no clarification needed — proceed without interrupt
    if not clarification or clarification.get("resolved", True):
        logger.debug("Brief clarification resolved or not needed, proceeding")
        return NodeResult({
            "phase": WorkflowPhase.BRIEFING,
        }, "brief_gate").to_dict()

    # Brief needs clarification — interrupt for user input
    logger.info("Brief gate: clarification needed, interrupting for user input")
    decision = interrupt({"type": "brief_clarification", "questions": clarification.get("questions", [])})

    # decision format: {"action": "answer", "answers": {...}} or {"action": "skip"}
    result: dict[str, Any] = {
        "phase": WorkflowPhase.BRIEFING,
        "brief_clarification": {"questions": [], "resolved": True},
    }

    if decision and decision.get("action") == "skip":
        logger.info("Brief gate: user skipped clarification")
    elif decision and decision.get("action") == "answer":
        logger.info("Brief gate: user provided clarification answers")
        # Merge answers into brief_content so downstream agents see them
        answers = decision.get("answers", {})
        if answers:
            brief_content = dict(state.get("brief_content", {}))
            for field, value in answers.items():
                if value is not None and value != "":
                    brief_content[field] = value
            result["brief_content"] = brief_content

    return NodeResult(result, "brief_gate").to_dict()
