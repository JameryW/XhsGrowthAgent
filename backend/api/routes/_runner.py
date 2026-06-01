"""Shared graph execution runner — unified _run_graph_and_persist for all route entry points."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, datetime
from typing import Any

from langgraph.types import StateSnapshot

from backend.realtime import EventBusService
from backend.realtime.events import EventType
from backend.state.machine import WorkflowStatus, derive_status

logger = logging.getLogger("xhs_growth.api.runner")

# These are set by the importing module (workflow.py) so the runner can access
# the shared registry / persistence helpers without circular imports.
_workflow_registry: dict[str, dict] = {}
_background_tasks: dict[str, asyncio.Task] = {}
_last_status: dict[str, WorkflowStatus] = {}


def bind_registry(
    registry: dict[str, dict],
    background_tasks: dict[str, asyncio.Task],
    last_status: dict[str, WorkflowStatus],
) -> None:
    """Bind the shared mutable dicts from workflow.py into this module.

    Must be called once at module import time (workflow.py does this at the
    bottom of its module body).
    """
    global _workflow_registry, _background_tasks, _last_status
    _workflow_registry = registry
    _background_tasks = background_tasks
    _last_status = last_status


def _save_registry() -> None:
    """Persist workflow registry — delegates to workflow.py's _save_registry.

    This is a thin wrapper; the actual implementation is monkey-patched by
    workflow.py after bind_registry() so we don't duplicate the file I/O logic.
    """
    _save_registry_fn()


# Placeholder — overwritten by workflow.py after bind_registry
_save_registry_fn = lambda: None  # noqa: E731


def _save_workflow_result(thread_id: str, state_values: dict) -> None:
    """Persist completed workflow result — delegates to workflow.py."""
    _save_workflow_result_fn(thread_id, state_values)


# Placeholder — overwritten by workflow.py after bind_registry
_save_workflow_result_fn = lambda tid, sv: None  # noqa: E731


def _emit_status_transition(
    new_status: WorkflowStatus,
    thread_id: str,
    snapshot: StateSnapshot | None = None,
) -> None:
    """Emit events when workflow status transitions.

    Enhanced to accept an optional snapshot for richer payloads (prepared for
    Fix 4 — the actual payload enrichment will be done there, but the
    signature is ready now).
    """
    old_status = _last_status.get(thread_id)
    if old_status == new_status:
        return  # No transition, skip
    _last_status[thread_id] = new_status

    bus = EventBusService.get_instance()

    # Build payload — snapshot enrichment placeholder
    payload: dict[str, Any] = {}
    if snapshot is not None:
        values = snapshot.values or {}
        payload["phase"] = values.get("phase")
        payload["current_agent"] = values.get("current_agent")

    if new_status == WorkflowStatus.AWAITING_REVIEW:
        # Enrich payload with content data so frontend can display review UI
        if snapshot is not None:
            values = snapshot.values or {}
            payload["content_plan"] = values.get("content_plan", {})
            payload["copy_content"] = values.get("copy_content", {})
            payload["visual_plan"] = values.get("visual_plan", {})
            payload["version_history"] = values.get("content_versions", [])
        bus.emit(
            EventType.REVIEW_PENDING,
            thread_id=thread_id,
            payload=payload,
        )
    elif new_status == WorkflowStatus.AWAITING_CHOICE:
        # Enrich payload with versions/draft/analysis for choice UI
        if snapshot is not None:
            values = snapshot.values or {}
            payload["data"] = {
                "versions": values.get("content_versions", []),
                "draft": values.get("draft_content", {}),
                "analysis": values.get("optimization_analysis", {}),
            }
        else:
            payload["data"] = {}
        bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload=payload,
        )


def _status_to_str(
    derived: WorkflowStatus,
    has_error: str | None = None,
    final_phase: str = "unknown",
) -> str:
    """Map WorkflowStatus enum to the string stored in the registry."""
    mapping = {
        WorkflowStatus.ERROR: "error",
        WorkflowStatus.CANCELLED: "cancelled",
        WorkflowStatus.COMPLETED: "completed",
        WorkflowStatus.AWAITING_REVIEW: "awaiting_review",
        WorkflowStatus.AWAITING_CHOICE: "awaiting_choice",
        WorkflowStatus.PAUSED: "paused",
        WorkflowStatus.RUNNING: "running",
    }
    status = mapping.get(derived)
    if status:
        return status
    # Fallback: phase stuck at early stage with error = premature termination
    if has_error or final_phase in ("scouting", "error"):
        return "error"
    return "completed"


async def _run_graph_and_persist(
    thread_id: str,
    graph: Any,
    config: dict,
    input_data: Any,  # initial_state dict, None (for resume), or Command
    *,
    source: str = "start",  # for logging: "start", "resume", "review", "select"
) -> dict:
    """Unified graph execution + status persistence + event emission.

    All graph invocations should go through this function to ensure:
    - Consistent status derivation via derive_status()
    - Registry/history updates
    - Status transition events (awaiting_review, awaiting_choice, etc.)
    - Background task registration
    - Exception handling with graph state phase=ERROR fallback
    """
    try:
        result = await graph.ainvoke(input_data, config)

        # Derive status from snapshot for consistent results
        snapshot = await graph.aget_state(config)
        derived = derive_status(snapshot)

        # Emit status transition events (e.g. awaiting_review, awaiting_choice)
        _emit_status_transition(derived, thread_id, snapshot=snapshot)

        final_phase = result.get("phase", "unknown") if result else "unknown"
        has_error = result.get("error") if result else None
        final_status = _status_to_str(derived, has_error, final_phase)

        progress = 100 if final_status == "completed" else 0

        _workflow_registry[thread_id]["phase"] = final_phase
        _workflow_registry[thread_id]["status"] = final_status
        _workflow_registry[thread_id]["progress_percent"] = progress
        _workflow_registry[thread_id]["error"] = has_error
        _workflow_registry[thread_id]["updated_at"] = datetime.now(UTC).isoformat()
        _save_registry()

        if final_status in ("completed", "error"):
            _save_workflow_result(thread_id, result or {})

        return result or {}

    except asyncio.CancelledError:
        # Check current phase — if paused, keep paused (not cancelled)
        try:
            snapshot = await graph.aget_state(config)
            current_phase = (snapshot.values or {}).get("phase", "unknown")
            if current_phase == "paused":
                _workflow_registry[thread_id]["status"] = "paused"
                _workflow_registry[thread_id]["error"] = None
            else:
                _workflow_registry[thread_id]["status"] = "cancelled"
                _workflow_registry[thread_id]["error"] = "Task cancelled"
        except Exception:
            _workflow_registry[thread_id]["status"] = "cancelled"
            _workflow_registry[thread_id]["error"] = "Task cancelled"
        _save_registry()
        raise

    except Exception as exc:
        logger.exception("Graph execution failed (source=%s, thread=%s)", source, thread_id)
        # Write error to graph state so derive_status picks it up
        with contextlib.suppress(Exception):
            await graph.aupdate_state(config, {"phase": "error", "error": str(exc)})
        _workflow_registry[thread_id]["status"] = "error"
        _workflow_registry[thread_id]["error"] = str(exc)
        _workflow_registry[thread_id]["updated_at"] = datetime.now(UTC).isoformat()
        _save_registry()
        raise

    finally:
        _background_tasks.pop(thread_id, None)
