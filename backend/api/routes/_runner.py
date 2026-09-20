"""Shared graph execution runner — unified _run_graph_and_persist for all route entry points."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # StateSnapshot is annotation-only; importing langgraph.types at module load
    # costs ~600ms (pulls langgraph.graph.state). Deferred — resolved only when
    # type checkers need it, never at runtime.
    from langgraph.store.base import BaseStore
    from langgraph.types import StateSnapshot

    from backend.db.execution_leases import AcquireOutcome, RenewOutcome
    from backend.db.workflows import WorkflowRow

from backend.realtime import EventBusService
from backend.realtime.events import EventType
from backend.state.artifacts import resolve_state
from backend.state.hydration import pick, realtime_view
from backend.state.machine import WorkflowStatus, derive_status

logger = logging.getLogger("xhs_growth.api.runner")

# ponytail: in-process cache of last serialized history per thread.
# /status polls completed workflows every 5s and would otherwise re-dump the
# (potentially MB-scale) full state to disk on every poll. Completed state is
# immutable, so a content-equal skip is safe. Process-local; if throughput ever
# needs cross-process dedup, move to file stat comparison.
_LAST_HISTORY_WRITE: dict[str, str] = {}

# Track threads currently executing via synchronous request handlers
_active_sync_executions: set[str] = set()

# Background task registry (for cancellation + has_active checks)
# In-process runtime cache only; DB is index/summary; checkpoint is truth source.
# Cleared on process restart — DB "running" rows with no matching task here are
# restart orphans, detected lazily in /list and /status (no startup scan).
_background_tasks: dict[str, asyncio.Task[Any]] = {}

# Track last known status per thread to detect transitions
_last_status: dict[str, WorkflowStatus] = {}


def process_has_active_task(thread_id: str) -> bool:
    """Whether *this* process is running this thread.

    The serialization question, not the ownership one. Callers use it to avoid
    starting a second task or retry in this process, so it must answer from the
    thing that actually holds the Task.
    """
    return (thread_id in _background_tasks and not _background_tasks[thread_id].done()) or (
        thread_id in _active_sync_executions
    )


# Tasks that deliberately stay OUT of the per-thread slot above. The slot holds
# one task per thread and three call sites cancel whoever sits in it, so a second
# registrant would displace the workflow's own entry instead of being found --
# that ruling (#634) has not changed; see docs/execution-plane.md §7.1.
#
# This is *not* a third answer to "is this process busy": nothing OR-s it into
# process_has_active_task or has_active_execution, and it has exactly one reader.
# Its question is narrower -- what must the preempting canceller stop, and can it
# reach it. The lease cannot answer it instead: both backends grant the row to a
# second holder of the same instance (backend/db/execution_leases.py:301,
# backend/db/execution_leases.py:384), because owner_id identifies the process and
# not the task. Today's only writer is ripple-retry in _wf_actions.py.
_detached_tasks: dict[str, asyncio.Task[Any]] = {}


async def cancel_detached_and_wait(thread_id: str) -> None:
    """Stop this thread's detached task **and wait for it to finish unwinding**.

    The waiting is not a nicer spelling -- it is the condition the handover
    needs. A cancelled repair coroutine runs :func:`_execution_lease`'s
    ``finally`` on its way out, and that calls ``end_lease`` -> ``release``,
    which stamps the row ``released`` matching on ``owner_id`` alone
    (``backend/db/execution_leases.py:314``). ``owner_id`` is per *instance*, so
    that write lands on the very row the caller is about to take: the
    successor's own heartbeat then answers ``LOST`` and its own fence cancels it.
    Why the lease cannot separate the two tasks by itself is in
    ``backend/db/execution_leases.py:301`` and ``backend/db/execution_leases.py:384``
    -- a second holder inside this process is granted, not refused.

    Measured both ways: without the wait the successor's ``renew_outcome`` is
    ``LOST``; with it, ``RENEWED``. The pair, and the rest of the measurement, is
    in ``docs/execution-plane.md`` §7.1.
    """
    task = _detached_tasks.get(thread_id)
    if task is None or task.done():
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


async def _lease_is_held(thread_id: str) -> bool:
    """Best-effort lease read. A broken store answers "not held", not "held"."""
    try:
        from backend.db.execution_leases import thread_is_held
    except Exception as exc:  # pragma: no cover - import cannot fail in practice
        logger.warning("execution lease import failed: %s", exc)
        return False
    try:
        return await thread_is_held(thread_id)
    except Exception as exc:
        logger.warning("execution lease check failed for %s: %s", thread_id, exc)
        return False


async def has_active_execution(thread_id: str) -> bool:
    """Whether any instance is running this thread -- the status-derivation answer.

    The lease is the durable half: it is the only fact that outlives the process
    running the work, which is what turns "running vs stale" into a question
    about the workflow rather than about whoever happens to be reading it.

    The process-local registries are OR-ed in rather than replaced. They are
    what actually holds the Task, and when the lease store is unreachable the
    lease cannot know about this process -- losing that would report a live run
    as stale. The OR only ever widens "running", so a wrong answer can suppress
    an orphan report but can never invent one; and the callers that decide
    whether to *start* work use :func:`process_has_active_task` instead, so it
    cannot cause a second execution either.
    """
    if await _lease_is_held(thread_id):
        return True
    return process_has_active_task(thread_id)


def _fields_differ(fields: dict[str, Any], existing: Any) -> bool:
    """True if any field in ``fields`` differs from the existing WorkflowRow.

    Used by :func:`_db_upsert` to skip no-op UPDATEs on the /status poll path.
    Missing attributes on ``existing`` count as differing (write to be safe).
    """
    for key, new_value in fields.items():
        if not hasattr(existing, key):
            return True
        if getattr(existing, key) != new_value:
            return True
    return False


async def _db_upsert(thread_id: str, **fields: Any) -> WorkflowRow | None:
    """Create or update a workflow row in DB. No-ops if DB is unavailable.

    Returns the fetched/created WorkflowRow so callers needing the persisted
    row (e.g. /status label resolution) can reuse it instead of a second
    db_get round trip. ``None`` when the DB is unavailable or the upsert
    raised (caller must treat the row as unknown).
    """
    try:
        from backend.db.pool import is_pool_ready

        if not is_pool_ready():
            return None
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
            # ponytail: skip the write when nothing changed. /status polls every
            # 5s (frontend workflow.ts startPolling) and calls _db_upsert with the
            # same phase/status/progress each tick — a no-op UPDATE still costs a
            # DB round trip + row lock. Comparing against the fetched row first
            # makes unchanged polls read-only. Callers that mutate state
            # (start/resume/pause/cancel) always pass a differing field, so they
            # still write.
            if not _fields_differ(fields, existing):
                return existing
            await db_update(thread_id, **fields)
            # Label is only ever mutated when present in ``fields``; otherwise it
            # is unchanged across the update, so the pre-write row's label is
            # still authoritative for callers.
            return existing
        else:
            row = WorkflowRow(thread_id=thread_id, **fields)
            await db_create(row)
            return row
    except Exception:
        logger.exception("DB upsert failed for %s", thread_id)
        return None


async def _emit_status_transition(
    new_status: WorkflowStatus,
    thread_id: str,
    snapshot: StateSnapshot | None = None,
    store: BaseStore | None = None,
) -> None:
    """Emit events when workflow status transitions.

    P1a-S4: gate payloads embed copy_content / visual_plan / content_versions /
    draft_content / analytics — fields that on a ref'd thread live in the
    Artifact Store, not the checkpoint. Snapshot values therefore go through
    the read seam (:func:`resolve_state`) first. Legacy threads come back as a
    shallow copy with no store round trip, so the hot path pays nothing until
    refs exist.
    """
    old_status = _last_status.get(thread_id)
    if old_status == new_status:
        return
    _last_status[thread_id] = new_status

    # Clean up terminal entries to avoid unbounded growth
    if new_status in (WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED, WorkflowStatus.ERROR):
        _last_status.pop(thread_id, None)

    bus = EventBusService.get_instance()

    payload: dict[str, Any] = {"status": new_status.value}
    values: dict[str, Any] = {}
    if snapshot is not None:
        values = await resolve_state(store, thread_id, snapshot.values or {})
        payload["phase"] = pick(values, "phase")
        payload["current_agent"] = pick(values, "current_agent")
        payload["next_steps"] = list(snapshot.next) if snapshot.next else []

    if new_status == WorkflowStatus.AWAITING_REVIEW:
        if snapshot is not None:
            _rv = realtime_view(values, "review_pending")
            payload["content_plan"] = _rv["content_plan"]
            payload["copy_content"] = _rv["copy_content"]
            payload["visual_plan"] = _rv["visual_plan"]
            payload["version_history"] = _rv["content_versions"]
        bus.emit(EventType.REVIEW_PENDING, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_CHOICE:
        if snapshot is not None:
            _rv = realtime_view(values, "awaiting_choice")
            payload["data"] = {
                "versions": _rv["content_versions"],
                "draft": _rv["draft_content"],
                "analysis": _rv["optimization_analysis"],
            }
        else:
            payload["data"] = {}
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_DRAFT:
        if snapshot is not None:
            _rv = realtime_view(values, "awaiting_draft")
            payload["copy_content"] = _rv["copy_content"]
            payload["content_plan"] = _rv["content_plan"]
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_BRIEF:
        if snapshot is not None:
            _rv = realtime_view(values, "awaiting_brief")
            payload["brief_content"] = _rv["brief_content"]
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_RIPPLE_DECISION:
        if snapshot is not None:
            _rv = realtime_view(values, "awaiting_ripple_decision")
            payload["ripple_prediction"] = _rv["ripple_prediction"]
            payload["ripple_pmf"] = _rv["ripple_pmf"]
            payload["ripple_reason"] = _rv["ripple_reason"]
            payload["reselect_count"] = _rv["reselect_count"]
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.AWAITING_BLOGGER_SELECTION:
        if snapshot is not None:
            _rv = realtime_view(values, "awaiting_blogger_selection")
            payload["blogger_candidates"] = _rv["blogger_candidates"]
            payload["blogger_candidate_limit"] = _rv["blogger_candidate_limit"]
            payload["blogger_note_limit"] = _rv["blogger_note_limit"]
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.COMPLETED:
        # Emit WORKFLOW_COMPLETED here (single source of truth) — not in
        # individual nodes like publisher, which would prematurely close SSE
        # streams before any manually requested post-publish analysis has run.
        if snapshot is not None:
            _rv = realtime_view(values, "completed")
            payload["publish_result"] = _rv["publish_result"]
            payload["copy_content"] = _rv["copy_content"]
            payload["trend_data"] = _rv["trend_data"]
            payload["content_plan"] = _rv["content_plan"]
            payload["visual_plan"] = _rv["visual_plan"]
            payload["analytics"] = _rv["analytics"]
            payload["ripple_prediction"] = _rv["ripple_prediction"]
            payload["ripple_pmf"] = _rv["ripple_pmf"]
            payload["ripple_comparison"] = _rv["ripple_comparison"]
        bus.emit(EventType.WORKFLOW_COMPLETED, thread_id=thread_id, payload=payload)

    elif new_status in (WorkflowStatus.PAUSED, WorkflowStatus.CANCELLED):
        bus.emit(EventType.WORKFLOW_DATA_UPDATED, thread_id=thread_id, payload=payload)

    elif new_status == WorkflowStatus.ERROR:
        if snapshot is not None:
            payload["error"] = pick(values, "error", "")
        bus.emit(EventType.WORKFLOW_ERROR, thread_id=thread_id, payload=payload)

    else:
        # RUNNING, STALE — emit as data update so frontend stays in sync
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
    if has_error:
        return "error"
    return "running"


def _get_as_node(state: StateSnapshot) -> str | None:
    """Determine as_node for aupdate_state from the current state checkpoint.

    LangGraph requires as_node when updating state on a workflow paused at
    an interrupt (multiple nodes in state). Without it, raises
    InvalidUpdateError: Ambiguous update, specify as_node.
    """
    if state.tasks:
        return state.tasks[0].name
    if state.values:
        node = state.values.get("_last_node", "orchestrator")
        return node if isinstance(node, str) else "orchestrator"
    return "orchestrator"


def _task_has_error(task: Any) -> bool:
    error = getattr(task, "error", None)
    return error not in (None, "")


def _has_native_resume_point(state: StateSnapshot) -> bool:
    """Return True when LangGraph already has a pending node to resume."""
    if state.next:
        return True
    return any(_task_has_error(task) for task in (state.tasks or ()))


def _save_history_file(thread_id: str, state_values: dict[str, Any]) -> None:
    """Persist completed workflow result to history file."""
    try:
        import json
        import os
        from pathlib import Path

        serialized = json.dumps(state_values, default=str, ensure_ascii=False)
        # Skip rewrite when content is unchanged since last write for this
        # thread. /status polls completed workflows repeatedly; the state is
        # immutable post-completion, so re-dumping is pure waste.
        if _LAST_HISTORY_WRITE.get(thread_id) == serialized:
            return
        _LAST_HISTORY_WRITE[thread_id] = serialized

        history_dir = Path(os.environ.get("XHS_REGISTRY_PATH", ".xhs")) / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        path = history_dir / f"{thread_id}.json"
        path.write_text(serialized, encoding="utf-8")
    except Exception:
        logger.exception("Failed to save history for %s", thread_id)


def _fence_on_lost_lease(thread_id: str, heartbeat: asyncio.Task[RenewOutcome]) -> asyncio.Event:
    """Stop this run the moment the lease behind it goes away.

    ``renew``'s docstring left this to S3: S1 logged a lost lease and kept
    working. That was harmless while nothing acted on a lease, and it is not
    harmless now that a scan takes an expired one over -- if this instance no
    longer owns the row then another instance does, and the only way left to
    keep red line 4 ("no two writers on one checkpoint") is to stop before the
    next write.

    What makes this safe to wire up is the distinction it draws: a heartbeat
    that ends by itself means ``renew`` gave a non-answer, i.e. the row stopped
    being ours. A heartbeat cancelled by ``end_lease`` is this run finishing
    normally and must not fence anything -- hence ``task.cancelled()`` rather
    than merely "the heartbeat finished".

    Which non-answer it was is read off the task rather than inferred, and it is
    read for the log only: ``LOST`` and ``UNKNOWN`` both fence here, so the
    decision below has not changed. What changed is that a storage failure is no
    longer recorded as a takeover -- the sentence used to be printed for both,
    which is a claim this code could not back. The ruling that keeps them
    collapsed, and the budget asymmetry it leaves open, are in
    ``docs/execution-plane.md`` §2.

    A synchronously-executed run is fenced too. That aborts the HTTP response
    the caller is waiting on, which is still the better of the two outcomes: an
    aborted request beats a second writer on the same checkpoint.
    """
    lost = asyncio.Event()
    owner = asyncio.current_task()
    # Deferred, like every other lease import here: the module pulls the pool,
    # and this file is on the import path of every route. Runtime, not
    # TYPE_CHECKING, because the callback below reads a member of it.
    from backend.db.execution_leases import RenewOutcome

    def _on_heartbeat_done(task: asyncio.Task[RenewOutcome]) -> None:
        if task.cancelled():
            return
        # ``exception`` first: a heartbeat that raised would make ``result()``
        # re-raise inside a done-callback, where asyncio only logs it. The loop
        # is written to return rather than raise, so this path is the guard
        # against that changing silently -- and it fences, like any non-answer.
        outcome = RenewOutcome.UNKNOWN if task.exception() is not None else task.result()
        logger.warning(
            "execution lease %s for %s: stopping this run before it writes again",
            "lost" if outcome is RenewOutcome.LOST else "unconfirmed",
            thread_id,
        )
        lost.set()
        if owner is not None and not owner.done():
            owner.cancel()

    heartbeat.add_done_callback(_on_heartbeat_done)
    return lost


@dataclass(frozen=True, slots=True)
class LeaseFence:
    """What a lease-holding block sees: which answer, and where the fence fires.

    ``outcome`` is what ``start_lease`` decided; ``lost`` is the event the fence
    sets. They belong together because a caller's first question is "do I have
    the row, and if somebody else does, what now" -- and the answer differs by
    caller, so this helper reports the pair instead of ruling on it.
    """

    outcome: AcquireOutcome
    lost: asyncio.Event


@contextlib.asynccontextmanager
async def _execution_lease(thread_id: str) -> AsyncIterator[LeaseFence]:
    """Hold this thread's lease for the block, and fence on losing it.

    **The single place a lease is taken.** Three executors use it: the unified
    runner below, and the two repair paths in ``_wf_actions.py``
    (``_run_retry`` / ``_run_publish_retry``). Keeping one implementation is the
    point -- a second copy is how the two drift, and the lease is the only fact
    about a thread that outlives the process running it.

    The block always runs (P2b ruling 2), but *what it yields* says which answer
    the store gave. UNKNOWN -- a store that cannot reply, or one that will not
    import -- and GRANTED are not gates. HELD_BY_LIVE_OWNER is: it is evidence
    that another instance is mid-write, so a caller about to write has to stand
    down. This helper deliberately rules on none of that. It reports, its three
    callers decide, and they do not all decide alike.

    ``lost`` is set when the lease was lost, so a caller catching
    ``CancelledError`` can tell a fence-cancel from a user cancel. The fence
    target is ``asyncio.current_task()`` (see :func:`_fence_on_lost_lease`), so
    a caller need not be in ``_background_tasks`` to be fenced.
    """
    from backend.db.execution_leases import AcquireOutcome

    # UNKNOWN is the starting value because it is the answer to "we could not
    # ask": a store that will not import is as unable to reply as one that will
    # not connect, and both have to leave the block runnable (ruling 2).
    outcome = AcquireOutcome.UNKNOWN
    heartbeat: asyncio.Task[RenewOutcome] | None = None
    hold = None
    try:
        from backend.db.execution_leases import start_lease

        hold = await start_lease(thread_id)
    except Exception:
        hold = None
    if hold is not None:
        # Read *outside* the guard on purpose: a ``start_lease`` answering with
        # the wrong shape is a bug here or in a test's stand-in, and folding it
        # into UNKNOWN would turn that into "we could not ask" -- the fixture
        # answering for the code under test.
        outcome = hold.outcome
        heartbeat = hold.heartbeat

    lost = asyncio.Event()
    if heartbeat is not None:
        lost = _fence_on_lost_lease(thread_id, heartbeat)
    try:
        yield LeaseFence(outcome=outcome, lost=lost)
    finally:
        # Best-effort teardown. A cancelled task may not reach this await at
        # all; the lease then goes silent and expires, which is the property
        # being built rather than a gap in it.
        with contextlib.suppress(Exception):
            from backend.db.execution_leases import end_lease

            await end_lease(thread_id, heartbeat)


async def _run_graph_and_persist(
    thread_id: str,
    graph: Any,
    config: dict[str, Any],
    input_data: Any,
    *,
    source: str = "start",
) -> dict[str, Any]:
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

    # P2b-S1/S2/S3: the lease is the fact ``has_active_execution`` reads first, and
    # it fences its own owner. One implementation, shared with the two repair paths
    # in ``_wf_actions.py`` -- see :func:`_execution_lease`.
    # The outcome is deliberately not consulted here. This entry's refusal
    # semantics belong to the endpoints that call it (/recover admits only
    # error/stale), and gating on the lease would fail closed whenever storage is
    # unreachable -- P2b ruling 2. The two repair paths in ``_wf_actions.py`` do
    # consult it; this is where the unified entry's answer differs from theirs.
    async with _execution_lease(thread_id) as lease:
        try:
            result = await graph.ainvoke(input_data, config)

            snapshot = await graph.aget_state(config)
            has_active = await has_active_execution(thread_id)
            derived = derive_status(snapshot, has_active_task=has_active)

            await _emit_status_transition(
                derived,
                thread_id,
                snapshot=snapshot,
                store=getattr(graph, "store", None),
            )

            # Phase/error 取图真实状态（snapshot.values），与 derive_status 同源——
            # 否则 ainvoke 返回的 result 只是最后节点输出，phase 可能滞后于中断点真实
            # phase，导致 DB 写入的 phase/progress 与 /status 现算不一致。
            snapshot_values = snapshot.values or {}
            final_phase = snapshot_values.get("phase") or (
                result.get("phase", "unknown") if result else "unknown"
            )
            has_error = snapshot_values.get("error") or (result.get("error") if result else None)
            final_status = _status_to_str(derived, has_error, final_phase)

            # Compute progress: completed → 100, awaiting gates → phase-based, else phase-based
            if final_status == "completed":
                progress = 100
            elif final_status == "error":
                progress = 0
            else:
                from backend.api.routes._wf_artifacts import get_progress

                progress = get_progress(final_phase)

            await _db_upsert(
                thread_id,
                phase=final_phase,
                status=final_status,
                progress_percent=progress,
                error=has_error,
                updated_at=datetime.now(UTC).isoformat(),
            )

            if final_status in ("completed", "error", "cancelled"):
                _save_history_file(thread_id, result or {})

            return result or {}

        except asyncio.CancelledError:
            # P2b-S3: a fence-cancelled run must not write a status. Whoever holds
            # the lease owns this row now; writing "cancelled" here would erase the
            # takeover that just started.
            if lease.lost.is_set():
                raise
            # Only update DB if this task is still the registered one —
            # a newer task may have replaced it (e.g. _start_resume_task cancel+restart)
            if _background_tasks.get(thread_id) is not asyncio.current_task():
                raise
            try:
                snapshot = await graph.aget_state(config)
                current_phase = (snapshot.values or {}).get("phase", "unknown")
                if current_phase == "paused":
                    await _db_upsert(thread_id, status="paused", phase="paused", error=None)
                    await _emit_status_transition(
                        WorkflowStatus.PAUSED,
                        thread_id,
                        snapshot=snapshot,
                        store=getattr(graph, "store", None),
                    )
                elif current_phase == "cancelled":
                    # cancel_workflow already set phase+error in graph and DB — skip
                    pass
                else:
                    await _db_upsert(
                        thread_id, status="cancelled", phase="cancelled", error="Task cancelled"
                    )
                    await _emit_status_transition(
                        WorkflowStatus.CANCELLED,
                        thread_id,
                        snapshot=snapshot,
                        store=getattr(graph, "store", None),
                    )
            except Exception:
                await _db_upsert(
                    thread_id, status="cancelled", phase="cancelled", error="Task cancelled"
                )
            raise

        except Exception as exc:
            logger.exception("Graph execution failed (source=%s, thread=%s)", source, thread_id)
            # Only update DB if this task is still the registered one —
            # a newer task may have replaced it (e.g. _start_resume_task cancel+restart)
            if _background_tasks.get(thread_id) is asyncio.current_task():
                from backend.core.error_handling import WorkflowCancelledError

                if isinstance(exc, WorkflowCancelledError):
                    # Node detected cancelled/paused phase — preserve the actual phase
                    # from the graph state rather than parsing the exception message
                    snap = None
                    with contextlib.suppress(Exception):
                        snap = await graph.aget_state(config)
                    if snap:
                        actual_phase = (snap.values or {}).get("phase", "cancelled")
                    else:
                        actual_phase = "cancelled"
                    is_paused = actual_phase == "paused"
                    target_phase = "paused" if is_paused else "cancelled"
                    target_status = "paused" if is_paused else "cancelled"
                    with contextlib.suppress(Exception):
                        await graph.aupdate_state(
                            config,
                            {"phase": target_phase, "error": None if is_paused else str(exc)},
                            as_node=_get_as_node(snap) if snap else None,
                        )
                    await _db_upsert(
                        thread_id,
                        status=target_status,
                        phase=target_phase,
                        error=None if is_paused else str(exc),
                        updated_at=datetime.now(UTC).isoformat(),
                    )
                    await _emit_status_transition(
                        WorkflowStatus.PAUSED if is_paused else WorkflowStatus.CANCELLED,
                        thread_id,
                        snapshot=snap,
                        store=getattr(graph, "store", None),
                    )
                else:
                    with contextlib.suppress(Exception):
                        snapshot = await graph.aget_state(config)
                        if not _has_native_resume_point(snapshot):
                            await graph.aupdate_state(
                                config,
                                {"phase": "error", "error": str(exc)},
                                as_node=_get_as_node(snapshot),
                            )
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
            # Only pop if this task is still the registered one —
            # a newer task may have replaced it (e.g. _start_resume_task cancel+restart)
            if _background_tasks.get(thread_id) is asyncio.current_task():
                _background_tasks.pop(thread_id, None)
