"""Workflow application layer: one function per endpoint.

Each function is the use case behind a route: it coordinates the runtime
layer (tasks, resume, takeover, orphan checks), the artifacts layer (files,
checkpoints, documents) and the actions layer (the retry jobs), and returns
the payload the api layer puts on the wire.  Moved verbatim out of
``workflow.py`` (P2c-S4) -- the handlers left behind are thin shells.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile

from backend.api.account_scope import (
    assert_thread_owned,
    require_owned_account,
    resolve_required_account_id,
)
from backend.api.deps import get_current_user
from backend.api.errors import ValidationError, WorkflowNotFoundError
from backend.api.latency import LatencyTimer
from backend.api.responses import ApiResponse, success
from backend.api.routes import _runner
from backend.api.routes._runner import _db_upsert, _get_as_node, _save_history_file
from backend.api.routes._wf_artifacts import (
    _HISTORY_DIR,
    _extract_pdf_text,
    _format_shooting_plan,
    _get_ripple_progress,
    _load_history_file,
    _snapshot_to_checkpoint,
    get_progress,
)
from backend.api.routes._wf_models import (
    AgentTimelineEntry,
    BriefExtractResponse,
    BriefUploadResponse,
    CheckpointHistoryResponse,
    CheckpointSnapshot,
    ImageUploadResponse,
    RecoverRequest,
    WorkflowStartRequest,
    WorkflowStatusResponse,
)
from backend.api.routes._wf_runtime import (
    _get_state_update_node_without_advancing,
    _is_orphan_running,
    _last_success_node,
    _on_task_done,
    _persisted_status,
    _resume_nodes_from_tasks,
    _resume_past_evaluator_pause,
    _resume_phase_for_next_nodes,
    _start_resume_task,
)
from backend.db.pool import is_pool_ready
from backend.db.workflows import (
    delete_workflow as db_delete,
)
from backend.db.workflows import (
    get_workflow as db_get,
)
from backend.db.workflows import (
    list_workflows as db_list,
)
from backend.graph.routers import PAUSE_REASON_EVALUATOR_FAIL_CLOSED
from backend.realtime import EventBusService
from backend.realtime.events import EventType
from backend.state.enums import WorkflowMode, WorkflowPhase
from backend.state.goal import BriefInput, Goal
from backend.state.hydration import (
    checkpoint_view,
    history_file_view,
    recover_view,
    status_view,
    timeline_entry,
)
from backend.state.machine import WorkflowStatus, derive_status
from backend.state.modes import stored_mode

logger = logging.getLogger(__name__)


def _account_id_from_thread(thread_id: str) -> str:
    """Parse account id from ``xhs_{account_id}_{8hex}`` thread minting scheme."""
    if not thread_id.startswith("xhs_"):
        return ""
    body = thread_id[4:]
    sep = body.rfind("_")
    if sep <= 0:
        return ""
    suffix = body[sep + 1 :]
    if len(suffix) != 8 or any(c not in "0123456789abcdefABCDEF" for c in suffix):
        return ""
    return body[:sep].strip()


def _resolve_status_account_id(
    thread_id: str,
    values: dict[str, Any] | None = None,
    *,
    db_account_id: str | None = None,
) -> str:
    """Prefer state/DB account_id; fall back to parsing the thread id."""
    if values:
        raw = values.get("account_id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    if isinstance(db_account_id, str) and db_account_id.strip():
        return db_account_id.strip()
    return _account_id_from_thread(thread_id)


async def _seed_brief_payload(
    req: WorkflowStartRequest, graph: Any, thread_id: str
) -> BriefInput | None:
    """Where a brief run's body goes — or ``None`` when there is no body.

    P1a-S4-3: ``brief_content`` is refable, so the body is seeded into the
    Artifact Store and only the ref travels in the input state; otherwise the raw
    text would sit in the initial checkpoint across the whole ``awaiting_brief``
    pause. The put is best-effort — a store that declines keeps the body inline,
    never a dangling ref. That pair of destinations is
    :class:`~backend.state.goal.BriefInput`'s job to model, so this is where the
    IO happens and nowhere else.

    Trend mode carries no brief at all, and a brief run with no text is waiting
    for an upload rather than carrying a payload, so both answer ``None``.
    """
    if req.workflow_mode != WorkflowMode.BRIEF or not req.brief_text:
        return None

    from backend.state.artifacts import put_artifact

    body = {"raw_text": req.brief_text, "source_type": "text"}
    ref = await put_artifact(getattr(graph, "store", None), thread_id, "brief_content", body)
    return BriefInput(body=body, ref=None if ref is None else dict(ref))


async def start_workflow(
    req: WorkflowStartRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """启动新的增长引擎工作流（必须使用当前用户拥有的账号）."""
    account_id = await resolve_required_account_id(str(user["id"]), req.account_id)
    await require_owned_account(str(user["id"]), account_id)
    # Keep request fields consistent for the rest of the handler.
    req.account_id = account_id

    graph = request.app.state.graph
    thread_id = f"xhs_{req.account_id}_{uuid.uuid4().hex[:8]}"

    # Resolve niche: manual (non-empty) wins; else infer from imported history
    # notes. D2' fail-fast: an unresolvable niche rejects the start (422) —
    # agents must never compile an invented default into prompts.
    from backend.services.niche_resolver import resolve_account_niche

    niche_res = await resolve_account_niche(
        req.account_id,
        manual_niche=req.niche,
        cold_start_default="",
        persist=True,
    )
    if not niche_res.niche:
        raise HTTPException(
            status_code=422,
            detail=(
                "niche 无法解析（冷启动且无历史笔记可推断）：请显式传入 niche 后重试"
                "（D2': 工作流起点必须提供垂类赛道，不再默认 '母婴'）"
            ),
        )

    # This run's intent, as one value (``backend/state/goal.py``) — and then the
    # one place that turns it into the mapping a run starts from. The phase is
    # the mode's, not the request's; see ``Goal.start_phase`` for why.
    goal = Goal(
        account_id=req.account_id,
        thread_id=thread_id,
        mode=req.workflow_mode,
        topic=req.topic,
        niche=niche_res.niche,
        niche_resolution=niche_res.to_dict(),
        execution_mode=req.execution_mode,
        dry_run=req.dry_run,
        auto_publish=req.auto_publish,
        brief=await _seed_brief_payload(req, graph, thread_id),
        created_at=datetime.now(UTC).isoformat(),
    )
    initial_state = goal.compile_initial_state()
    start_phase_str = goal.start_phase.value

    config = {"configurable": {"thread_id": thread_id}}
    now = goal.created_at

    # Register workflow in DB (no-op when DB unavailable)
    await _db_upsert(
        thread_id,
        account_id=req.account_id,
        phase=start_phase_str,
        status="running",
        dry_run=req.dry_run,
        auto_publish=req.auto_publish,
        progress_percent=get_progress(start_phase_str),
        workflow_mode=req.workflow_mode,
        label="",
        created_at=now,
        updated_at=now,
    )

    # Brief mode without a body: save the initial state to the checkpoint but do
    # not start execution — the PDF upload will trigger the actual start via
    # aupdate_state. The condition is the goal's, not a comparison restated here.
    if goal.waits_for_brief_upload:
        await graph.aupdate_state(config, initial_state, as_node="orchestrator")
        # Update DB status to awaiting_brief (not "running" — no active task)
        actual_phase = goal.start_phase.value
        await _db_upsert(
            thread_id,
            status="awaiting_brief",
            phase=actual_phase,
            progress_percent=get_progress(actual_phase),
            updated_at=datetime.now(UTC).isoformat(),
        )
        return success(
            data={
                "thread_id": thread_id,
                "status": "awaiting_brief",
                "phase": actual_phase,
                "progress_percent": get_progress(actual_phase),
                "sse_url": f"/api/workflow/stream/{thread_id}",
                "websocket_url": "/api/realtime/ws",
            }
        )

    if req.async_mode:

        async def _run_async() -> None:
            await _runner._run_graph_and_persist(
                thread_id,
                graph,
                config,
                initial_state,
                source="start",
            )

        task = asyncio.create_task(_run_async())
        task.add_done_callback(_on_task_done(thread_id))
        _runner._background_tasks[thread_id] = task
        return success(
            data={
                "thread_id": thread_id,
                "status": "running",
                "phase": start_phase_str,
                "progress_percent": get_progress(start_phase_str),
                "sse_url": f"/api/workflow/stream/{thread_id}",
                "websocket_url": "/api/realtime/ws",
            }
        )
    else:
        from backend.core.error_handling import WorkflowCancelledError

        with contextlib.suppress(asyncio.CancelledError, WorkflowCancelledError):
            await _runner._run_graph_and_persist(
                thread_id,
                graph,
                config,
                initial_state,
                source="start",
            )

        # Read final status from DB (fallback to completed when DB unavailable)
        row = await db_get(thread_id) if is_pool_ready() else None
        final_status = row.status if row else "completed"
        final_phase = row.phase if row else "unknown"

        return success(
            data={
                "thread_id": thread_id,
                "status": final_status,
                "phase": final_phase,
                "progress_percent": 100 if final_status == "completed" else 0,
            }
        )


async def get_workflow_status(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取工作流状态"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    _lat = LatencyTimer("/status", thread_id) if LatencyTimer.should_sample("/status") else None

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    if _lat:
        with _lat.segment("aget_state"):
            state = await graph.aget_state(config)
    else:
        state = await graph.aget_state(config)

    # Check if workflow exists in live graph state
    if state.values and state.values.get("session_id") is not None:
        phase = state.values.get("phase", "unknown")

        has_active = await _runner.has_active_execution(thread_id)
        derived_status = derive_status(state, has_active_task=has_active)
        status_str = str(derived_status.value)
        # Orphan: DB reported running but no live in-process task (restart orphan).
        # derive_status already maps this to STALE — flag it for the response.
        is_orphan = derived_status == WorkflowStatus.STALE and not has_active

        # Graph can end (no next nodes / no interrupt → COMPLETED) while the
        # stored phase is still mid-flight (e.g. reviewing). Heal the phase we
        # return and persist so the dashboard does not keep showing gate CTAs.
        if status_str == WorkflowStatus.COMPLETED.value and phase not in (
            WorkflowPhase.COMPLETED.value,
            WorkflowPhase.ERROR.value,
            WorkflowPhase.CANCELLED.value,
        ):
            phase = WorkflowPhase.COMPLETED.value
        elif status_str == WorkflowStatus.ERROR.value and phase != WorkflowPhase.ERROR.value:
            phase = WorkflowPhase.ERROR.value
        elif (
            status_str == WorkflowStatus.CANCELLED.value and phase != WorkflowPhase.CANCELLED.value
        ):
            phase = WorkflowPhase.CANCELLED.value

        # Compute progress: completed → always 100; awaiting gates → phase-based; error → 0
        if status_str == "completed":
            progress = 100
        elif status_str == "error":
            progress = 0
        else:
            progress = get_progress(phase)

        # P1a-S4-3: brief_content is out-of-line on ref'd threads — resolve
        # once up front so the history dump, the DB label and the hydrated
        # response all see the full inline view (D4). Legacy threads pay no
        # store round trip (values is a shallow copy of state.values).
        from backend.state.artifacts import resolve_state
        from backend.state.events import load_perf_log

        values = await resolve_state(getattr(graph, "store", None), thread_id, state.values)

        # Persist completed workflow results to history file
        if phase in ("completed", "error", "cancelled"):
            _save_history_file(thread_id, values)

        # Update DB
        update_fields: dict[str, Any] = {
            "phase": phase,
            "status": status_str,
            "progress_percent": progress,
        }
        if state.values.get("error"):
            update_fields["error"] = state.values.get("error")

        # Update label with content summary (brand name for brief, topic for trend)
        if not update_fields.get("label"):
            bc = values.get("brief_content") or {}
            cp = values.get("content_plan") or {}
            if bc.get("brand_name"):
                update_fields["label"] = bc["brand_name"]
            elif bc.get("product_name"):
                update_fields["label"] = bc["product_name"]
            elif bc.get("content_direction"):
                update_fields["label"] = bc["content_direction"][:20]
            elif cp.get("selected_topic"):
                update_fields["label"] = cp["selected_topic"]
            elif bc.get("raw_text"):
                update_fields["label"] = bc["raw_text"][:20] + "…"
        # Carry the thread's own mode onto its row. Read through the registry
        # (``backend/state/modes.py``) so that this is not a second place that
        # knows the state key, and read *raw* rather than normalised: a legacy
        # thread keeps whatever it was created with.
        stored = stored_mode(values)
        if stored:
            update_fields["workflow_mode"] = stored

        if _lat:
            with _lat.segment("db"):
                _row = await _db_upsert(thread_id, **update_fields)
        else:
            _row = await _db_upsert(thread_id, **update_fields)

        # Resolve label for response: prefer the field we just persisted, then
        # the row _db_upsert already fetched (reusing it avoids a second db_get
        # round trip on every poll that has no auto-generated label).
        label = update_fields.get("label", "")
        if not label and _row is not None:
            label = _row.label or ""

        _serialize_seg = _lat.segment("serialize") if _lat else None
        if _serialize_seg:
            _serialize_seg.__enter__()

        # P1a-S2: telemetry lives in the Event store; legacy checkpoints still
        # carry it inline and the reader merges both.
        perf_log = await load_perf_log(thread_id, values)
        # P1a-S3/S4-3: the up-front resolve already hydrated the ref'd view —
        # reuse it for the response payload instead of a second store pass.
        live_values = values
        # ponytail: filter to node-level entries (kind=="node" or absent for
        # back-compat with pre-kind entries). llm/ripple/human_wait entries
        # share the log but don't populate the agent_timeline schema.
        agent_timeline = [
            AgentTimelineEntry(**entry)
            for entry in (timeline_entry(e) for e in perf_log)
            if entry is not None
        ]

        _resp = success(
            data=WorkflowStatusResponse(
                thread_id=thread_id,
                phase=phase,
                status=status_str,
                current_agent=state.values.get("current_agent", "unknown"),
                next_steps=list(state.next) if state.next else [],
                error=state.values.get("error"),
                progress_percent=progress,
                created_at=state.values.get("created_at"),
                updated_at=state.values.get("updated_at"),
                account_id=_resolve_status_account_id(thread_id, state.values),
                agent_timeline=agent_timeline,
                ripple_progress=_get_ripple_progress(thread_id),
                label=label,
                orphan=is_orphan,
                # RuntimeState scalar (not a stage-view key): read straight from
                # state exactly as pre-S1 so the evaluator_fail_closed resume
                # prompt keeps rendering. history-file branch never hydrated it.
                pause_reason=state.values.get("pause_reason"),
                **status_view(live_values),
            ).model_dump()
        )
        if _serialize_seg:
            _serialize_seg.__exit__(None, None, None)
        if _lat:
            _lat.emit(phase=phase)
        return _resp

    # Fallback 1: check history file (pre-DB completed workflows)
    saved = _load_history_file(thread_id)
    if saved:
        phase = saved.get("phase", "unknown")
        # History files are dumps of the full state, so a pre-S2 run keeps its
        # entries inline; a post-S2 run has them in the Event store.
        from backend.state.artifacts import resolve_state
        from backend.state.events import load_perf_log

        perf_log = await load_perf_log(thread_id, saved)
        saved = await resolve_state(getattr(graph, "store", None), thread_id, saved)
        agent_timeline = [
            AgentTimelineEntry(**entry)
            for entry in (timeline_entry(e) for e in perf_log)
            if entry is not None
        ]
        return success(
            data=WorkflowStatusResponse(
                thread_id=thread_id,
                phase=phase,
                status=_persisted_status(phase, saved.get("error")),
                current_agent=saved.get("current_agent", "unknown"),
                next_steps=[],
                error=saved.get("error"),
                progress_percent=get_progress(phase),
                created_at=saved.get("created_at"),
                updated_at=saved.get("updated_at"),
                account_id=_resolve_status_account_id(thread_id, saved),
                agent_timeline=agent_timeline,
                ripple_progress={},  # History file has no live Ripple progress
                label="",
                **history_file_view(saved),
            ).model_dump()
        )

    # Fallback 2: check DB for metadata-only entries (e.g. workflows created but
    # not yet checkpointed by LangGraph)
    if is_pool_ready():
        row = await db_get(thread_id)
    else:
        row = None
    if row:
        # A workflow is only truly "checkpoint lost" if:
        # - It has a non-terminal status in DB (meaning it was running/paused/awaiting)
        # - AND there is no active background task for it in this process
        # - AND there is no live LangGraph checkpoint (we already checked above)
        has_active_task = await _runner.has_active_execution(thread_id)
        checkpoint_lost = (
            row.status
            in (
                "running",
                "stale",
                "paused",
                "awaiting_review",
                "awaiting_choice",
                "awaiting_draft",
                "awaiting_brief",
                "awaiting_ripple_decision",
                "awaiting_blogger_selection",
            )
            and not has_active_task
        )
        # Orphan: DB running with no live task — restart orphan. Surface as
        # stale in the response so /recover can pick it up.
        is_orphan = await _is_orphan_running(thread_id, row.status)
        fallback_status = row.status or _persisted_status(row.phase, row.error)
        effective_status = "stale" if is_orphan else fallback_status
        data = WorkflowStatusResponse(
            thread_id=thread_id,
            phase=row.phase,
            status=effective_status,
            current_agent="unknown",
            next_steps=[],
            error=row.error,
            progress_percent=row.progress_percent,
            created_at=row.created_at,
            updated_at=row.updated_at,
            account_id=_resolve_status_account_id(thread_id, db_account_id=row.account_id),
            label=row.label or "",
            checkpoint_lost=checkpoint_lost,
            orphan=is_orphan,
        ).model_dump()
        return success(data=data)

    raise WorkflowNotFoundError(thread_id)


async def get_checkpoint_history(
    thread_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100, description="Max checkpoints to return"),
    before: str | None = Query(None, description="Checkpoint ID cursor for pagination"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """获取工作流的检查点历史记录（用于回放）"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    # Build before_config for cursor-based pagination
    before_config = None
    if before:
        before_config = {"configurable": {"thread_id": thread_id, "checkpoint_id": before}}

    checkpoints: list[CheckpointSnapshot] = []
    has_more = False
    found_workflow = False

    try:
        count = 0
        async for snapshot in graph.aget_state_history(
            config,
            limit=limit + 1,
            before=before_config,
        ):
            found_workflow = True
            if count >= limit:
                has_more = True
                break
            checkpoints.append(
                await _snapshot_to_checkpoint(snapshot, getattr(graph, "store", None), thread_id)
            )
            count += 1
    except ValueError:
        # No checkpointer configured — fall through to history file fallback
        pass

    if found_workflow:
        return success(
            data=CheckpointHistoryResponse(
                thread_id=thread_id,
                checkpoints=checkpoints,
                has_more=has_more,
            ).model_dump()
        )

    # Fallback: check history file for completed workflows (no live checkpoints)
    saved = _load_history_file(thread_id)
    if saved:
        phase = saved.get("phase", "unknown")
        checkpoint = CheckpointSnapshot(
            checkpoint_id="history-final",
            step=0,
            source="history_file",
            phase=phase,
            current_agent=saved.get("current_agent", ""),
            created_at=saved.get("updated_at") or saved.get("created_at"),
            next_nodes=[],
            **checkpoint_view(saved),
        )
        return success(
            data=CheckpointHistoryResponse(
                thread_id=thread_id,
                checkpoints=[checkpoint],
                has_more=False,
            ).model_dump()
        )

    # Fallback: check DB
    if is_pool_ready():
        row = await db_get(thread_id)
    else:
        row = None
    if row:
        return success(
            data=CheckpointHistoryResponse(
                thread_id=thread_id,
                checkpoints=[],
                has_more=False,
            ).model_dump()
        )

    raise WorkflowNotFoundError(thread_id)


