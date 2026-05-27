"""Orchestrator node implementation."""

from typing import Any
from langgraph.store.base import BaseStore

from xhs_growth.agents.nodes._base import NodeResult
from xhs_growth.agents.orchestrator import OrchestratorAgent
from xhs_growth.realtime import EventBusService, EventType
from xhs_growth.state.schema import XHSGrowthState


_orchestrator = OrchestratorAgent()


async def orchestrator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute orchestrator agent and emit phase change event."""
    result = await _orchestrator(state, store=store)

    # Emit phase change event if phase changed
    old_phase = state.get("phase")
    new_phase = result.get("phase")
    if new_phase and new_phase != old_phase:
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_PHASE_CHANGED,
            thread_id=state.get("thread_id"),
            payload={
                "old_phase": old_phase,
                "new_phase": new_phase,
            },
        )

    return NodeResult(result, "orchestrator").to_dict()