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

# Track threads currently executing via synchronous request handlers
# (submit_draft, select_version, etc.) so derive_status knows the graph
# is actively running even without a background asyncio.Task entry.
_active_sync_executions: set[str] = set()

# Background task registry (for cancellation + has_active checks)
_background_tasks: dict[str, asyncio.Task] = {}

# Track last known status per thread to detect transitions
_last_status: dict[str, WorkflowStatus] = {}


async def _db_upsert(thread_id: str, **fields: Any) -> None:
    """Create or update a workflow row in DB. No-ops if DB is unavailable."""
    try:
        from backend.db.pool import is_pool_ready
        if not is_pool_ready():
            return
        from backend.db.workflows import (
            WorkflowRow,
        )
        from backend.db.workflows import (
            create_workflow as db_create,
        )
        from backend.db.workflows import (
            get_workflow as db_get,
        )
        from backend.db.workflows import (
            update_workflow as db_update,
        )
        existing = await db_get(thread_id)
        if existing:
            await db_update(thread_id, **fields)
        else:
            row = WorkflowRow(thread_id=thread_id, **fields)
            await db_create(row)
    except Exception:
        logger.exception("DB upsert failed for %s", thread_id)


def _emit_status_transition(
    new_status: WorkflowStatus,
    thread_id: str,
    snapshot: StateSnapshot | None = None,
) -> None:
    """Emit events when workflow status transitions."""
    old_status = _last_status.get(thread_id)
    if old_status == new_status:
        return
    _last_status[thread_id] = new_status

    bus = EventBusService.get_instance()

    payload: dict[str, Any] = {"status": new_status.value}
    if snapshot is not None:
        values = snapshot.values or {}
        payload["phase"] = values.get("phase")
        payload["current_agent"] = values.get("current_agent")
        payload["next_steps"] = list(snapshot.next) if snapshot.next else []

    if new_status == WorkflowStatus.AWAITING_REVIEW:
        if snapshot is not None:
            values = snapshot.values or {}
            payload["content_plan"] = values.get("content_plan", {})
            payload["copy_content"] = values.get("copy_content", {})
            payload["visual_plan"] = values.get("visual_plan", {})
            payload["version_history"] = values.get("content_versions", [])
        bus.emit(EventType.REVIEW_PENDING, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_CHOICE:
        if snapshot is not None:
            values = snapshot.values or {}
            payload["data"] = {
                "versions": values.get("content_versions", []),
                "draft": values.get("draft_content", {}),
                "analysis": values.get("optimization_analysis", {}),
            }
        else:
            payload["data"] = {}
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_DRAFT:
        if snapshot is not None:
            values = snapshot.values or {}
            payload["copy_content"] = values.get("copy_content", {})
            payload["content_plan"] = values.get("content_plan", {})
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_BRIEF:
        if snapshot is not None:
            values = snapshot.values or {}
            payload["brief_content"] = values.get("brief_content", {})
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_RIPPLE_DECISION:
        if snapshot is not None:
            values = snapshot.values or {}
            payload["ripple_prediction"] = values.get("ripple_prediction", {})
            payload["ripple_pmf"] = values.get("ripple_pmf", {})
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_BLOGGER_SELECTION:
        if snapshot is not None:
            values = snapshot.values or {}
            payload["blogger_candidates"] = values.get("blogger_candidates", [])
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)


def _status_to_str(
    derived: WorkflowStatus,
    has_error: str | None = None,
    final_phase: str = "unknown",
) -> str:
    """Map WorkflowStatus enum to the string stored in DB."""
    mapping = {
        WorkflowStatus.ERROR: "error",
        WorkflowStatus.CANCELLED: "cancelled",
        WorkflowStatus.COMPLETED: "completed",
        WorkflowStatus.AWAITING_REVIEW: "awaiting_review",
        WorkflowStatus.AWAITING_CHOICE: "awaiting_choice",
        WorkflowStatus.AWAITING_DRAFT: "awaiting_draft",
        WorkflowStatus.AWAITING_BRIEF: "awaiting_brief",
        WorkflowStatus.AWAITING_RIPPLE_DECISION: "awaiting_ripple_decision",
        WorkflowStatus.AWAITING_BLOGGER_SELECTION: "awaiting_blogger_selection",
        WorkflowStatus.PAUSED: "paused",
        WorkflowStatus.RUNNING: "running",
        WorkflowStatus.STALE: "stale",
    }
    status = mapping.get(derived)
    if status:
        return status
    if has_error or final_phase in ("scouting", "error"):
        return "error"
    return "completed"


