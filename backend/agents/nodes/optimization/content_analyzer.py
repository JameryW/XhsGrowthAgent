"""Content analyzer node implementation - analyzes draft vs viral posts gap."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.content_analyzer import ContentAnalyzerAgent
from backend.agents.nodes._base import NodeResult
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_content_analyzer = ContentAnalyzerAgent()


async def content_analyzer_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute content analyzer agent and emit data updated event."""
    result = await _content_analyzer(state, store=store)

    # Emit data updated event for optimization_analysis
    thread_id = state.get("session_id")
    if result.get("optimization_analysis"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={
                "data_type": "optimization_analysis",
                "data": result.get("optimization_analysis"),
            },
        )

    return NodeResult(result, "content_analyzer").to_dict()