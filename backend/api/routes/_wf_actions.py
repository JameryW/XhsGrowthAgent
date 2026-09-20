"""Workflow actions layer: the two use cases that bypass the unified entry.

``retry_ripple_analysis`` and ``retry_publish`` are the only endpoints whose
side effect does not go through ``_runner._run_graph_and_persist``: each starts
its own task and drives its own execution. That is why they are not in the
application layer with the other sixteen use cases -- and the reason has to be
stated precisely, because "writes checkpoints without taking a lease" would also
describe the other eighteen side-writes the request handlers do.

What makes these two special is that the *execution* is theirs: the handler
hands a nested coroutine to ``asyncio.create_task`` and never looks at it again,
so no execution-plane surface would otherwise know the thread is being written.
They therefore hold the lease through ``_runner._execution_lease`` -- the same
helper the unified entry uses -- which is what puts their writes inside
``docs/execution-plane.md`` §2's guarantee instead of outside it. A store that
cannot answer is still not a gate: see that helper for ruling 2. A *live foreign
owner* is not that kind of refusal -- it is evidence, not the absence of it -- so
these two paths stand down on it instead of writing over another instance's work.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import Depends, Request

from backend.agents.publisher import (
    evaluate_unknown_publish_retry,
    reconcile_unknown_publish,
    run_publish,
)
from backend.api.account_scope import assert_thread_owned
from backend.api.deps import get_current_user
from backend.api.errors import ValidationError, WorkflowNotFoundError
from backend.api.responses import ApiResponse, success
from backend.api.routes import _runner
from backend.api.routes._runner import _db_upsert, _execution_lease, _get_as_node
from backend.api.routes._wf_runtime import _on_task_done
from backend.db.execution_leases import AcquireOutcome
from backend.realtime import EventBusService
from backend.realtime.events import EventType
from backend.state.enums import WorkflowPhase

logger = logging.getLogger(__name__)


async def _record_lease_refusal(thread_id: str, *, path: str, account_id: str) -> None:
    """Record that a repair path stood down, and why, on the thread's timeline.

    The endpoint has already answered 200 ``retrying`` by the time this runs, so
    the refusal has nowhere else to surface: it cannot be a status code, and it
    must not be a state write -- not touching this thread is the entire point.
    ``state/events`` owns the refusal vocabulary for exactly that reason, and
    :data:`backend.state.events.ACTION_LEASE_REFUSED` is the third entry in it.

    Best-effort on both channels, deliberately: the log always lands, the event
    may not, and a failed event must never turn a safe refusal into an error.
    """
    from backend.state.events import ACTION_LEASE_REFUSED, action_perf_entry, emit_events

    logger.warning("%s refused for %s: a live owner holds the lease", path, thread_id)
    await emit_events(
        thread_id,
        [
            action_perf_entry(
                ACTION_LEASE_REFUSED,
                account_id=account_id,
                path=path,
                reason=AcquireOutcome.HELD_BY_LIVE_OWNER.value,
            )
        ],
    )


async def retry_ripple_analysis(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """重新运行 Ripple 传播预测和 PMF 验证（当之前超时或不可用时）"""
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    state = await graph.aget_state(config)
    if not state.values or state.values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # 并发守卫：与 retry_publish 同一条规则、同一个谓词、同一句文案。两处问的都是
    # "本进程要不要再起一份任务"，而租约答的是"有没有人在跑"，两个方向都会错（理由
    # 见 retry_publish 的同段注释与 tests/unit/api/test_serialization_guards_stay_local.py）。
    # 范围：只挡"重试撞本进程的执行"，不挡反向的"执行撞重试"——ripple-retry 刻意不写
    # _runner._background_tasks：那个 dict 每 thread 一槽，写入会顶掉工作流自己的条目，
    # 把 /pause、/cancel、/resume 的 cancel() 靶子换成重试。
    if _runner.process_has_active_task(thread_id):
        return success(
            data={
                "thread_id": thread_id,
                "status": "skipped",
                "message": "工作流正在运行，无法重试。",
            }
        )

    # P1a-S4-2: content_plan / ripple_prediction live in the Artifact Store on
    # ref'd threads — a raw read sees neither, so the retry would always
    # "skip" for lack of selected_topic. Resolve through the read seam first.
    from backend.state.artifacts import refify_updates, resolve_state

    store = getattr(graph, "store", None)
    values = await resolve_state(store, thread_id, state.values)
    ripple_reason = values.get("ripple_reason", "")
    content_plan = values.get("content_plan") or values.get("content_plan", {})
    ripple_prediction = values.get("ripple_prediction") or {}
    # Attribution for the refusal event below; the resolved state is the only
    # place this coroutine can still read it, since the handler has returned.
    account_id = str(values.get("account_id") or "")

    # Check if Ripple previously failed — explicit flags or fallback-looking prediction
    is_fallback_prediction = (
        ripple_prediction.get("viral_probability") == 0
        and ripple_prediction.get("confidence") == 0
        and ripple_prediction.get("estimated_reach") in (0, None)
    )
    if not ripple_reason and not values.get("ripple_fallback") and not is_fallback_prediction:
        return success(
            data={
                "thread_id": thread_id,
                "status": "skipped",
                "message": "Ripple 分析之前已成功，无需重试",
            }
        )

    topic = content_plan.get("selected_topic", "") if isinstance(content_plan, dict) else ""
    if not topic:
        return success(
            data={
                "thread_id": thread_id,
                "status": "skipped",
                "message": "无法重试：缺少 content_plan 或 selected_topic",
            }
        )

    from backend.services.ripple_service import RippleService, RippleTimeoutError

    ripple = RippleService.get_instance()
    ripple_timeout = 1800.0

    async def _run_retry() -> None:
        # 取租约：这是「执行平面」看见这两条路径的唯一通道。栅栏的靶子是
        # asyncio.current_task()（_runner._fence_on_lost_lease），与 _background_tasks
        # 无关 —— 所以本条刻意不进那个槽（每 thread 一槽，写入是换靶子），照样在
        # 丢租约时被 cancel。
        # 「问不到」照跑（裁定 2），只是没有栅栏可装；「活着的外部持有者」是另一
        # 回事——那是证据，不是证据的缺席。继续跑就正是这条租约要禁止的第二个写者，
        # 而且写的是另一个实例正在改的状态之上算出来的结果。stand down + 留事件。
        try:
            async with _execution_lease(thread_id) as lease:
                if lease.outcome is AcquireOutcome.HELD_BY_LIVE_OWNER:
                    await _record_lease_refusal(
                        thread_id, path="ripple-retry", account_id=account_id
                    )
                    return
                print(f"[ripple-retry] Started for {thread_id}, topic={topic}", flush=True)
                try:
                    # Bypass health-check/fallback — retry means we want a real simulation
                    pred_task = ripple.submit_and_wait(
                        {
                            "skill": "social-media",
                            "platform": "xiaohongshu",
                            "event": {
                                "topic": topic,
                                "content_type": content_plan.get("content_type", "note"),
                                "tags": content_plan.get("hashtags", []),
                                "tone": content_plan.get("content_angle", ""),
                                "description": content_plan.get("content_angle", ""),
                            },
                            "max_waves": 3,
                            "simulation_horizon": "12h",
                            "ensemble_runs": 1,
                        },
                        max_wait=ripple_timeout,
                        thread_id=thread_id,
                    )
                    pmf_task = ripple.submit_and_wait(
                        {
                            "skill": "pmf-validation",
                            "channel": "content-seeding",
                            "vertical": "fmcg",
                            "platform": "xiaohongshu",
                            "event": {
                                "name": content_plan.get("selected_topic", ""),
                                "category": content_plan.get("category", ""),
                                "description": content_plan.get("content_angle", ""),
                                "differentiators": content_plan.get("key_points", []),
                            },
                            "max_waves": 3,
                            "simulation_horizon": "12h",
                            "ensemble_runs": 1,
                        },
                        max_wait=ripple_timeout,
                        thread_id=thread_id,
                    )
                    raw_pred, raw_pmf = await asyncio.gather(pred_task, pmf_task)
                    print(f"[ripple-retry] Simulations completed for {thread_id}", flush=True)

                    pred = ripple._parse_spread_result(raw_pred)
                    pmf_result = ripple._parse_pmf_result(raw_pmf)
                except (RippleTimeoutError, TimeoutError):
                    logger.warning("Ripple retry timed out for %s", thread_id)
                    return
                except Exception as e:
                    print(
                        f"[ripple-retry] FAILED for {thread_id}: {type(e).__name__}: {e}",
                        flush=True,
                    )
                    return

                # Update workflow state with new Ripple results
                updates: dict[str, Any] = {}
                ripple_pred_data = pred.get("ripple_prediction")
                if ripple_pred_data:
                    updates["ripple_prediction"] = ripple_pred_data
                ripple_pmf_data = pmf_result.get("ripple_pmf")
                if ripple_pmf_data:
                    updates["ripple_pmf"] = ripple_pmf_data

                # Both succeeded — clear fallback flags
                if ripple_pred_data and ripple_pmf_data:
                    updates["ripple_reason"] = None
                    updates["ripple_fallback"] = None
                else:
                    reason = (
                        pred.get("ripple_reason")
                        or pmf_result.get("ripple_reason")
                        or "unreachable"
                    )
                    updates["ripple_reason"] = reason
                    updates["ripple_fallback"] = True

                if updates:
                    ripple_state = await graph.aget_state(config)
                    # P1a-S4-2: ripple_prediction/ripple_pmf are refable — the write
                    # must go through refify_updates (a bare inline write would be
                    # shadowed by a stale artifact ref on the next resolve). Fresh
                    # resolve gives refify the state the write lands on.
                    fresh_values = await resolve_state(store, thread_id, ripple_state.values or {})
                    refified = await refify_updates(
                        store, thread_id, updates, prev_values=fresh_values
                    )
                    await graph.aupdate_state(config, refified, as_node=_get_as_node(ripple_state))
                    print(
                        f"[ripple-retry] State updated for {thread_id}: {list(updates.keys())}",
                        flush=True,
                    )

        finally:
            # Identity-guarded, like publish-retry's: a newer retry may have
            # replaced this entry, and the old one must not pop the new one's.
            if _runner._detached_tasks.get(thread_id) is asyncio.current_task():
                _runner._detached_tasks.pop(thread_id, None)

    task = asyncio.create_task(_run_retry(), name=f"ripple-retry-{thread_id}")
    # Out-of-slot registry -- declaration and reasoning in _runner.py; §7.1.
    _runner._detached_tasks[thread_id] = task
    print(f"[ripple-retry] Task created for {thread_id}: {task.get_name()}", flush=True)

    return success(
        data={
            "thread_id": thread_id,
            "status": "retrying",
            "message": "Ripple 分析正在重新运行",
        }
    )


async def retry_publish(
    thread_id: str,
    request: Request,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """重试发布：用工作流现有内容重跑发布步骤，不重走创作链路。

    用于发布失败（status=failed/error）或试运行（mock_published）后手动重发。
    已发布的（status=published/success）拒绝，避免重复发笔记。
    P0-W4：status="unknown"（结果不明）先自动对账；对账确认已发布则不重发，
    对账不确定时拒绝重试，需请求体显式 {"force": true} 才继续（真实发布侧还有
    确定性 publish_id 幂等护栏兜底）。
    """
    if not thread_id or thread_id.strip() == "":
        raise ValidationError("thread_id", "thread_id cannot be empty")

    await assert_thread_owned(str(user["id"]), thread_id)

    graph = request.app.state.graph
    config = {"configurable": {"thread_id": thread_id}}

    from backend.state.artifacts import resolve_state

    store = getattr(graph, "store", None)
    state = await graph.aget_state(config)
    values = await resolve_state(store, thread_id, state.values)
    if not values or values.get("session_id") is None:
        raise WorkflowNotFoundError(thread_id)

    # Attribution for the refusal event; same reason as retry_ripple_analysis.
    account_id = str(values.get("account_id") or "")

    # 并发守卫：工作流正在跑（含正在重试）时不允许再触发。
    # 与状态推导不同，这里问的是"本进程要不要再起一份任务"——租约答的是"有没有人
    # 在跑"，两个方向都会错：租约写入是 best-effort，存储故障时会有"活任务却查不到
    # 租约"，据此放行就起第二份执行；反过来重启后死进程的租约在 TTL 内仍算活着，据此
    # 拒绝会让用户刚点的重试静默失效（200 但什么都没跑）。
    # 两条都钉在 tests/unit/api/test_serialization_guards_stay_local.py。
    has_active = _runner.process_has_active_task(thread_id)
    if has_active:
        return success(
            data={
                "thread_id": thread_id,
                "status": "skipped",
                "message": "工作流正在运行，无法重试。",
            }
        )

    copy = values.get("copy_content") or {}
    if not (copy.get("selected_title") or copy.get("body_text")):
        return success(
            data={
                "thread_id": thread_id,
                "status": "skipped",
                "message": "无法重试：缺少已生成的标题/正文内容。",
            }
        )

    pr = values.get("publish_result") or {}
    if not pr:
        return success(
            data={
                "thread_id": thread_id,
                "status": "skipped",
                "message": "无法重试：工作流尚未到达发布步骤。",
            }
        )

    pr_status = pr.get("status")
    # 已发布的工作流不允许重试——防止在小红书重复发笔记
    if pr_status in ("published", "success"):
        return success(
            data={
                "thread_id": thread_id,
                "status": "skipped",
                "message": "该笔记已发布，不允许重复发布。",
            }
        )

    # P0-W4: status="unknown"（提交后超时等结果不明）的重试必须先对账；对账
    # 不确定时要求请求体显式 force=true 才继续——盲目重发可能产生重复笔记。
    body: dict[str, Any] = (
        await request.json()
        if request.headers.get("content-type", "").startswith("application/json")
        else {}
    )
    force_retry = bool(body.get("force"))
    if pr_status == "unknown":
        reconciled = await reconcile_unknown_publish(values, request.app.state.graph.store)
        gate = evaluate_unknown_publish_retry(pr_status, force_retry, reconciled)
        if gate is not None:
            return success(
                data={
                    "thread_id": thread_id,
                    **gate,
                }
            )
        # 显式 force：把人工决定落到 publish_options.force_publish，run_publish
        # 的幂等护栏据此放行（并重新记录本次尝试）。
        await graph.aupdate_state(
            config,
            {
                "publish_options": {
                    **(values.get("publish_options") or {}),
                    "force_publish": True,
                }
            },
            as_node=_get_as_node(state),
        )

    def _emit_retry_event(tid: str, publish_result: dict[str, Any]) -> None:
        bus = EventBusService.get_instance()
        status = publish_result.get("status", "unknown")
        bus.emit(
            EventType.WORKFLOW_AGENT_STARTED,
            thread_id=tid,
            payload={"agent": "publisher", "retry": True},
        )
        bus.emit(
            EventType.WORKFLOW_AGENT_COMPLETED,
            thread_id=tid,
            payload={"agent": "publisher", "status": status, "retry": True},
        )
        bus.emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=tid,
            payload={"publish_result": publish_result, "retry": True},
        )

    async def _run_publish_retry() -> None:
        # 取租约：见 _run_retry 的同段注释（同一个 helper、同一条规则）。
        async with _execution_lease(thread_id) as lease:
            try:
                if lease.outcome is AcquireOutcome.HELD_BY_LIVE_OWNER:
                    # 同一个理由，代价更高：publisher 是唯一的不可逆节点，第二个
                    # 写者在这里意味着重复发一篇笔记。检查放在 try 内是为了让下面
                    # 的 finally 仍然把 _background_tasks 里那条已完成的条目摘掉。
                    await _record_lease_refusal(
                        thread_id, path="publish-retry", account_id=account_id
                    )
                    return
                snap = await graph.aget_state(config)
                # Read seam: run_publish hashes copy_content/visual_plan subfields
                # for the publish_id — a ref'd thread must feed it the resolved
                # bodies, not the checkpoint's ref-only view.
                resolved = await resolve_state(
                    getattr(graph, "store", None), thread_id, snap.values
                )
                result = await run_publish(resolved, graph.store)
                publish_result = result["publish_result"]
                snap = await graph.aget_state(config)
                await graph.aupdate_state(
                    config,
                    {
                        "publish_result": publish_result,
                        "phase": WorkflowPhase.PUBLISHING,
                        # P0-W4 (F3): run_publish consumes an explicit force one
                        # shot and returns the cleared options — write them back so
                        # the next publish on this thread is guarded again.
                        **(
                            {"publish_options": result["publish_options"]}
                            if result.get("publish_options") is not None
                            else {}
                        ),
                    },
                    as_node=_get_as_node(snap),
                )
                # ponytail: 真实 XHS 发布成功只 redirect 到 success 页，post_id 从 URL
                # regex 提取，常为空（line 620）。用 status=="published" 判成功，非 post_id。
                pub_ok = publish_result.get("status") == "published"
                await _db_upsert(
                    thread_id,
                    status="completed" if pub_ok else "error",
                    phase=WorkflowPhase.PUBLISHING.value,
                    error=None if pub_ok else publish_result.get("error"),
                )
                _emit_retry_event(thread_id, publish_result)
            except Exception:
                logger.exception("publish-retry failed for %s", thread_id)
            finally:
                if _runner._background_tasks.get(thread_id) is asyncio.current_task():
                    _runner._background_tasks.pop(thread_id, None)

    task = asyncio.create_task(_run_publish_retry(), name=f"publish-retry-{thread_id}")
    task.add_done_callback(_on_task_done(thread_id))
    _runner._background_tasks[thread_id] = task

    return success(
        data={
            "thread_id": thread_id,
            "status": "retrying",
            "message": "正在重新发布",
        }
    )