def _get_as_node(state) -> str | None:
    """Determine as_node for aupdate_state from the current state checkpoint.

    LangGraph requires as_node when updating state on a workflow paused at
    an interrupt (multiple nodes in state). Without it, raises
    InvalidUpdateError: Ambiguous update, specify as_node.
    """
    if state.tasks:
        return state.tasks[0].name
    if state.values:
        return state.values.get("_last_node", "orchestrator")
    return "orchestrator"


def _save_history_file(thread_id: str, state_values: dict) -> None:
    """Persist completed workflow result to history file."""
    try:
        import json
        import os
        from pathlib import Path

        history_dir = Path(os.environ.get("XHS_REGISTRY_PATH", ".xhs")) / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        path = history_dir / f"{thread_id}.json"
        path.write_text(json.dumps(state_values, default=str, ensure_ascii=False))
    except Exception:
        logger.exception("Failed to save history for %s", thread_id)


async def _run_graph_and_persist(
    thread_id: str,
    graph: Any,
    config: dict,
    input_data: Any,
    *,
    source: str = "start",
) -> dict:
    """Unified graph execution + status persistence + event emission.

    All graph invocations should go through this function to ensure:
    - Consistent status derivation via derive_status()
    - DB updates
    - Status transition events (awaiting_review, awaiting_choice, etc.)
    - Background task registration
    - Exception handling with graph state phase=ERROR fallback
    """
    is_sync = source not in ("start", "resume")
    if is_sync:
        _active_sync_executions.add(thread_id)

    try:
        result = await graph.ainvoke(input_data, config)

        snapshot = await graph.aget_state(config)
        has_active = (
            (thread_id in _background_tasks and not _background_tasks[thread_id].done())
            or (thread_id in _active_sync_executions)
        )
        derived = derive_status(snapshot, has_active_task=has_active)

        _emit_status_transition(derived, thread_id, snapshot=snapshot)

        final_phase = result.get("phase", "unknown") if result else "unknown"
        has_error = result.get("error") if result else None
        final_status = _status_to_str(derived, has_error, final_phase)

        progress = 100 if final_status == "completed" else 0

        await _db_upsert(
            thread_id,
            phase=final_phase,
            status=final_status,
            progress_percent=progress,
            error=has_error,
            updated_at=datetime.now(UTC).isoformat(),
        )

        if final_status in ("completed", "error"):
            _save_history_file(thread_id, result or {})

        return result or {}

    except asyncio.CancelledError:
        try:
            snapshot = await graph.aget_state(config)
            current_phase = (snapshot.values or {}).get("phase", "unknown")
            if current_phase == "paused":
                await _db_upsert(thread_id, status="paused", phase="paused", error=None)
            else:
                await _db_upsert(
                    thread_id, status="cancelled", phase="cancelled", error="Task cancelled"
                )
        except Exception:
            await _db_upsert(
                thread_id, status="cancelled", phase="cancelled", error="Task cancelled"
            )
        raise

    except Exception as exc:
        logger.exception("Graph execution failed (source=%s, thread=%s)", source, thread_id)
        with contextlib.suppress(Exception):
            snapshot = await graph.aget_state(config)
            await graph.aupdate_state(config, {"phase": "error", "error": str(exc)}, as_node=_get_as_node(snapshot))
        await _db_upsert(
            thread_id,
            status="error",
            phase="error",
            error=str(exc),
            updated_at=datetime.now(UTC).isoformat(),
        )
        raise

    finally:
        if is_sync:
            _active_sync_executions.discard(thread_id)
        _background_tasks.pop(thread_id, None)
