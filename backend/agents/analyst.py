"""Analyst agent — reads engagement data, generates insights, with Ripple report integration.

P1b-S4 迁移第五批销号（consumer-map §六.5，creative_ctx 类批之 analyst）：
content_history recall 走 S2 管线（RetrievalResult.mode 降级信号 +
kind=context 事件面），``raw_items`` 还原原始记录列表使 user_msg 内
``历史数据：{history}`` 的 list repr 逐字节等价（D3'）；system prompt
组装接 ContextCompiler.compile_prompt（本 YAML 无占位符，整段 L0）。

P1d-S2b：分析报告迁到 ``_llm_structured`` + ``AnalyticsOutput``。
只接 ``StructuredOutputError``（分析做不出来 = 业务结果，空快照继续），
「一次都没问到」原样上抛 —— 见 ``execute`` 内注释。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.context.compiler import ContextCompiler
from backend.context.models import RetrievalMode, RetrievalResult, RunContext, require_niche
from backend.context.retrieval import RecallRequest, recall_namespaces
from backend.memory.hy.promotion import evaluate_outcome_gate, memory_metadata
from backend.memory.hy.recall import format_hy_section, recall_hy_memory
from backend.models.outputs import AnalyticsOutput, normalize_analytics
from backend.models.structured import StructuredOutputError
from backend.services.memory_chain import memory_chain_enabled
from backend.state.schema import WorkflowPhase, XHSGrowthState
from backend.tools.runtime.models import ErrorKind

if TYPE_CHECKING:
    # MemoryManager pulled lazily inside execute() to avoid import cycles;
    # needed here only for the _safe_store_* helper annotations.
    from backend.memory.store import MemoryManager

logger = logging.getLogger("xhs_growth.agents.analyst")

_compiler = ContextCompiler()


async def _recall_history(
    store: BaseStore | None, account_id: str, thread_id: str
) -> RetrievalResult:
    """content_history recall through the S2 pipeline (D6').

    Same namespace / query / limit as the pre-migration ``_recall_memory``
    call; a store failure now degrades with an explicit ``mode`` instead of
    silently returning ``[]``, and — with a ``thread_id`` — lands in the
    workflow_events tier as ``kind="context"``.
    """
    if store is None:
        return RetrievalResult(
            namespace="content_history",
            mode=RetrievalMode.DEGRADED,
            error="store_unavailable",
        )
    results = await recall_namespaces(
        store,
        account_id=account_id,
        requests=[
            RecallRequest(namespace="content_history", query="content performance", limit=10)
        ],
        thread_id=thread_id,
        emit_events=True,
    )
    return results["content_history"]


def _format_history(result: RetrievalResult) -> list[dict[str, Any]]:
    """History records for the user_msg list repr, format identical to the
    pre-migration block (分段等价): the raw store records themselves —
    ``raw_items`` mirrors ``item.value`` so ``{history}`` renders the same
    ``[{...}, ...]`` repr. EMPTY/DEGRADED renders as ``[]`` (the old
    swallow-and-return-``[]`` text), except the degradation is now visible
    as a ``mode`` (and a workflow_events entry).
    """
    if result.mode is RetrievalMode.HIT and result.raw_items:
        return list(result.raw_items)
    return []


async def _safe_evolve(account_id: object) -> None:
    """Fire-and-forget wrapper: run maybe_evolve, swallow all errors.

    Scheduled via asyncio.create_task after backfill_engagement, so its
    exceptions would otherwise escape to the event loop. maybe_evolve is
    already non-blocking internally; this just guarantees no stray traceback.
    """
    try:
        from backend.db.evaluator_config import maybe_evolve

        await maybe_evolve(account_id if isinstance(account_id, str) else None)
    except Exception as e:
        logger.debug("evaluator auto-evolve failed (non-blocking): %s", e)


async def _safe_store_insight(
    mm: MemoryManager, store: BaseStore, insight: str, post_id: str, account_id: str = ""
) -> None:
    """Per-row write wrapper: store one insight, swallow errors.

    Write-gather variant (#512): store_insight is a bare store.aput call with
    no internal try/except, so without this wrapper the first failing write
    would abort the rest of the gather. Best-effort post-publish telemetry —
    losing one insight shouldn't skip the others.

    台账 #99：开关打开且给了账号时，先过记忆写入链路。``PROFILE``（不确定信号）
    只进候诊室、不进长期记忆 —— 一次数据抖动不该变成下周的可执行结论；
    路由本身失败时退回既有的「照常写」，不让新链路成为新的故障点。
    """
    if account_id and memory_chain_enabled():
        try:
            from backend.services.memory_chain import record_observation

            route = await record_observation(
                store, account_id, observation=insight, kind="insight", source="analyst"
            )
        except Exception:
            logger.warning("memory chain routing failed; storing insight directly", exc_info=True)
        else:
            if not route.stored:
                logger.debug(
                    "insight parked in waiting room (surprisal=%.2f, hypothesis=%s)",
                    route.surprisal,
                    route.hypothesis_id,
                )
                return
    try:
        await mm.store_insight(store, insight, {"source": "analyst", "post_id": post_id})
    except Exception:
        logger.warning("store_insight failed", exc_info=True)


async def _safe_record_visual_feedback(
    store: BaseStore,
    account_id: str,
    niche: str,
    *,
    collect_ratio: float | None,
    view_ratio: float | None,
    sample_size: int,
) -> None:
    """#45 write side: move one scene weight with a baseline-relative outcome.

    Best-effort: the visual-memory write must never break the analytics node.
    ``record_scene_feedback_if_enabled`` itself refuses to move a weight when
    there is no baseline or too few samples, so this wrapper only owns the
    error boundary.
    """
    from backend.services.visual_memory import record_scene_feedback_if_enabled, scene_for

    try:
        await record_scene_feedback_if_enabled(
            store,
            account_id,
            scene_for(niche=niche),
            collect_ratio=collect_ratio,
            view_ratio=view_ratio,
            sample_size=sample_size,
        )
    except Exception:  # pragma: no cover - defensive store boundary
        logger.warning("visual memory feedback skipped", exc_info=True)


async def _safe_store_strategy_note(mm: MemoryManager, store: BaseStore, rec: str) -> None:
    """Per-row write wrapper: store one strategy note, swallow errors.

    See _safe_store_insight — same rationale (bare aput, best-effort telemetry).
    """
    try:
        await mm.store_strategy_note(store, rec, {"source": "analyst"})
    except Exception:
        logger.warning("store_strategy_note failed", exc_info=True)


async def _safe_remember_hy(account_id: str, text: str, *, metadata: dict[str, Any]) -> None:
    """hy-memory 双写包装：单条写入失败不影响同批其余写入，也不炸节点。

    与 _safe_store_insight 同一纪律（best-effort telemetry），但目标换成
    hy-memory working 场景。功能关闭时 bridge.remember 直接返回 None，
    这里连日志都不打（避免关闭状态下每次复盘都刷 warning）。
    """
    try:
        from backend.memory.hy.bridge import get_hy_memory_bridge

        bridge = get_hy_memory_bridge()
        if not bridge.enabled:
            return
        result = await bridge.remember(
            text, account_id=account_id, scene="working", metadata=metadata
        )
        if result is None:
            logger.debug("hy-memory remember returned None (degraded)")
    except Exception:
        logger.warning("hy-memory remember failed", exc_info=True)


async def _safe_store_pitfall(
    mm: MemoryManager, store: BaseStore, pitfall: str, data: dict[str, Any]
) -> None:
    """Per-row write wrapper for the negative pitfalls pool; swallow errors."""
    try:
        await mm.store_negative_pitfall(store, pitfall, data)
    except Exception:
        logger.warning("store_negative_pitfall failed", exc_info=True)


def _learning_signal_approved(state: XHSGrowthState) -> bool:
    """A reviewer can explicitly bless a lesson even when metrics are weak.

    Kept deliberately narrow: only an explicit boolean on ``human_feedback``
    counts. A low-risk auto-approval of the *content* is not a learning signal.
    """
    feedback = state.get("human_feedback") or {}
    return bool(
        feedback.get("approve_learning")
        or feedback.get("learning_signal_approved")
        or feedback.get("promote_learning")
    )


def _hy_learning_allowed(outcome_gate: Any) -> bool:
    """Whether the lesson may enter the positive working-memory pool.

    New accounts have no baseline yet; blocking every write would defeat the
    cold start. Those writes are tagged ``unverified_cold_start`` so they stay
    auditable, while a measured below-baseline note never becomes a positive
    working experience.
    """
    return bool(outcome_gate.allowed or outcome_gate.reason == "insufficient_history")


class AnalystAgent(BaseAgent):
    task_type = TaskType.ANALYSIS
    agent_name = "analyst"
    prompt_file = "analyst.yaml"
    tool_capabilities = ("ripple.get_report",)

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        self._reset_llm_perf()
        account_id = state.get("account_id", "default")
        thread_id = str(state.get("session_id") or "")
        publish_result = state.get("publish_result", {})

        niche = require_niche(state)
        # hy-memory 召回（chat 画像 + working 经验）与下面的 memory+ripple
        # gather 并发：先 ensure_future 建 task（立即开跑），主 gather 保持
        # 2-awaitable 形状不变（既有测试以该形状钉并发契约）。功能关闭时
        # recall_hy_memory 立即返回 EMPTY，零成本；recall_hy_memory 契约
        # 永不抛，故主 gather 万一失败时无需 finally 回收该 task。
        hy_recall_task = asyncio.ensure_future(
            asyncio.gather(
                recall_hy_memory(
                    f"{niche} 账号偏好与受众画像", account_id=account_id, scene="chat"
                ),
                recall_hy_memory(
                    f"{niche} 内容运营经验 数据复盘", account_id=account_id, scene="working"
                ),
            )
        )
        # 召回历史数据 + 获取 Ripple 报告（并发：memory RTT 隐藏在 Ripple 长轮询后）。
        # recall 走 S2 管线（降级信号 + kind=context 事件面），并发契约不变。
        history_result, ripple_report = await asyncio.gather(
            _recall_history(store, account_id, thread_id),
            self._ripple_report(state),
        )
        hy_chat, hy_working = await hy_recall_task
        history = _format_history(history_result)

        # Outcome-Verified Epistemic Gate: only a note that beat the account's
        # recent median (or a human-approved learning signal) may promote its
        # lesson to a verified pattern. Everything else still gets recorded,
        # but in the negative pitfalls pool.
        history_records = [
            item for item in (history_result.raw_items or ()) if isinstance(item, dict)
        ]
        outcome_gate = evaluate_outcome_gate(
            publish_result,
            history_records,
            human_approved=_learning_signal_approved(state),
        )
        gate_metadata = memory_metadata(outcome_gate)
        if outcome_gate.reason == "insufficient_history":
            gate_metadata = {
                **gate_metadata,
                "verification": "unverified_cold_start",
                "memory_pool": "working_unverified",
            }

        # 台账 #45：视觉记忆的场景权重只在真实数据与账号基线可比时移动；
        # 无基线/样本不足时 record_scene_feedback 直接跳过，写失败也不影响分析。
        await _safe_record_visual_feedback(
            store,
            account_id,
            niche,
            collect_ratio=outcome_gate.collect_ratio,
            view_ratio=outcome_gate.view_ratio,
            sample_size=outcome_gate.sample_size,
        )

        hy_context = format_hy_section([hy_chat, hy_working])

        run_context = RunContext(
            thread_id=thread_id,
            account_id=account_id,
            niche=niche,
            values=state,
            tool_schema=self.tool_schema_layer(),
        )
        system_prompt = _compiler.compile_prompt(
            run_context, self.prompt_template["system"]
        ).render()

        ripple_context = ""
        if ripple_report:
            ripple_context = f"\nRipple 传播预测报告：\n{ripple_report}\n"

        user_msg = f"""帖子数据：{publish_result}
历史数据：{history}
账号定位：{account_id}
垂类赛道：{niche}{ripple_context}{hy_context}"""

        # P1d-S2b: 分析报告走结构化链。只接 ``StructuredOutputError`` ——
        # 「问过了、每一档都没给出可用产物」是一次分析做不出来，属业务结果，降级成
        # 空快照继续跑。而「一次都没问到」（LLM 完全不可用）必须原样上抛：空快照带
        # 着 engagement_rate=0.0 / views=0 会进 state 与报表，看起来正好像一次真实
        # 的零表现 —— 与 P1c 的「全零不是数据」同一条纪律，宁可让节点失败。
        try:
            analytics_output = await self._llm_structured(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_msg),
                ],
                AnalyticsOutput,
            )
        except StructuredOutputError as exc:
            logger.warning(
                "%s: no usable analytics payload (%d attempt(s)); recording an empty snapshot",
                self.agent_name,
                len(exc.attempts),
            )
            analytics_output = AnalyticsOutput()

        analytics = normalize_analytics(analytics_output)

        # 将 Ripple 预测与实际数据对比，写入 state
        result_updates: dict[str, Any] = {
            "analytics": analytics,
            "phase": WorkflowPhase.ANALYZING,
        }

        ripple_prediction = state.get("content_plan", {}).get("ripple_prediction")
        ripple_comparison: dict[str, Any] | None = None
        if ripple_prediction:
            ripple_comparison = self._compare_prediction_vs_actual(
                cast(dict[str, Any] | None, ripple_prediction),
                cast(dict[str, Any], publish_result),
            )
            if ripple_comparison:
                analytics["ripple_comparison"] = ripple_comparison
                result_updates["ripple_comparison"] = ripple_comparison

                # 将校准洞察存入原有记忆（保持兼容）
                calibration = ripple_comparison.get("calibration_insight", "")
                if calibration:
                    from backend.memory.store import MemoryManager

                    mm = MemoryManager(account_id)
                    await mm.store_insight(
                        store,
                        f"Ripple 校准: {calibration}",
                        {"source": "analyst", "type": "ripple_calibration"},
                    )

        # 将洞察存入原有记忆（保持兼容）— gather 并发写入，per-row 隔离
        # （写-gather 变体 #512：store_insight/store_strategy_note 是裸 aput 调用，
        # 不吞异常 → _safe_* 包装每行 try/except，部分失败不再中断其余写入）
        from backend.memory.store import MemoryManager

        mm = MemoryManager(account_id)
        post_id = publish_result.get("post_id", "")
        insights = analytics.get("insights", [])
        recommendations = analytics.get("recommendations", [])
        await asyncio.gather(
            *(_safe_store_insight(mm, store, insight, post_id, account_id) for insight in insights),
            *(_safe_store_strategy_note(mm, store, rec) for rec in recommendations),
            # 低表现笔记的复盘不进正向记忆：同一批洞察/建议改存负向避坑池，
            # 避免把一次偶然低表现（或高表现）固化成长期规则。
            *(
                _safe_store_pitfall(
                    mm,
                    store,
                    f"[{niche}] 低表现避坑（帖子 {post_id or 'unknown'}）：{insight}",
                    {
                        "source": "analyst",
                        "post_id": post_id,
                        "niche": niche,
                        "outcome_gate": outcome_gate.as_dict(),
                    },
                )
                for insight in insights
                if not outcome_gate.allowed
            ),
            # hy-memory 双写（best-effort）：洞察/策略建议进 working 场景，
            # 让 SDK 的 facts/experiences 两层在后续会话可复用。功能关闭时
            # remember 立即返回 None，与既有写入完全并发不互相阻塞。
            *(
                _safe_remember_hy(
                    account_id,
                    f"[{niche}] 复盘洞察（帖子 {post_id or 'unknown'}）：{insight}",
                    metadata={
                        "kind": "insight",
                        "post_id": post_id,
                        "niche": niche,
                        **gate_metadata,
                    },
                )
                for insight in insights
                if _hy_learning_allowed(outcome_gate)
            ),
            *(
                _safe_remember_hy(
                    account_id,
                    f"[{niche}] 运营策略建议：{rec}",
                    metadata={"kind": "strategy_note", "niche": niche, **gate_metadata},
                )
                for rec in recommendations
                if _hy_learning_allowed(outcome_gate)
            ),
        )

        # ── Update content history with actual engagement metrics ──
        post_id = publish_result.get("post_id", "")
        if post_id:
            try:
                existing = await store.aget(mm.content_history_ns, key=post_id)
                if existing:
                    record = existing.value
                    record["views"] = publish_result.get(
                        "views", publish_result.get("impressions", 0)
                    )
                    record["likes"] = publish_result.get("likes", 0)
                    record["collects"] = publish_result.get(
                        "collects", publish_result.get("bookmarks", 0)
                    )
                    record["comments"] = publish_result.get("comments", 0)
                    record["shares"] = publish_result.get("shares", 0)
                    record_views = record["views"] or 0
                    if record_views > 0:
                        total_engagement = (
                            (record.get("likes", 0) or 0)
                            + (record.get("collects", 0) or 0)
                            + (record.get("comments", 0) or 0)
                            + (record.get("shares", 0) or 0)
                        )
                        record["engagement_rate"] = round(total_engagement / record_views, 4)
                    await store.aput(mm.content_history_ns, key=post_id, value=record)
            except Exception as e:
                logger.warning(f"更新内容历史互动数据失败: {e}")

        # ── Back-fill real engagement onto the evaluator's training sample ──
        # ponytail: weak label for grader finetuning — attaches real engagement
        # to the evaluator judgment sample. Non-blocking.
        #
        # The numbers have to come from ``creator_note_stats``, which is why the
        # selection below is a no-op today: ``publisher.py`` writes no metric key
        # into ``publish_result``, so a publish-time read has nothing to hand
        # over and ``backfill_engagement`` is never reached.  Registered in
        # ``tests/unit/db/test_weak_label_contract.py`` instead of being left to
        # read as working code; the real numbers arrive through the sync path.
        if thread_id:
            try:
                from backend.db.evaluator_config import backfill_engagement, build_weak_label
                from backend.db.pool import is_pool_ready

                if is_pool_ready():
                    engagement = build_weak_label(publish_result)
                    if engagement:
                        await backfill_engagement(thread_id, engagement)
                        # ── Online co-evolution (RQGM epoch boundary) ──
                        # New feedback arrived → fire-and-forget a check whether
                        # enough samples accrued to refit weights / advance the
                        # prompt epoch. Never blocks the publish path.
                        # ponytail: create_task; _safe_evolve swallows all errors
                        # and maybe_evolve is re-entry-guarded per account.
                        asyncio.create_task(_safe_evolve(state.get("account_id")))  # noqa: RUF006
            except Exception as e:
                logger.debug(f"样本 engagement 回灌失败 (non-blocking): {e}")

        # ── Creative Memory: 输出 calibration_payload（异步回写）──
        from backend.memory.calibrator import build_calibration_payload, schedule_calibration

        actual_engagement_rate = 0.0
        actual_save_rate = 0.0
        if ripple_comparison:
            actual_engagement_rate = ripple_comparison.get("actual_engagement_rate", 0.0)
        actual_collects: int = publish_result.get("collects", publish_result.get("bookmarks", 0))  # type: ignore[assignment]
        actual_views: int = publish_result.get("views", publish_result.get("impressions", 0))  # type: ignore[assignment]
        if actual_views > 0:
            actual_save_rate = actual_collects / actual_views

        calibration_payload = build_calibration_payload(
            state,  # type: ignore[arg-type]
            actual_engagement_rate,
            actual_save_rate,
        )
        result_updates["calibration_payload"] = calibration_payload

        # 异步回写（不阻塞主流程）
        if store is not None:
            await schedule_calibration(store, calibration_payload)

        return result_updates

    async def _ripple_report(self, state: XHSGrowthState) -> str | None:
        """尝试获取 Ripple 模拟报告

        P1c-S3c: 经 Tool Gateway 调用。等待预算声明在能力上
        （``ripple.get_report`` → ``timeout_s=120``），调用点不再自己包一层
        ``asyncio.wait_for`` —— 否则超时策略会有两个可能打架的出处。
        """
        ripple_prediction = state.get("content_plan", {}).get("ripple_prediction", {})
        job_id = (
            ripple_prediction.get("ripple_job_id") if isinstance(ripple_prediction, dict) else None
        )

        if not job_id:
            return None

        result = await self.tools.invoke("ripple.get_report", {"job_id": job_id})

        if not result.ok:
            logger.warning(f"Ripple report retrieval skipped: {result.error}")
            # 只有超时才是"模拟还在跑"，这时取消任务才有意义。判断依据是
            # error_kind 而不是错误文本 —— 普通失败不代表任务还在跑，取消它没有意义。
            if result.error_kind is ErrorKind.TIMEOUT:
                await self._ripple_cancel(job_id)
            return None

        report = result.value
        if not isinstance(report, dict):
            return None

        rounds = report.get("rounds", [])
        return "\n".join(r.get("content", r.get("text", str(r))) for r in rounds)

    async def _ripple_cancel(self, job_id: str) -> None:
        """尝试取消 Ripple 模拟任务（报告超时时调用）"""
        if not job_id:
            return

        try:
            from backend.services.ripple_service import RippleService

            service = RippleService.get_instance()
            result = await service.cancel_simulation(job_id)
            logger.info(f"Ripple cancel result for {job_id}: {result}")

        except Exception as e:
            logger.warning(f"Ripple cancel failed for {job_id}: {e}")

    def _compare_prediction_vs_actual(
        self, prediction: dict[str, Any] | None, actual: dict[str, Any]
    ) -> dict[str, Any]:
        """对比 Ripple 预测与实际表现，生成可行动的校准洞察"""
        if not prediction:
            return {}

        predicted_reach = prediction.get("estimated_reach", 0)
        predicted_engagement = prediction.get("estimated_engagement", 0)
        predicted_viral_prob = prediction.get("viral_probability", 0.0)

        # 从 publish_result 提取实际数据
        actual_views = actual.get("views", actual.get("impressions", 0))
        actual_likes = actual.get("likes", 0)
        actual_collects = actual.get("collects", actual.get("bookmarks", 0))
        actual_comments = actual.get("comments", 0)
        actual_shares = actual.get("shares", 0)
        actual_engagement_total = actual_likes + actual_collects + actual_comments + actual_shares
        actual_engagement_rate = actual.get(
            "engagement_rate",
            (actual_engagement_total / actual_views) if actual_views > 0 else 0.0,
        )

        # 计算偏差率
        reach_deviation = 0.0
        if predicted_reach > 0:
            reach_deviation = (actual_views - predicted_reach) / predicted_reach

        engagement_deviation = 0.0
        if predicted_engagement > 0:
            engagement_deviation = (
                actual_engagement_total - predicted_engagement
            ) / predicted_engagement

        # 评级
        if abs(reach_deviation) <= 0.3:
            accuracy_rating = "准确"
        elif reach_deviation > 0.3:
            accuracy_rating = "低估"
        else:
            accuracy_rating = "高估"

        # 生成校准洞察
        calibration_parts = []
        if accuracy_rating == "低估":
            calibration_parts.append(
                f"Ripple 低估了实际触达 {abs(reach_deviation):.0%}，"
                f"说明该内容类型/话题的传播力超出模型预期"
            )
        elif accuracy_rating == "高估":
            calibration_parts.append(
                f"Ripple 高估了实际触达 {abs(reach_deviation):.0%}，说明内容在分发/互动环节存在瓶颈"
            )
        else:
            calibration_parts.append("Ripple 预测与实际表现基本吻合")

        if predicted_viral_prob > 0.5 and actual_engagement_rate < 0.02:
            calibration_parts.append("高爆发概率但实际互动率偏低，可能标题党效应或受众不匹配")
        elif predicted_viral_prob < 0.3 and actual_engagement_rate > 0.05:
            calibration_parts.append("低爆发概率但实际互动率出色，该内容模式值得复用")

        return {
            "predicted_reach": predicted_reach,
            "predicted_engagement": predicted_engagement,
            "predicted_viral_prob": predicted_viral_prob,
            "actual_views": actual_views,
            "actual_engagement_total": actual_engagement_total,
            "actual_engagement_rate": actual_engagement_rate,
            "reach_deviation": round(reach_deviation, 3),
            "engagement_deviation": round(engagement_deviation, 3),
            "accuracy_rating": accuracy_rating,
            "calibration_insight": "；".join(calibration_parts),
        }