async def pause_workflow(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """暂停工作流"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    current_phase = state.values.get("phase", "unknown")
    await graph.aupdate_state(
        config, {"phase": "paused", "prev_phase": current_phase}, as_node=_get_as_node(state)
    )

    bg_task = _runner._background_tasks.get(thread_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()

    await _db_upsert(thread_id, status="paused", phase="paused")

    await _runner._emit_status_transition(
        WorkflowStatus.PAUSED, thread_id, store=getattr(graph, "store", None)
    )

    return success(
        data={
            "thread_id": thread_id,
            "status": "paused",
            "message": "工作流已暂停，当前 Agent 完成后将停止",
        }
    )


async def resume_workflow(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """恢复暂停或可重试错误的工作流"""
    from langgraph.types import Command

    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        saved = _load_history_file(thread_id)
        if not saved or saved.get("phase") != WorkflowPhase.ERROR:
            raise WorkflowNotFoundError(thread_id)

        resume_node = saved.get("current_agent")
        if not resume_node or resume_node == "unknown":
            return success(
                data={
                    "thread_id": thread_id,
                    "status": "error",
                    "message": "工作流错误历史缺少可恢复节点，无法恢复。",
                }
            )

        if resume_node == "engagement":
            return success(
                data={
                    "thread_id": thread_id,
                    "status": WorkflowStatus.COMPLETED.value,
                    "phase": WorkflowPhase.COMPLETED,
                    "recovered": False,
                    "message": "旧版自动互动节点已移除，工作流不会恢复评论或私信操作。",
                }
            )

        prev_phase = _resume_phase_for_next_nodes(
            (resume_node,),
            saved.get("prev_phase") or WorkflowPhase.CREATING,
        )
        restored_state = {
            **saved,
            "phase": prev_phase,
            "error": None,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        await graph.aupdate_state(config, restored_state, as_node=resume_node)
        await _start_resume_task(thread_id, graph, config, prev_phase)

        return success(
            data={
                "thread_id": thread_id,
                "status": "running",
                "phase": prev_phase,
            }
        )

    has_active = await _runner.has_active_execution(thread_id)
    derived = derive_status(state, has_active_task=has_active)

    # P0-W5 continuation channel: the evaluator parked this thread on purpose.
    # Handled exclusively here — such a thread must never reach the legacy
    # restart further down (that re-runs scouting and the whole creation chain).
    # Only run-ended/terminal shapes qualify; a thread that is live or waiting at
    # another gate keeps its existing channel (review submit, gate resume, ...).
    if str(
        (state.values or {}).get("pause_reason") or ""
    ) == PAUSE_REASON_EVALUATOR_FAIL_CLOSED and derived in (
        WorkflowStatus.PAUSED,
        WorkflowStatus.COMPLETED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.ERROR,
        WorkflowStatus.STALE,
    ):
        return await _resume_past_evaluator_pause(thread_id, request, graph, config, state)

    if derived == WorkflowStatus.AWAITING_REVIEW:
        return success(
            data={
                "thread_id": thread_id,
                "status": "awaiting_review",
                "message": "工作流正在等待审核，请使用 /api/review/submit 端点提交审核决定",
            }
        )

    if derived == WorkflowStatus.AWAITING_CHOICE:
        return success(
            data={
                "thread_id": thread_id,
                "status": "awaiting_choice",
                "message": "工作流正在等待版本选择，请使用 /api/optimization/select 端点选择版本",
            }
        )

    if derived == WorkflowStatus.AWAITING_DRAFT:
        return success(
            data={
                "thread_id": thread_id,
                "status": "awaiting_draft",
                "message": "工作流正在等待草稿提交，请使用 /api/optimization/draft 端点提交草稿",
            }
        )

    if derived == WorkflowStatus.AWAITING_BRIEF:
        # Resume from brief_gate interrupt — pass resume value for skip/answer
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        resume_value = body.get("resume_value", {"action": "skip"})

        result = await _runner._run_graph_and_persist(
            thread_id,
            graph,
            config,
            Command(resume=resume_value),
            source="brief_resume",
        )
        return success(
            data={
                "thread_id": thread_id,
                "status": "running",
                "phase": result.get("phase", WorkflowPhase.BRIEFING)
                if result
                else WorkflowPhase.BRIEFING,
            }
        )

    if derived == WorkflowStatus.AWAITING_RIPPLE_DECISION:
        # Resume from ripple_gate interrupt — accept/reangle/retopic
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        resume_value = body.get("resume_value", {"action": "accept"})

        result = await _runner._run_graph_and_persist(
            thread_id,
            graph,
            config,
            Command(resume=resume_value),
            source="ripple_resume",
        )
        return success(
            data={
                "thread_id": thread_id,
                "status": "running",
                "phase": result.get("phase", WorkflowPhase.CREATING)
                if result
                else WorkflowPhase.CREATING,
            }
        )

    if derived == WorkflowStatus.AWAITING_BLOGGER_SELECTION:
        # Resume from blogger_gate interrupt. The blogger gate accepts either a
        # concrete selection ({user_id, nickname}) or an explicit skip.
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        resume_value = body.get("resume_value", {"skip": True})

        result = await _runner._run_graph_and_persist(
            thread_id,
            graph,
            config,
            Command(resume=resume_value),
            source="blogger_resume",
        )
        return success(
            data={
                "thread_id": thread_id,
                "status": "running",
                "phase": result.get("phase", WorkflowPhase.CREATING)
                if result
                else WorkflowPhase.CREATING,
            }
        )

    if derived == WorkflowStatus.AWAITING_PUBLISH:
        # 发布确认关卡（P2a-S4b）。和前三个 gate 不同的地方只有一处，而它是
        # 刻意的：brief / ripple / blogger 的 resume_value 都有默认值（skip /
        # accept），因为那里的默认是"继续一件已经被授权的事"；这里没有默认值，
        # 因为这里的默认会**执行那个不可逆的动作**。所以缺 decision 时不动作、
        # 只说明该发什么 —— 空 body 的 /resume 绝不能读成一次发布确认。
        body = (
            await request.json()
            if request.headers.get("content-type", "").startswith("application/json")
            else {}
        )
        resume_value = body.get("resume_value")
        if not isinstance(resume_value, dict) or "decision" not in resume_value:
            return success(
                data={
                    "thread_id": thread_id,
                    "status": WorkflowStatus.AWAITING_PUBLISH.value,
                    "message": (
                        "工作流正在等待发布确认。请以 "
                        '{"resume_value": {"decision": "confirmed"}} 确认发布，'
                        '或 {"resume_value": {"decision": "cancelled"}} 取消；'
                        "不带 decision 的恢复不会发布任何内容。"
                    ),
                }
            )

        result = await _runner._run_graph_and_persist(
            thread_id,
            graph,
            config,
            Command(resume=resume_value),
            source="publish_confirmation",
        )
        return success(
            data={
                "thread_id": thread_id,
                "status": "running",
                "phase": result.get("phase", WorkflowPhase.PUBLISHING)
                if result
                else WorkflowPhase.PUBLISHING,
            }
        )

    next_nodes = tuple(state.next or ())
    if "engagement" in next_nodes:
        return success(
            data={
                "thread_id": thread_id,
                "status": WorkflowStatus.COMPLETED.value,
                "phase": WorkflowPhase.COMPLETED,
                "recovered": False,
                "message": "旧版自动互动节点已移除，工作流不会恢复评论或私信操作。",
            }
        )
    can_retry_error = derived == WorkflowStatus.ERROR
    can_resume_stale = derived == WorkflowStatus.STALE
    can_restart_terminal = derived in (WorkflowStatus.COMPLETED, WorkflowStatus.CANCELLED)

    if (
        derived != WorkflowStatus.PAUSED
        and not can_retry_error
        and not can_resume_stale
        and not can_restart_terminal
    ):
        return success(
            data={
                "thread_id": thread_id,
                "status": str(derived.value),
                "message": (
                    f"工作流当前状态为 {derived.value}，无法恢复。"
                    "只有暂停、过期、错误、已完成或已取消状态可以恢复/重试。"
                ),
            }
        )

    if can_retry_error or can_resume_stale:
        # Infer the displayed resume phase from the checkpoint's failed/pending
        # node (state.next / state.tasks), not a blind SCOUTING fallback. The
        # actual graph re-entry below uses native ainvoke(None) — NOT
        # aupdate_state(as_node=...), which would advance to the node's
        # successors and re-run the downstream chain.
        infer_nodes = next_nodes
        if not infer_nodes:
            infer_nodes = _resume_nodes_from_tasks(state.tasks)
        if not infer_nodes and state.values:
            last_node = state.values.get("_last_node")
            if last_node:
                infer_nodes = (last_node,)
        if "engagement" in infer_nodes:
            return success(
                data={
                    "thread_id": thread_id,
                    "status": WorkflowStatus.COMPLETED.value,
                    "phase": WorkflowPhase.COMPLETED,
                    "recovered": False,
                    "message": "旧版自动互动节点已移除，工作流不会恢复评论或私信操作。",
                }
            )
        prev_phase = _resume_phase_for_next_nodes(
            infer_nodes,
            state.values.get("prev_phase") or WorkflowPhase.CREATING,
        )
    else:
        # Paused (prev_phase saved on pause) or terminal restart (fresh from SCOUTING).
        prev_phase = state.values.get("prev_phase") or WorkflowPhase.SCOUTING

    # Resume strategy for error/stale: native re-run of the failed node.
    #
    # We must NOT call aupdate_state(as_node=_get_as_node(state)) here. On an
    # error checkpoint state.tasks holds an earlier *succeeded* node first
    # (e.g. orchestrator); _get_as_node picks tasks[0]=orchestrator, and
    # as_node=orchestrator means "orchestrator just finished" → ainvoke advances
    # to orchestrator's successors (trend_scout) → re-runs the whole downstream
    # chain (scouting → content_strategist → 30min Ripple). The failed node is
    # never retried. This is the retry/stale loop bug (see research/probe-results.md).
    #
    # Instead: LangGraph's native error-resume re-runs the failed task on
    # ainvoke(None) (the failed task's writes are empty / versions_seen not
    # bumped, per langgraph pregel/_loop.py). Leave the graph checkpoint
    # untouched; _start_resume_task clears persisted display state and then
    # resumes with None. This matches the workflow-state spec: stale/error
    # resume uses ainvoke(None).
    if can_retry_error or can_resume_stale:
        await _start_resume_task(thread_id, graph, config, prev_phase)
    else:
        await graph.aupdate_state(
            config, {"phase": prev_phase, "error": None}, as_node=_get_as_node(state)
        )
        await _start_resume_task(thread_id, graph, config, prev_phase)

    return success(
        data={
            "thread_id": thread_id,
            "status": "running",
            "phase": prev_phase,
        }
    )


async def recover_workflow(
    thread_id: str,
    req: RecoverRequest,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """显式恢复操作 — 把状态诊断变成可执行操作。

    仅 error/stale 状态可 recover。三种策略：
      - retry_failed: 等同 /resume error 路径（native ainvoke(None) 重跑失败 task）
      - retry_from_last_success: Command(goto=上次成功节点) 重跑该节点起的链
      - skip_to_next: Command(goto=state.next[0]) 跳过失败节点，从后继继续
    """
    from langgraph.types import Command

    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if not state.values or state.values.get("session_id") is None:
        # No live LangGraph checkpoint. Before returning 404, check if the DB
        # has a running/stale row for this thread — that's the "checkpoint_lost"
        # case (e.g. after a container restart where the checkpoint DB was lost
        # but the workflow metadata row survived). Return a diagnostic 200 so
        # the user knows to /resume restart instead of hitting a bare 404.
        if is_pool_ready():
            row = await db_get(thread_id)
        else:
            row = None
        if row:
            has_active_task = await _runner.has_active_execution(thread_id)
            checkpoint_lost = (
                row.status
                in (
                    "running",
                    "stale",
                    "paused",
                    "awaiting_review",
                    "awaiting_choice",
                    "awaiting_draft",
                    "awaiting_brief",
                    "awaiting_ripple_decision",
                    "awaiting_blogger_selection",
                )
                and not has_active_task
            )
            if checkpoint_lost:
                return success(
                    data={
                        "thread_id": thread_id,
                        "status": "checkpoint_lost",
                        "strategy": req.strategy,
                        "recovered": False,
                        "message": (
                            "DB 有记录但 LangGraph checkpoint 丢失，无法续跑；"
                            "建议 /resume restart 重新开始。"
                        ),
                    }
                )
        raise WorkflowNotFoundError(thread_id)

    has_active = await _runner.has_active_execution(thread_id)
    derived = derive_status(state, has_active_task=has_active)

    # 仅 error/stale 可 recover；其他状态给出明确拒绝信息
    if derived not in (WorkflowStatus.ERROR, WorkflowStatus.STALE):
        return success(
            data={
                "thread_id": thread_id,
                "status": str(derived.value),
                "strategy": req.strategy,
                "recovered": False,
                "message": (
                    f"工作流当前状态为 {derived.value}，不可 recover。"
                    "paused 用 /resume，completed/cancelled 用 /resume restart。"
                ),
            }
        )

    # ── 定位目标节点 + 构造 input_data ──
    _rcv = recover_view(state.values)
    target_node: str | None = None
    input_data: Any = None

    if req.strategy == "retry_failed":
        # 等同 /resume error 路径：native ainvoke(None) 重跑失败 task
        input_data = None
        infer_nodes = tuple(state.next or ())
        if not infer_nodes:
            infer_nodes = _resume_nodes_from_tasks(state.tasks)
        if not infer_nodes and state.values:
            last_node = _rcv["_last_node"]
            if last_node:
                infer_nodes = (last_node,)
        prev_phase = _resume_phase_for_next_nodes(
            infer_nodes,
            _rcv["prev_phase"] or WorkflowPhase.CREATING,
        )
        target_node = infer_nodes[0] if infer_nodes else None

    elif req.strategy == "retry_from_last_success":
        target_node = _last_success_node(state)
        if not target_node:
            # 上次成功节点无法确定 → 400 带诊断，不盲跑
            raise ValidationError(
                "strategy",
                "无法确定上次成功节点：state.tasks 中没有非失败的命名 task。"
                "可改用 retry_failed 或 skip_to_next。",
            )
        prev_phase = _resume_phase_for_next_nodes(
            (target_node,),
            _rcv["prev_phase"] or WorkflowPhase.CREATING,
        )
        input_data = Command(goto=target_node)

    else:  # skip_to_next
        next_nodes = tuple(state.next or ())
        if not next_nodes:
            raise ValidationError(
                "strategy",
                "无法确定后继节点：state.next 为空，失败节点没有可跳转的后继。"
                "可改用 retry_failed 或 retry_from_last_success。",
            )
        target_node = next_nodes[0]
        prev_phase = _resume_phase_for_next_nodes(
            next_nodes,
            _rcv["prev_phase"] or WorkflowPhase.CREATING,
        )
        input_data = Command(goto=target_node)

    if target_node == "engagement":
        return success(
            data={
                "thread_id": thread_id,
                "status": WorkflowStatus.COMPLETED.value,
                "target_node": target_node,
                "phase": WorkflowPhase.COMPLETED,
                "recovered": False,
                "message": "旧版自动互动节点已移除，工作流不会恢复评论或私信操作。",
            }
        )

    await _start_resume_task(thread_id, graph, config, prev_phase, input_data=input_data)

    return success(
        data={
            "thread_id": thread_id,
            "status": "running",
            "strategy": req.strategy,
            "target_node": target_node,
            "phase": prev_phase,
            "recovered": True,
        }
    )


async def cancel_workflow(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """取消工作流"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)

    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    current_phase = state.values.get("phase", "unknown")
    await graph.aupdate_state(
        config,
        {
            "phase": "cancelled",
            "error": "User cancelled",
            "prev_phase": current_phase,
        },
        as_node=_get_as_node(state),
    )

    await _db_upsert(
        thread_id,
        status="cancelled",
        phase="cancelled",
        error="User cancelled",
    )

    bg_task = _runner._background_tasks.get(thread_id)
    if bg_task and not bg_task.done():
        bg_task.cancel()

    await _runner._emit_status_transition(
        WorkflowStatus.CANCELLED, thread_id, store=getattr(graph, "store", None)
    )

    return success(
        data={
            "thread_id": thread_id,
            "status": "cancelled",
            "message": "工作流已取消",
        }
    )


async def stream_workflow_progress(thread_id: str, request: Request) -> StreamingResponse:
    """SSE 流式进度推送 — EventBus驱动

    Recovery: if the workflow is already in a terminal state (completed/error/
    cancelled) when the client connects, emit a synthetic terminal event
    immediately so the client doesn't hang waiting for a WORKFLOW_COMPLETED
    that was already broadcast before subscription. On reconnect (client sends
    the SSE-standard ``Last-Event-ID`` header), events missed since that seq
    are replayed first, scoped to this thread — mirroring the WebSocket
    ``get_missed?since=<seq>`` recovery path. Fresh connects skip the replay;
    full event recovery for dropped connections is the WebSocket path's job.
    """
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    graph = request.app.state.graph

    # Last-Event-ID is the SSE standard header EventSource sends on reconnect
    # (auto-set to the seq of the last event the client received). We use it to
    # avoid re-delivering events the client already saw — without it (fresh
    # connect), we only check for terminal state, never bulk-replay history.
    last_event_id = request.headers.get("Last-Event-ID")
    try:
        last_seq = int(last_event_id) if last_event_id is not None else -1
    except ValueError:
        last_seq = -1

    async def event_generator() -> Any:
        bus = EventBusService.get_instance()

        # P1a-S4 read seam: the synthetic terminal payload embeds refable
        # content fields (copy/visual/analytics) — resolve before reading.
        from backend.state.artifacts import resolve_state

        # On reconnect (Last-Event-ID present), replay events the client missed
        # since its last seen seq — scoped to this thread. On fresh connect
        # (no header), skip the replay: a brand-new client doesn't need history,
        # and bulk-replaying the whole ring buffer would re-deliver events to a
        # reconnecting client that forgot to send Last-Event-ID. Full event
        # recovery for dropped connections is the WebSocket /events/missed path.
        if last_seq >= 0:
            for event in bus.get_events_since(last_seq):
                if event.thread_id != thread_id:
                    continue
                event_data = json.dumps(event.payload, ensure_ascii=False)
                # Include id: so EventSource advances its Last-Event-ID cursor
                # over replayed events — without it a second reconnect would
                # re-deliver this whole replay window.
                yield f"event: {event.event_type.value}\nid: {event.seq}\ndata: {event_data}\n\n"
                if event.event_type in (
                    EventType.WORKFLOW_COMPLETED,
                    EventType.WORKFLOW_ERROR,
                ):
                    return

        # Check if the workflow is already terminal but no terminal event was
        # emitted (e.g. completed via a code path that bypassed EventBus, or
        # the event was evicted from the ring buffer). Emit a synthetic one so
        # the SSE client closes cleanly instead of hanging forever.
        # CANCELLED is mapped to WORKFLOW_COMPLETED with status=cancelled in
        # the payload so consumers can distinguish it from a real completion;
        # the frontend never sees this synthetic event (it uses WebSocket,
        # where _runner emits WORKFLOW_DATA_UPDATED for cancelled).
        config = {"configurable": {"thread_id": thread_id}}
        try:
            state = await graph.aget_state(config)
            if state.values and state.values.get("session_id") is not None:
                has_active = await _runner.has_active_execution(thread_id)
                derived = derive_status(state, has_active_task=has_active)
                if derived in (
                    WorkflowStatus.COMPLETED,
                    WorkflowStatus.ERROR,
                    WorkflowStatus.CANCELLED,
                ):
                    if derived == WorkflowStatus.ERROR:
                        synthetic_type = EventType.WORKFLOW_ERROR
                    else:
                        # COMPLETED and CANCELLED both close the stream via
                        # WORKFLOW_COMPLETED; consumers read status from payload.
                        synthetic_type = EventType.WORKFLOW_COMPLETED
                    values = await resolve_state(
                        getattr(graph, "store", None), thread_id, state.values or {}
                    )
                    payload: dict[str, Any] = {
                        "status": derived.value,
                        "phase": values.get("phase", ""),
                    }
                    # Enrich with the same content fields the real
                    # WORKFLOW_COMPLETED carries (runner._emit_progress), so
                    # consumers don't see an empty/sparse terminal payload.
                    if synthetic_type == EventType.WORKFLOW_COMPLETED:
                        for k in (
                            "publish_result",
                            "copy_content",
                            "trend_data",
                            "content_plan",
                            "visual_plan",
                            "analytics",
                            "ripple_prediction",
                            "ripple_pmf",
                            "ripple_comparison",
                        ):
                            v = values.get(k)
                            if v:
                                payload[k] = v
                    else:  # WORKFLOW_ERROR
                        payload["error"] = values.get("error", "")
                    event_data = json.dumps(payload, ensure_ascii=False)
                    yield (
                        f"event: {synthetic_type.value}\n"
                        f"id: {bus.current_seq()}\n"
                        f"data: {event_data}\n\n"
                    )
                    return
        except Exception:
            logger.debug("SSE terminal-check failed for %s", thread_id, exc_info=True)

        queue = bus.subscribe_thread(thread_id)

        try:
            while True:
                event = await queue.get()
                event_data = json.dumps(event.payload, ensure_ascii=False)
                yield f"event: {event.event_type.value}\nid: {event.seq}\ndata: {event_data}\n\n"

                if event.event_type in (
                    EventType.WORKFLOW_COMPLETED,
                    EventType.WORKFLOW_ERROR,
                ):
                    break
        finally:
            bus.unsubscribe_thread(thread_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def list_workflows_endpoint(
    request: Request,
    account_id: str | None = Query(None, description="账号 ID（省略则用当前用户活跃账号）"),
    status: str | None = Query(None, description="筛选状态: running/completed/error/cancelled"),
    limit: int = Query(20, ge=1, le=100, description="返回数量限制"),
    offset: int = Query(0, ge=0, description="分页偏移"),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """列出工作流 — 从 DB 查询，按创建时间倒序（单账号隔离，禁止全量聚合）."""
    account_id = await resolve_required_account_id(str(user["id"]), account_id)
    _lat = LatencyTimer("/list", account_id) if LatencyTimer.should_sample("/list") else None
    if is_pool_ready():
        if _lat:
            with _lat.segment("db"):
                rows, total = await db_list(
                    account_id=account_id,
                    status=status,
                    limit=limit,
                    offset=offset,
                )
        else:
            rows, total = await db_list(
                account_id=account_id,
                status=status,
                limit=limit,
                offset=offset,
            )
        _serialize_seg = _lat.segment("serialize") if _lat else None
        if _serialize_seg:
            _serialize_seg.__enter__()
        workflows: list[dict[str, Any]] = []
        for r in rows:
            item = r.to_dict()
            # The public Showcase uses a stable derived ID for legacy rows that
            # do not yet have an explicitly persisted public_id. Expose that
            # effective ID to the authenticated history UI so it can manage
            # visibility without duplicating the server-side secret logic.
            from backend.api.routes.public_showcase import _public_id

            item["showcase_public_id"] = _public_id(r)
            orphan = await _is_orphan_running(r.thread_id, r.status)
            if orphan:
                # Restart orphan: DB running but no live task. Reuse STALE
                # semantics so /recover can resume; do not mutate DB on read.
                item["status"] = WorkflowStatus.STALE.value
                item["orphan"] = True
            else:
                item["orphan"] = False
            workflows.append(item)
        _resp = success(
            data={
                "workflows": workflows,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )
        if _serialize_seg:
            _serialize_seg.__exit__(None, None, None)
        if _lat:
            _lat.emit(phase="ok")
        return _resp

    # Fallback when DB is unavailable: return empty list
    return success(
        data={
            "workflows": [],
            "total": 0,
            "limit": limit,
            "offset": offset,
        }
    )


async def workflow_account_totals(
    status: str | None = Query(
        None,
        description="可选：按状态计数（如 awaiting_review），省略则计全部工作流",
    ),
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Return workflow counts for every account owned by the current user.

    Metadata-only (no workflow content). Powers history/review multi-account
    chip badges in a single round-trip instead of N× ``/list?limit=1`` probes.
    Still ownership-scoped: only the caller's accounts appear.
    """
    from backend.db.accounts import list_accounts as db_list_accounts
    from backend.db.workflows import count_workflows_for_accounts

    _lat = (
        LatencyTimer("/account-totals", str(user["id"]))
        if LatencyTimer.should_sample("/account-totals")
        else None
    )
    if _lat:
        with _lat.segment("db"):
            owned = await db_list_accounts(owner_user_id=str(user["id"]))
            ids = [a.id for a in owned if a.id]
    else:
        owned = await db_list_accounts(owner_user_id=str(user["id"]))
        ids = [a.id for a in owned if a.id]
    if not ids:
        if _lat:
            _lat.emit(phase="empty")
        return success(data={"totals": {}, "status": status})

    if not is_pool_ready():
        if _lat:
            _lat.emit(phase="no-pool")
        return success(data={"totals": {aid: 0 for aid in ids}, "status": status})

    if _lat:
        with _lat.segment("count"):
            totals = await count_workflows_for_accounts(ids, status=status)
    else:
        totals = await count_workflows_for_accounts(ids, status=status)
    if _lat:
        _lat.emit(phase="ok")
    return success(data={"totals": totals, "status": status})


async def delete_workflow(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """删除工作流记录 — 只能删除已完成/已取消/出错的工作流"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    row = await db_get(thread_id) if is_pool_ready() else None
    in_history = (_HISTORY_DIR / f"{thread_id}.json").exists()

    if not row and not in_history:
        raise WorkflowNotFoundError(thread_id)

    if row and row.status == "running":
        raise ValidationError(
            "thread_id",
            "Cannot delete a running workflow. Cancel it first.",
        )

    # Also block if a background task is active (DB may not reflect running status yet)
    bg_task = _runner._background_tasks.get(thread_id)
    if bg_task and not bg_task.done():
        raise ValidationError(
            "thread_id",
            "Cannot delete a running workflow. Cancel it first.",
        )

    # Delete from DB
    if row:
        await db_delete(thread_id)

    # Delete history file
    history_path = _HISTORY_DIR / f"{thread_id}.json"
    with contextlib.suppress(OSError):
        history_path.unlink()

    # Delete from LangGraph checkpointer
    checkpointer = getattr(request.app.state, "checkpointer", None)
    if checkpointer is not None:
        with contextlib.suppress(Exception):
            await checkpointer.adelete_thread(thread_id)

    return success(
        data={
            "thread_id": thread_id,
            "message": "Workflow deleted from history",
        }
    )


async def extract_brief_file(
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Extract text from a brief document (PDF) without requiring a thread ID.

    Used by the frontend for immediate preview after file selection.
    The extracted text is then passed as briefText when starting the workflow.
    """
    form = await request.form()
    file = form.get("file")
    if not isinstance(file, UploadFile):
        raise ValidationError("file", "No file uploaded")

    filename = file.filename or "unknown"
    content_bytes = await file.read()

    max_upload_size = 20 * 1024 * 1024
    if len(content_bytes) > max_upload_size:
        raise ValidationError("file", f"File too large (max {max_upload_size // 1024 // 1024}MB)")

    brief_text = ""
    source_type = "text"

    if filename.lower().endswith(".pdf"):
        source_type = "pdf"
        brief_text, _ = await _extract_pdf_text(content_bytes)
    else:
        try:
            brief_text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            brief_text = content_bytes.decode("gbk", errors="replace")

    if not brief_text.strip():
        raise ValidationError("file", "Could not extract text from the uploaded file")

    return success(
        data=BriefExtractResponse(
            brief_text=brief_text[:500] + "..." if len(brief_text) > 500 else brief_text,
            source_type=source_type,
        ).model_dump()
    )


async def upload_brief_file(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Upload a brief document (PDF) and extract text content."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    form = await request.form()
    file = form.get("file")
    if not isinstance(file, UploadFile):
        raise ValidationError("file", "No file uploaded")

    filename = file.filename or "unknown"
    content_bytes = await file.read()

    max_upload_size = 20 * 1024 * 1024
    if len(content_bytes) > max_upload_size:
        raise ValidationError("file", f"File too large (max {max_upload_size // 1024 // 1024}MB)")

    brief_text = ""
    source_type = "text"
    perf_entry: dict[str, Any] | None = None

    if filename.lower().endswith(".pdf"):
        source_type = "pdf"
        brief_text, perf_entry = await _extract_pdf_text(content_bytes)
    else:
        try:
            brief_text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            brief_text = content_bytes.decode("gbk", errors="replace")

    if not brief_text.strip():
        raise ValidationError("file", "Could not extract text from the uploaded file")

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    snap = await graph.aget_state(config)
    as_node = _get_as_node(snap)

    update_values: dict[str, Any] = {
        "brief_content": {
            "raw_text": brief_text,
            "source_type": source_type,
        },
    }
    # P1a-S4-3: brief_content is refable — the write must go through the seam.
    # A bare inline write would be shadowed by the stale artifact ref on the
    # next resolve, silently discarding the freshly uploaded text on ref'd
    # threads (e.g. re-uploading a corrected PDF).
    from backend.state.artifacts import refify_updates, resolve_state

    store = getattr(graph, "store", None)
    values = await resolve_state(store, thread_id, snap.values or {})
    update_values = await refify_updates(store, thread_id, update_values, prev_values=values)
    # Emit the LLM cost entry (if any) to the Event store so /analytics/costs
    # sees the BRIEF_ANALYSIS spend. P1a-S2: no longer merged into the
    # checkpoint via the performance_log reducer.
    if perf_entry is not None:
        from backend.state.events import emit_events

        await emit_events(thread_id, [perf_entry])

    update_kwargs: dict[str, Any] = {"values": update_values}
    if as_node:
        update_kwargs["as_node"] = as_node

    await graph.aupdate_state(config, **update_kwargs)

    # If the workflow was started without brief_text (waiting for PDF upload),
    # it paused at the initial checkpoint — start execution now
    state = await graph.aget_state(config)
    next_nodes = state.next if state.next else ()
    # Serialization, not ownership: this starts a task *in this process*, so it
    # asks what this process is doing. Both directions are pinned by
    # tests/unit/api/test_serialization_guards_stay_local.py -- a bare lease read
    # would resume while our own task is live (the lease write is best-effort),
    # and asking "does anyone hold it" would refuse on a dead owner's lease for
    # up to LEASE_TTL_SECONDS after a restart, silently skipping the resume the
    # user just asked for. The status sites do ask the lease; see _runner.
    has_active = _runner.process_has_active_task(thread_id)

    if not has_active and next_nodes:
        # Workflow is paused and waiting — resume execution
        await _start_resume_task(thread_id, graph, config, WorkflowPhase.BRIEFING)

    return success(
        data=BriefUploadResponse(
            thread_id=thread_id,
            brief_text=brief_text[:500] + "..." if len(brief_text) > 500 else brief_text,
            source_type=source_type,
        ).model_dump()
    )


async def export_shooting_plan(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Export shooting plan as formatted text (for copy/download)."""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    from backend.state.artifacts import resolve_state

    state = await graph.aget_state(config)
    values = await resolve_state(getattr(graph, "store", None), thread_id, state.values)

    if not values or values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    shooting_plan = values.get("shooting_plan", {})
    if not shooting_plan:
        return success(data={"text": "", "message": "No shooting plan available yet"})

    text = _format_shooting_plan(shooting_plan)
    return success(data={"text": text, "format": "markdown"})


async def upload_images(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Upload images for a workflow (before publishing).

    Stored on disk, paths saved to visual_plan.image_paths.
    """
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    form = await request.form()
    files = form.getlist("files")
    if not files:
        raise ValidationError("files", "No files uploaded")

    # Validate file count and types
    if len(files) > 9:
        raise ValidationError("files", "Maximum 9 images allowed")

    allowed_types = {"image/jpeg", "image/png", "image/webp"}
    max_size = 10 * 1024 * 1024  # 10MB per file

    image_dir = Path(f"/tmp/xhs_images/{thread_id}")
    image_dir.mkdir(parents=True, exist_ok=True)

    saved_paths: list[str] = []
    for f in files:
        if not isinstance(f, UploadFile):
            continue
        if not f.filename:
            continue
        content = await f.read()
        if len(content) > max_size:
            raise ValidationError("files", f"File {f.filename} exceeds 10MB limit")
        if f.content_type not in allowed_types:
            raise ValidationError(
                "files", f"File {f.filename} has unsupported type {f.content_type}"
            )

        # Sanitize filename
        safe_name = f"{uuid.uuid4().hex[:8]}_{f.filename}"
        dest = image_dir / safe_name
        dest.write_bytes(content)
        saved_paths.append(str(dest))

    if not saved_paths:
        raise ValidationError("files", "No valid images were saved")

    # Update workflow state with image paths
    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    from backend.state.artifacts import refify_updates, resolve_state

    store = getattr(graph, "store", None)
    state = await graph.aget_state(config)
    values = await resolve_state(store, thread_id, state.values)
    if not values or values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    visual_plan = dict(values.get("visual_plan", {}))
    # Merge with existing paths (avoid duplicates)
    existing = set(visual_plan.get("image_paths", []))
    existing.update(saved_paths)
    visual_plan["image_paths"] = list(existing)

    # Write seam: visual_plan is refable — a bare inline write would be
    # shadowed by the stale ref body on the next resolve (uploaded paths
    # silently lost). refify stores the merged body + files the ref; on store
    # failure it keeps the value inline and tombstones the stale ref.
    refified = await refify_updates(
        store, thread_id, {"visual_plan": visual_plan}, prev_values=values
    )

    as_node = _get_state_update_node_without_advancing(state)
    update_kwargs: dict[str, Any] = {"values": refified}
    if as_node:
        update_kwargs["as_node"] = as_node

    await graph.aupdate_state(config, **update_kwargs)

    return success(
        data=ImageUploadResponse(
            image_paths=list(existing),
            count=len(existing),
        ).model_dump()
    )


async def trigger_analytics(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """手动触发 analyst 节点（发布后手动运行 Ripple 分析）"""
    from langgraph.types import Command

    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    from backend.state.artifacts import resolve_state

    state = await graph.aget_state(config)
    values = await resolve_state(getattr(graph, "store", None), thread_id, state.values)
    if not values or values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # Only allow when workflow has publish result but no analytics
    has_publish = bool(values.get("publish_result"))
    has_analytics = bool(values.get("analytics"))
    if not has_publish:
        return success(
            data={
                "thread_id": thread_id,
                "status": "error",
                "message": "工作流尚未发布，无法触发分析。",
            }
        )
    if has_analytics:
        return success(
            data={
                "thread_id": thread_id,
                "status": "completed",
                "message": "分析已完成，无需重复触发。",
            }
        )

    # Update state to analyzing phase, then jump to analyst node
    await graph.aupdate_state(
        config,
        {"phase": WorkflowPhase.ANALYZING, "error": None},
        as_node="publisher",
    )
    await _start_resume_task(
        thread_id,
        graph,
        config,
        WorkflowPhase.ANALYZING,
        input_data=Command(goto=["analyst"]),
    )

    return success(
        data={
            "thread_id": thread_id,
            "status": "running",
            "phase": "analyzing",
        }
    )
