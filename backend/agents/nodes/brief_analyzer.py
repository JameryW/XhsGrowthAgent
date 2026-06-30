"""Brief analyzer node — LangGraph node wrapping BriefAnalyzerAgent."""

from __future__ import annotations

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.brief_analyzer import BriefAnalyzerAgent
from backend.agents.nodes._base import _check_cancelled
from backend.state.schema import XHSGrowthState

_agent = BriefAnalyzerAgent()


async def brief_analyzer_node(state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
    """Parse brief text/document into structured BriefContent.

    Sets brief_clarification if brief is too vague (confidence < 0.6),
    which will trigger brief_gate interrupt for user clarification.
    """
    _check_cancelled(state)
    result = await _agent.execute(state, store)
    result["current_agent"] = "brief_analyzer"
    return result


__all__ = ["brief_analyzer_node"]
