"""Base classes for graph nodes."""

from typing import Any

from langgraph.store.base import BaseStore

from backend.core.error_handling import WorkflowCancelledError
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState


class NodeContext:
    """节点执行上下文"""

    def __init__(self, state: XHSGrowthState, store: BaseStore | None):
        self.state = state
        self.store = store


class NodeResult:
    """节点执行结果封装"""

    def __init__(self, updates: dict[str, Any], agent_name: str = ""):
        self.updates = updates
        self.agent_name = agent_name

    def to_dict(self) -> dict[str, Any]:
        """转换为状态更新字典"""
        result = self.updates.copy()
        if self.agent_name:
            result["current_agent"] = self.agent_name
        return result


def _check_cancelled(state: XHSGrowthState) -> None:
    """Check if workflow is cancelled/paused and raise if so."""
    phase = state.get("phase")
    if phase in (WorkflowPhase.CANCELLED, WorkflowPhase.PAUSED):
        raise WorkflowCancelledError(f"Workflow is {phase}")


def emit_error_event(state: XHSGrowthState, error: Exception) -> None:
    """Emit WORKFLOW_ERROR event."""
    from backend.realtime import EventBusService, EventType

    EventBusService.get_instance().emit(
        EventType.WORKFLOW_ERROR,
        thread_id=state.get("session_id"),
        payload={"error": str(error)},
    )


def node_perf_entry(
    agent: str,
    *,
    started_at: str,
    completed_at: str,
    status: str,
    error: str | None,
    retries: int,
) -> dict[str, Any]:
    """Build one node-level performance_log entry.

    Schema (PRD 节点级指标): {kind:"node", agent, started_at, completed_at,
    duration_seconds, status, error, retries}. `kind` discriminates node
    entries from llm/ripple/human_wait entries in the shared performance_log
    list (readers filter on kind, treating absent kind as node for back-compat
    with the agent_timeline reader's pre-existing schema).
    """
    duration_seconds = _duration_seconds(started_at, completed_at)
    return {
        "kind": "node",
        "agent": agent,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": duration_seconds,
        "status": status,
        "error": error,
        "retries": retries,
    }


def _duration_seconds(started_at: str, completed_at: str) -> float:
    """Seconds between two ISO8601 timestamps; 0.0 on parse failure."""
    from datetime import UTC, datetime

    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(completed_at)
        if start.tzinfo is None:
            start = start.replace(tzinfo=UTC)
        if end.tzinfo is None:
            end = end.replace(tzinfo=UTC)
        return round((end - start).total_seconds(), 4)
    except (ValueError, TypeError):
        return 0.0


def record_human_wait(
    state: dict[str, Any], gate: str, *, now_iso: str | None = None
) -> dict[str, Any]:
    """Build a human_wait performance_log entry for a gate resume.

    `entered_at` is the gate's last preceding node completion — looked up by
    scanning performance_log for the most recent `kind=="node"` entry whose
    `completed_at` precedes the gate interrupt. `resumed_at` is now (or the
    injected `now_iso` for testability). Returns the entry; caller appends it
    to the state-update dict under `performance_log: [entry]` so the
    `_append_list` reducer merges it.
    """
    from datetime import UTC, datetime

    if now_iso is None:
        now_iso = datetime.now(UTC).isoformat()
    perf_log = state.get("performance_log") or []
    entered_at = ""
    for entry in reversed(perf_log):
        if entry.get("kind") in ("node", None) and entry.get("completed_at"):
            entered_at = entry["completed_at"]
            break
    wait_seconds = 0.0
    if entered_at:
        try:
            start = datetime.fromisoformat(entered_at)
            end = datetime.fromisoformat(now_iso)
            if start.tzinfo is None:
                start = start.replace(tzinfo=UTC)
            if end.tzinfo is None:
                end = end.replace(tzinfo=UTC)
            wait_seconds = round((end - start).total_seconds(), 4)
        except (ValueError, TypeError):
            wait_seconds = 0.0
    return {
        "kind": "human_wait",
        "gate": gate,
        "entered_at": entered_at,
        "resumed_at": now_iso,
        "wait_seconds": wait_seconds,
    }
