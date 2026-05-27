"""Copywriter node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.agents.copywriter import CopywriterAgent
from xhs_growth.realtime import EventBusService, EventType
from xhs_growth.state.schema import XHSGrowthState


_copywriter = CopywriterAgent()


async def copywriter_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute copywriter agent and emit data updated event."""
    result = await _copywriter(state, store=store)

    # Emit data updated event for copy_content
    thread_id = state.get("thread_id")
    if result.get("copy_content"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "copy_content", "data": result.get("copy_content")},
        )

    return NodeResult(result, "copywriter").to_dict()