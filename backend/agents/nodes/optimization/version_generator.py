"""Version generator node implementation - generates A/B/C optimized versions."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.agents.version_generator import VersionGeneratorAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_version_generator = VersionGeneratorAgent()


async def version_generator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute version generator agent and emit data updated event."""
    _check_cancelled(state)
    result = await _version_generator(state, store=store)

    # Emit data updated event for content_versions
    thread_id = state.get("session_id")
    if result.get("content_versions"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "content_versions", "data": result.get("content_versions")},
        )

    return NodeResult(result, "version_generator").to_dict()