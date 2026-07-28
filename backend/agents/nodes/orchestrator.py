"""Orchestrator node implementation."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.agents.nodes._base import NodeResult, _check_cancelled
from backend.agents.orchestrator import OrchestratorAgent
from backend.realtime import EventBusService, EventType
from backend.state.schema import XHSGrowthState

_orchestrator = OrchestratorAgent()


async def orchestrator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Execute orchestrator agent and emit phase change event."""
    _check_cancelled(state)
    result = await _orchestrator(state, store=store)

    thread_id = state.get("session_id")
    event_bus = EventBusService.get_instance()

    # Emit workflow started event on first orchestrator run
    if not state.get("current_agent"):
        event_bus.emit(
            EventType.WORKFLOW_STARTED,
            thread_id=thread_id,
            payload={
                "phase": result.get("phase", state.get("phase")),
                "account_id": state.get("account_id"),
                "dry_run": state.get("dry_run", False),
            },
        )
    else:
        # Not the first orchestrator run → this is a continuous-mode loop-back
        # (analyst→orchestrator). Bump cycle_count so should_continue can cap
        # the loop at _MAX_CYCLE_COUNT.
        result["cycle_count"] = state.get("cycle_count", 0) + 1

    # Emit phase change event if phase changed
    old_phase = state.get("phase")
    new_phase = result.get("phase")
    if new_phase and new_phase != old_phase:
        event_bus.emit(
            EventType.WORKFLOW_PHASE_CHANGED,
            thread_id=thread_id,
            payload={
                "old_phase": old_phase,
                "new_phase": new_phase,
                "current_agent": result.get("current_agent", "orchestrator"),
            },
        )

    return NodeResult(result, "orchestrator").to_dict()
