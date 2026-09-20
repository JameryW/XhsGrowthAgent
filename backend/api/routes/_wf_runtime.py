"""Workflow runtime layer: task registry, resume/takeover plumbing, orphan checks.

Everything here answers a question about *execution*: is a task live in
this process, what does a resume have to replay, which node carries the
state update.  P2b moved the ownership question onto the execution lease
(see ``docs/execution-plane.md``); the guards that ask "should *this
process* start a task" deliberately still read the process-local
registries, and ``tests/unit/api/test_serialization_guards_stay_local.py``
pins that.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import Request

from backend.api.errors import ValidationError
from backend.api.responses import ApiResponse, success
from backend.api.routes import _runner
from backend.api.routes._runner import _db_upsert, _get_as_node, _task_has_error
from backend.db.pool import is_pool_ready
from backend.db.workflows import get_workflow as db_get
from backend.db.workflows import update_workflow as db_update
from backend.state.enums import ContentStatus, WorkflowPhase
from backend.state.machine import WorkflowStatus

logger = logging.getLogger(__name__)


# ── In-memory tracking (not persisted — rebuilt on restart from DB) ──
# Use _runner._background_tasks as the single task registry so that
# _run_graph_and_persist can correctly determine has_active_task.
# The local _last_status dict tracks status transitions for this module only.
_last_status: dict[str, WorkflowStatus] = {}


def _get_state_update_node_without_advancing(state: Any) -> str | None:
    """Pick an as_node that updates state without consuming the pending gate."""

    values = state.values if isinstance(state.values, dict) else {}
    next_nodes = set(getattr(state, "next", []) or [])
    for key in ("current_agent", "_last_node"):
        node = values.get(key)
        if isinstance(node, str) and node and node not in next_nodes:
            return node
    fallback = _get_as_node(state)
    if fallback in next_nodes:
        return "orchestrator"
    return fallback


def _on_task_done(thread_id: str) -> Callable[[asyncio.Task[None]], None]:
    """Background task done callback — update DB with task_done_at / stale status."""

    def callback(task: asyncio.Task[None]) -> None:
        # Skip DB update if this task was replaced by a newer one
        # (e.g. _start_resume_task cancelled this task and started a new one)
        if _runner._background_tasks.get(thread_id) is not task:
            return

        task_error = None
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Background task for %s failed: %s", thread_id, e)
            # ponytail: raw str(e) flows to the DB `error`/`task_error` columns
            # → /list + /status JSON → frontend UI; keep the full detail in the
            # logger only. Preserve the type name for ops diagnosability (same
            # pattern as the error-log-type-name series #471/#474) without
            # leaking the message/paths.
            task_error = f"后台任务异常: {type(e).__name__}"

        # Best-effort DB update via ensure_future (can't await in a sync callback,
        # and run_until_complete would crash inside an already-running event loop).
        try:
            updates: dict[str, Any] = {"task_done_at": datetime.now(UTC).isoformat()}
            if task_error:
                updates["task_error"] = task_error

            async def _do_update() -> None:
                if not is_pool_ready():
                    return
                existing = await db_get(thread_id)
                if not existing:
                    return
                if task_error:
                    # Task failed — mark as error (not stale)
                    updates["status"] = "error"
                    updates["error"] = task_error
                elif existing.status == "running":
                    # Task completed normally but DB still running → stale
                    updates["status"] = "stale"
                await db_update(thread_id, **updates)

            asyncio.ensure_future(_do_update())
        except Exception:
            logger.exception("Failed to update DB in task_done callback for %s", thread_id)

    return callback


def _resume_phase_for_next_nodes(
    next_nodes: tuple[str, ...],
    fallback: str | WorkflowPhase,
) -> str | WorkflowPhase:
    """Infer a non-terminal phase when retrying from a checkpointed next node."""
    phase_by_node: dict[str, WorkflowPhase] = {
        "orchestrator": WorkflowPhase.SCOUTING,
        "trend_scout": WorkflowPhase.SCOUTING,
        "content_strategist": WorkflowPhase.PLANNING,
        "ripple_gate": WorkflowPhase.PLANNING,
        "brief_analyzer": WorkflowPhase.BRIEFING,
        "brief_gate": WorkflowPhase.BRIEFING,
        "copywriter": WorkflowPhase.CREATING,
        "draft_gate": WorkflowPhase.CREATING,
        "viral_matcher": WorkflowPhase.CREATING,
        "blogger_scout": WorkflowPhase.CREATING,
        "blogger_gate": WorkflowPhase.CREATING,
        "shooting_planner": WorkflowPhase.CREATING,
        "content_analyzer": WorkflowPhase.CREATING,
        "version_generator": WorkflowPhase.CREATING,
        "choice_gate": WorkflowPhase.CREATING,
        "visual_designer": WorkflowPhase.CREATING,
        "review_gate": WorkflowPhase.REVIEWING,
        "revise_content": WorkflowPhase.REVIEWING,
        "publisher": WorkflowPhase.PUBLISHING,
        "analyst": WorkflowPhase.ANALYZING,
        # Removed workflow node: old checkpoints must be reported terminal,
        # never resumed into automatic comment/DM interaction.
        "engagement": WorkflowPhase.COMPLETED,
    }
    for node in next_nodes:
        if node in phase_by_node:
            return phase_by_node[node]
    return fallback


# ── P0-W5 continuation channel: evaluator fail-closed pause ──────────────────
#
# The evaluator gate is fail-closed: a degraded evaluation or a compliance
# rejection ends the run with phase=PAUSED + pause_reason=evaluator_fail_closed
# (backend/graph/routers.py::evaluator_requires_human is the single source of
# truth shared by node and router). Such a thread must NEVER fall through to the
# legacy restart below — ainvoke-from-scouting would re-run the whole creation
# pipeline. A human decision continues it in place instead:
#
#   approve → evaluation_result is patched to APPROVED and the gate is replayed
#             via aupdate_state(as_node="evaluator_gate"), so the conditional
#             edge routes straight to the publisher (verified empirically in
#             tests/integration/test_evaluator_pause_resume.py). Compliance
#             blocks are human-overridable BY DESIGN — fail-closed means
#             "requires a human", not "forbidden".
#   revise   → patched to NEEDS_REVISION with a FRESH revision budget
#             (revision_count reset to 0), so the human-initiated cycle gets a
#             full Settings().workflow.max_revision_count allowance instead of
#             instantly re-triggering the fail-closed cap.
#
# Both paths keep the original judge output (score/dimensions/summary) so the
# audit trail and the training samples still show what the panel actually said;
# only the verdict fields the shared predicate reads are overridden, and the
# decision is stamped into ``human_override`` for attribution.

HUMAN_DECISIONS = ("approve", "revise")


def build_evaluator_pause_resume_updates(values: dict[str, Any], decision: str) -> dict[str, Any]:
    """State patch that carries a thread past an evaluator fail-closed pause.

    Written with ``as_node="evaluator_gate"`` so the gate's own conditional edge
    decides what runs next; the patched result must make
    ``evaluator_requires_human`` False (asserted against the real predicate in
    the tests).
    """
    evaluation = dict(values.get("evaluation_result") or {})
    dimensions = evaluation.get("dimensions")
    if isinstance(dimensions, list):
        # Clear stale blocking evidence: the human has seen it and decided. The
        # next gate pass re-derives its own verdict from a fresh panel run.
        evaluation["dimensions"] = [
            {**d, "is_blocking": False} if isinstance(d, dict) else d for d in dimensions
        ]
    evaluation["degraded"] = False
    evaluation["failed_dimensions"] = []
    evaluation["human_override"] = {
        "decision": decision,
        "source": "resume_api",
        "at": datetime.now(UTC).isoformat(),
    }

    if decision == "approve":
        evaluation["decision"] = ContentStatus.APPROVED.value
        evaluation["status"] = "human_approved"
        phase: WorkflowPhase = WorkflowPhase.PUBLISHING
    else:
        evaluation["decision"] = ContentStatus.NEEDS_REVISION.value
        evaluation["status"] = "human_revision_requested"
        hints = [h for h in (evaluation.get("revision_hints") or []) if isinstance(h, str)]
        evaluation["revision_hints"] = hints or [
            "人工复核未放行：请根据评估意见重写标题/正文/视觉方案后再次送审"
        ]
        phase = WorkflowPhase.REVIEWING

    updates: dict[str, Any] = {
        "evaluation_result": evaluation,
        "pause_reason": None,
        "phase": phase,
        "error": None,
    }
    if decision == "revise":
        # Fresh revision budget for the human-initiated cycle (see header).
        updates["revision_count"] = 0
    return updates


async def _resume_past_evaluator_pause(
    thread_id: str,
    request: Request,
    graph: Any,
    config: dict[str, Any],
    state: Any,
) -> ApiResponse[Any]:
    """Handle /resume for a thread the evaluator parked. Always returns or 4xx.

    An explicit human_decision is mandatory here: silently continuing would
    either re-run the whole pipeline (legacy path) or auto-publish past a
    compliance block, which is exactly what P0-W5 forbids.
    """
    body: dict[str, Any] = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    decision = str(body.get("human_decision") or "").strip().lower()
    if decision not in HUMAN_DECISIONS:
        raise ValidationError(
            "human_decision",
            "该工作流停在评估质量门（evaluator_fail_closed），必须由人工显式决定如何继续："
            '请求体需带 {"human_decision": "approve"}（放行发布）或 '
            '"revise"（退回修订并给出新的修订额度）。'
            "未提供决定时不会重跑创作流水线，也不会自动发布。",
        )

    updates = build_evaluator_pause_resume_updates(state.values or {}, decision)
    await graph.aupdate_state(config, updates, as_node="evaluator_gate")
    phase = updates["phase"]
    await _start_resume_task(thread_id, graph, config, phase)
    logger.info(
        "Evaluator fail-closed pause continued by human decision=%s for %s (phase=%s)",
        decision,
        thread_id,
        phase,
    )
    return success(
        data={
            "thread_id": thread_id,
            "status": "running",
            "phase": phase,
            "human_decision": decision,
            "continued_from": "evaluator_gate",
            "message": (
                "人工已放行评估质量门，继续发布（不会重跑创作链路）"
                if decision == "approve"
                else "人工选择修订：已退回内容修订环节，并授予新的修订额度"
            ),
        }
    )


def _task_name(task: Any) -> str | None:
    name = getattr(task, "name", None)
    return name if isinstance(name, str) and name else None


def _resume_nodes_from_tasks(tasks: Any) -> tuple[str, ...]:
    named_tasks = tuple(name for task in (tasks or ()) if (name := _task_name(task)))
    failed_tasks = tuple(
        name for task in (tasks or ()) if (name := _task_name(task)) and _task_has_error(task)
    )
    return failed_tasks or named_tasks


def _persisted_status(phase: str | WorkflowPhase, error: str | None = None) -> str:
    """Derive status for persisted records without live snapshot."""
    if phase == WorkflowPhase.ERROR or error:
        return WorkflowStatus.ERROR.value
    if phase == WorkflowPhase.CANCELLED:
        return WorkflowStatus.CANCELLED.value
    if phase == WorkflowPhase.PAUSED:
        return WorkflowStatus.PAUSED.value
    if phase == WorkflowPhase.COMPLETED:
        return WorkflowStatus.COMPLETED.value
    return WorkflowStatus.RUNNING.value


async def _is_orphan_running(thread_id: str, db_status: str) -> bool:
    """Detect orphans: DB says running but nobody holds the lease.

    After deploy/restart the process that held the lease is gone and nothing
    renews it, so the row goes silent and then expires. This asks about
    ownership rather than about this process's task registry: "nobody is
    running it" is a claim about the workflow, and a process that never had
    the task cannot make it. Reuses STALE semantics via derive_status; does
    not mutate DB.
    """
    if db_status != WorkflowStatus.RUNNING.value:
        return False
    return not await _runner.has_active_execution(thread_id)


async def _start_resume_task(
    thread_id: str,
    graph: Any,
    config: dict[str, Any],
    phase: str | WorkflowPhase,
    *,
    input_data: Any = None,
) -> None:
    """Mark a workflow running and resume graph execution in the background.

    input_data: passed as the graph ainvoke input. None = native resume from
    checkpoint (the default). Pass a Command(goto=...) to retry a specific node.
    """
    # Cancel any still-running task for this thread to prevent conflicting state updates
    existing_task = _runner._background_tasks.get(thread_id)
    if existing_task and not existing_task.done():
        existing_task.cancel()

    # The slot above holds one task per thread, so a repair path that stays out
    # of it on purpose is invisible there -- and the lease cannot stand in: a
    # second holder in this process is granted rather than refused, because the
    # row's owner_id identifies the process and not the task
    # (backend/db/execution_leases.py:301, backend/db/execution_leases.py:384).
    # A detached task is therefore reachable only through its own registry, and
    # that cancel has to WAIT -- its teardown releases the very row we are about
    # to take. See cancel_detached_and_wait and docs/execution-plane.md §7.1.
    await _runner.cancel_detached_and_wait(thread_id)

    await _db_upsert(
        thread_id,
        status="running",
        phase=str(phase),
        error=None,
    )

    async def _resume_async() -> None:
        await _runner._run_graph_and_persist(
            thread_id,
            graph,
            config,
            input_data,
            source="resume",
        )

    task = asyncio.create_task(_resume_async())
    task.add_done_callback(_on_task_done(thread_id))
    _runner._background_tasks[thread_id] = task


def _failed_node(state: Any) -> str | None:
    """Best-effort name of the node to re-run on error/stale retry.

    Why this exists: _get_as_node picks state.tasks[0], which on an error
    checkpoint is often an earlier *succeeded* node (e.g. orchestrator).
    Resuming as_node=that advances to its successors and re-runs the whole
    downstream chain — the retry/stale loop (scouting → content_strategist →
    30min Ripple). We instead jump Command(goto=failed_node) to re-run only it.

    Signal priority (none is universally reliable across LangGraph versions /
    entry paths, so we try each):
      1. state.tasks entry with a non-empty .error  (the failed task itself)
      2. state.next                                   (failed task stays pending
                                                         per LangGraph _loop.py)
      3. state.values["current_agent"]                (last node that ran; a
                                                         fallback only — on a
                                                         raised error __call__
                                                         never sets current_agent
                                                         for the failed node)
    Returns None when no signal fires; caller falls back to the as_node path.
    """
    for t in state.tasks or ():
        if getattr(t, "error", None) and getattr(t, "name", None):
            return cast(str, t.name)
    for node in state.next or ():
        if node:
            return cast(str, node)
    values = state.values or {}
    agent = values.get("current_agent")
    if agent and agent != "unknown":
        return cast(str, agent)
    return None


def _last_success_node(state: Any) -> str | None:
    """Name of the most recently completed (non-error) named task in state.tasks.

    Used by /recover strategy=retry_from_last_success: we Command(goto=) this
    node to re-run it and everything downstream. We scan state.tasks in order
    and pick the last named task whose .error is empty — that's the most
    recent success before the failure.
    """
    last_success: str | None = None
    for task in state.tasks or ():
        name = _task_name(task)
        if not name:
            continue
        if _task_has_error(task):
            continue
        last_success = name
    return last_success
