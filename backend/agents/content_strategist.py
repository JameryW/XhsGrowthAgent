"""Content Strategist agent — selects topics and plans content, with Ripple spread prediction.

P1b-S4 迁移第三个销号 agent（consumer-map §六.3）：performance_insights
recall 走 S2 管线（RetrievalResult.mode 降级信号 + kind=context 事件面），
prompt 组装走 ContextCompiler.compile_prompt（YAML 分段 schema，
`<!-- ctx:l4_memory -->` 标记替代 {memory_context} 占位符）。三个拼装点
（主 prompt / 漂移纠偏 retry / 低传播 retry）各自以对应 L4 文本编译；
`{ripple_context}` 占位符按 consumer-map 暂保留 post-render .replace
（P1b 不动）。分段等价口径（info.md D3'）：L0 policy 文本逐字不变，
L4 段内容集合与迁移前相等（层序渲染到 L0 尾部）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.config.settings import Settings
from backend.context.compiler import ContextCompiler
from backend.context.models import (
    ContextItem,
    PromptLayer,
    RetrievalMode,
    RetrievalResult,
    RunContext,
    require_niche,
)
from backend.context.retrieval import RecallRequest, recall_namespaces
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState
from backend.tools.runtime.models import ErrorKind, ToolResult

logger = logging.getLogger("xhs_growth.agents.content_strategist")

_compiler = ContextCompiler()

# Ripple workflow wait timeout (seconds). Real jobs commonly exceed 900s.
_DEFAULT_RIPPLE_TIMEOUT = 1800


@dataclass(frozen=True)
class _RippleCall:
    """One Ripple capability call, read in the terms the call sites branch on.

    Ripple answers in a vocabulary of its own — a prediction, or "still
    running, job id X", or "service unavailable" — and both call sites (the
    blocking path in :meth:`execute` and the background task) have to read it
    the same way. Reading it *once*, here, is what retires the marker the old
    code used: success was recognised by the **absence** of a
    ``"ripple_reason"`` key, so the meaning lived in a missing key and every
    site re-derived it (and one of them got it wrong — a zeroed fallback body
    read as a genuine forecast).
    """

    data: dict[str, Any] = field(default_factory=dict)
    """The body to store, already in the shape callers store it."""
    reason: str = ""
    """``""`` when ok; otherwise ``timeout`` / ``unavailable`` / ``skipped``."""
    job_id: str = ""
    """The simulation id, on success *and* on timeout (``""`` if unknown)."""

    @property
    def ok(self) -> bool:
        """Whether a body came back.

        Derived from ``data`` rather than stored beside it: a call that
        produced a body succeeded and there is no third state, so a field of
        its own could only ever disagree with the payload it describes.
        Failure is what you get by naming a reason, which is the safe default.
        """
        return bool(self.data)

    @classmethod
    def read(cls, result: ToolResult, *, body_key: str) -> _RippleCall:
        """Read one Gateway result in Ripple's terms.

        Everything that is not a usable body reads as a failure, and the two
        failures the caller can act on differently are told apart by the
        runtime's own vocabulary rather than by inspecting strings: a domain
        outcome with ``reason="timeout"`` carries a job id worth cancelling or
        resuming, while everything else (degraded service, Gateway timeout,
        tool exception) leaves nothing to recover.
        """
        if result.ok:
            envelope = result.value if isinstance(result.value, Mapping) else {}
            body = envelope.get(body_key)
            if isinstance(body, Mapping) and body:
                return cls(data=dict(body), job_id=str(envelope.get("ripple_job_id", "")))
            # A call that succeeded at producing no body is not a prediction.
            return cls(reason="unavailable")
        if result.error_kind is ErrorKind.DOMAIN and result.domain.get("reason") == "timeout":
            return cls(reason="timeout", job_id=str(result.domain.get("ripple_job_id", "")))
        return cls(reason="unavailable")


async def _recall_insights(
    store: BaseStore | None, account_id: str, thread_id: str
) -> RetrievalResult:
    """performance_insights recall through the S2 pipeline (D6').

    Same namespace / query / limit as the pre-migration ``_recall_memory``
    call; a store failure now degrades with an explicit ``mode`` instead of
    silently returning ``[]``, and — with a ``thread_id`` — lands in the
    workflow_events tier as ``kind="context"``.
    """
    if store is None:
        return RetrievalResult(
            namespace="performance_insights",
            mode=RetrievalMode.DEGRADED,
            error="store_unavailable",
        )
    results = await recall_namespaces(
        store,
        account_id=account_id,
        requests=[
            RecallRequest(namespace="performance_insights", query="content strategy", limit=5)
        ],
        thread_id=thread_id,
        emit_events=True,
    )
    return results["performance_insights"]


def _format_memory_context(result: RetrievalResult) -> str:
    """L4 text, format identical to the pre-migration block (分段等价)."""
    if result.mode is RetrievalMode.HIT and result.items:
        text = "\n历史表现洞察：\n"
        for item in result.items:
            text += f"- {item.body}\n"
        return text
    return ""


class ContentStrategistAgent(BaseAgent):
    task_type = TaskType.STRATEGY
    agent_name = "content_strategist"
    prompt_file = "content_strategist.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        self._reset_llm_perf()
        account_id = state.get("account_id", "default")
        thread_id = state.get("session_id")

        # ── Creative Memory: 读取 ──
        from backend.memory.creative import CreativeMemory

        cm = CreativeMemory(account_id, store=store)
        niche = require_niche(state)
        # 4 independent read-only recalls with disjoint sources → one
        # concurrent wave instead of 4 serial ones. CreativeMemory recalls
        # swallow their own exceptions internally; the pipeline recall carries
        # explicit degradation modes (same arity as pre-migration: 3 cm
        # recalls + 1 batched-ns pipeline helper).
        styles, plays, benchmark, insights_result = await asyncio.gather(
            cm.recall_style(query=f"content strategy {niche}"),
            cm.recall_plays(condition="content strategy", niche=niche),
            cm.recall_benchmark(niche),
            _recall_insights(store, account_id, str(thread_id or "")),
        )
        memory_context = _format_memory_context(insights_result)

        # 拼接 creative memory 上下文
        creative_ctx = cm.build_creative_context(styles, plays, [], benchmark)
        if creative_ctx:
            memory_context += f"\n{creative_ctx}"

        # 创作者中心导入数据建议（trend 模式选题策略）
        try:
            from backend.services.creator_stats.suggestions import build_mode_creative_context

            stats_ctx = await build_mode_creative_context(account_id, "trend", store=store)
            if stats_ctx:
                memory_context += f"\n{stats_ctx}"
        except Exception as e:
            logger.debug("creator_stats suggestions skipped: %s", e)

        # 先用基础 prompt 生成初版策略（暂无 Ripple 数据）。topic 打分在下方
        # 追加进 L4 文本后才编译——旧路径在此处的首次 _build_system_prompt 构建是
        # 死代码（构建结果立即被 104 行重建覆盖），迁移后不再保留。
        trend_data: dict[str, Any] = cast(dict[str, Any], state.get("trend_data", {}))

        # User-provided topic override. Stored in state["topic"] by /workflow/start
        # but previously dead data — no agent read it, and the drift-guard below
        # actively pulled the LLM back to the trend candidate set. When set, the
        # user's topic becomes the selection core; trend data degrades to a
        # "borrow momentum / angle reference" and the candidate-set guard is skipped.
        user_topic = str(state.get("topic") or "").strip()

        # ponytail: 对候选话题打分（topic_scorer 已注册但此前从未调用——死代码）
        # 评分结果拼入 extra_context，让 LLM 基于热度/增长/竞争度选话题。
        # topic_scorer 内部已处理实时数据不可用降级（返回 heat_score=50），此处只透传。
        topic_scores_ctx = await self._score_trend_topics(trend_data, niche)
        if topic_scores_ctx:
            memory_context += f"\n{topic_scores_ctx}"
        # When the user pinned a topic, inject the user-topic branch so the
        # hard constraint (select from trend candidates) is lifted for this turn.
        if user_topic:
            memory_context = (
                f"\n【用户指定主题】{user_topic}"
                "\n用户已明确指定选题主题。selected_topic 必须围绕该用户主题为核心，"
                "趋势数据仅作为借势角度与热点参考，不得用候选话题替换用户主题。" + memory_context
            )
        system_prompt = self._compile_system_prompt(
            state,
            thread_id=str(thread_id or ""),
            account_id=account_id,
            niche=niche,
            l4_extra=memory_context,
        )
        system_prompt = system_prompt.replace("{ripple_context}", "")

        user_msg = f"""趋势数据：{trend_data}
账号定位：{account_id}
垂类赛道：{niche}
用户指定主题：{user_topic or "（未指定，从趋势候选中选取）"}
历史表现洞察：{memory_context}"""

        response = await self._llm_ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        llm_content = response.content
        if isinstance(llm_content, list):
            llm_content = str(llm_content)
        content_plan = self._parse_json_response(llm_content)

        # ponytail: 主题漂移防护——selected_topic 必须落在候选集内
        # 偏离则带 hint 重生成一次。候选为空时跳过（prompt 已指示输出空）。
        # 用户指定主题时跳过纠偏：用户主题是 selected_topic 核心，不在候选集是预期而非漂移。
        candidates = self._extract_candidate_topics(trend_data)
        if user_topic:
            logger.info(
                f"user topic override active: '{user_topic}' — skipping candidate-set drift guard"
            )
        elif candidates and content_plan.get("selected_topic") not in candidates:
            chosen = content_plan.get("selected_topic", "")
            logger.info(f"selected_topic '{chosen}' 不在候选集，触发重生成")
            retry_prompt = self._compile_system_prompt(
                state,
                thread_id=str(thread_id or ""),
                account_id=account_id,
                niche=niche,
                l4_extra=memory_context
                + f"\n【纠偏】上一次输出的 selected_topic='{chosen}' 不在候选话题内。"
                f"候选话题为：{candidates}。必须从中选取一个，不得自创或改写措辞。",
            )
            retry_prompt = retry_prompt.replace("{ripple_context}", "")
            retry_response = await self._llm_ainvoke(
                [SystemMessage(content=retry_prompt), HumanMessage(content=user_msg)]
            )
            retry_content = retry_response.content
            if isinstance(retry_content, list):
                retry_content = str(retry_content)
            content_plan = self._parse_json_response(retry_content)
            content_plan["topic_revised"] = True

        # 使用 Ripple 预测传播效果 + PMF 验证（并行调用，带超时保护）
        ripple_timeout = Settings().ripple.workflow_timeout or _DEFAULT_RIPPLE_TIMEOUT

        # Build environment context from trend data to improve Ripple's
        # input_completeness and evidence_balance (P1 optimization).
        ripple_env: dict[str, Any] | None = None
        if trend_data or niche:
            ripple_env = {}
            if niche:
                ripple_env["niche"] = niche
            hot_topics = trend_data.get("hot_topics") or trend_data.get("trending_topics") or []
            if hot_topics:
                ripple_env["competing_topics"] = hot_topics[:5]
            if trend_data.get("market_saturation"):
                ripple_env["market_saturation"] = trend_data["market_saturation"]

        result: dict[str, Any] = {
            "content_plan": content_plan,
            "phase": WorkflowPhase.PLANNING,
        }

        if Settings().ripple.background and thread_id:
            # 后台模式：fire-and-forget Ripple，不阻塞主链
            await self._schedule_ripple_background(
                store, thread_id, content_plan, ripple_timeout, ripple_env
            )
            content_plan["ripple_pending"] = True
            result["ripple_pending"] = True
            result["ripple_reason"] = "pending"
            # ── Creative Memory: 沉淀策略 ──
            await self._deposit_creative_memory(cm, content_plan, niche)
            return result

        async def _predict() -> _RippleCall:
            call = await self._ripple_predict(
                content_plan,
                max_wait=ripple_timeout,
                thread_id=thread_id,
                environment=ripple_env,
            )
            if call.reason == "timeout":
                logger.warning(f"Ripple spread prediction timed out: job_id={call.job_id}")
                # 尝试取消任务（job_id 为空时 _ripple_cancel 直接返回）
                await self._ripple_cancel(call.job_id)
            return call

        async def _validate_pmf() -> _RippleCall:
            call = await self._ripple_validate_pmf(
                content_plan,
                max_wait=ripple_timeout,
                thread_id=thread_id,
            )
            if call.reason == "timeout":
                logger.warning(f"Ripple PMF validation timed out: job_id={call.job_id}")
                await self._ripple_cancel(call.job_id)
            return call

        ripple_prediction, ripple_pmf = await asyncio.gather(_predict(), _validate_pmf())

        # Set Ripple data (including fallback when unavailable)
        if ripple_prediction.ok:
            # 成功获取预测
            content_plan["ripple_prediction"] = ripple_prediction.data
            result["ripple_prediction"] = ripple_prediction.data
        else:
            # 超时或无数据
            fallback_pred: dict[str, Any] = {
                "estimated_reach": 0,
                "estimated_engagement": 0,
                "viral_probability": 0.0,
                "confidence": 0.0,
                "spread_path": [],
                "key_influencers": [],
            }
            # 保存超时时的 job_id 以便后续恢复
            if ripple_prediction.job_id:
                fallback_pred["ripple_job_id"] = ripple_prediction.job_id
                result["ripple_job_id"] = ripple_prediction.job_id
            content_plan["ripple_prediction"] = fallback_pred
            result["ripple_prediction"] = fallback_pred
            result["ripple_reason"] = (
                "timeout" if ripple_prediction.reason == "timeout" else "unreachable"
            )

        if ripple_pmf.ok:
            # 成功获取 PMF
            content_plan["ripple_pmf"] = ripple_pmf.data
            result["ripple_pmf"] = ripple_pmf.data
        else:
            # 超时或无数据
            is_pmf_timeout = ripple_pmf.reason == "timeout"
            fallback_pmf: dict[str, Any] = {
                "pmf_score": 0.0,
                "risk_factors": [
                    "Ripple 模拟超时，结果不可用" if is_pmf_timeout else "Ripple 服务不可用"
                ],
                "improvement_strategies": [],
                "confidence": 0.0,
            }
            # 保存超时时的 job_id 以便后续恢复
            if ripple_pmf.job_id:
                fallback_pmf["ripple_job_id"] = ripple_pmf.job_id
                if not result.get("ripple_job_id"):
                    result["ripple_job_id"] = ripple_pmf.job_id
            content_plan["ripple_pmf"] = fallback_pmf
            result["ripple_pmf"] = fallback_pmf
            if result.get("ripple_reason") is None:
                result["ripple_reason"] = "timeout" if is_pmf_timeout else "unreachable"

        # 如果传播预测偏低，注入 Ripple 数据重新生成策略
        if (
            ripple_prediction.ok
            and ripple_prediction.data.get("viral_probability", 1.0)
            < Settings().ripple.low_viral_threshold
        ):
            logger.info(
                f"Low viral probability "
                f"({ripple_prediction.data['viral_probability']:.2f}), "
                f"regenerating strategy with Ripple insights"
            )
            ripple_context = self._build_ripple_context(
                ripple_prediction.data, ripple_pmf.data or None
            )
            retry_prompt = self._compile_system_prompt(
                state,
                thread_id=str(thread_id or ""),
                account_id=account_id,
                niche=niche,
                l4_extra=memory_context,
            )
            # 将 ripple_context 直接拼入 system prompt
            retry_prompt = retry_prompt.replace("{ripple_context}", ripple_context)

            retry_response = await self._llm_ainvoke(
                [
                    SystemMessage(content=retry_prompt),
                    HumanMessage(content=user_msg),
                ]
            )
            retry_content = retry_response.content
            if isinstance(retry_content, list):
                retry_content = str(retry_content)
            revised_plan = self._parse_json_response(retry_content)
            # 保留 Ripple 数据
            revised_plan["ripple_prediction"] = ripple_prediction.data
            revised_plan["ripple_pmf"] = ripple_pmf.data
            revised_plan["ripple_revised"] = True
            content_plan = revised_plan

        result["content_plan"] = content_plan
        # Also set top-level Ripple fields for API exposure
        if ripple_prediction.ok and "ripple_prediction" not in result:
            result["ripple_prediction"] = ripple_prediction.data
        if ripple_pmf.ok and "ripple_pmf" not in result:
            result["ripple_pmf"] = ripple_pmf.data

        # ── Creative Memory: 沉淀策略 ──
        await self._deposit_creative_memory(cm, content_plan, niche)

        return result

    def _compile_system_prompt(
        self,
        state: XHSGrowthState,
        *,
        thread_id: str,
        account_id: str,
        niche: str,
        l4_extra: str,
    ) -> str:
        """Compile the system prompt via ContextCompiler (S4-3 迁移).

        L4 extra context（历史表现洞察 + creative_ctx + 创作者中心建议 +
        话题评分 + 用户主题前缀）作为单个 ContextItem 渲染到
        `<!-- ctx:l4_memory -->` 标记位。``{ripple_context}`` 占位符仍由
        调用方 post-render replace（consumer-map 口径，P1b 不动）。
        """
        run_context = RunContext(
            thread_id=thread_id, account_id=account_id, niche=niche, values=state
        )
        if l4_extra:
            memory = RetrievalResult(
                namespace="strategist_memory",
                layer=PromptLayer.L4_MEMORY,
                mode=RetrievalMode.HIT,
                items=(ContextItem(body=l4_extra, source="memory:content_strategist"),),
            )
        else:
            memory = RetrievalResult(
                namespace="strategist_memory",
                layer=PromptLayer.L4_MEMORY,
                mode=RetrievalMode.EMPTY,
            )
        return _compiler.compile_prompt(
            run_context, self.prompt_template["system"], retrievals=(memory,)
        ).render()

    async def _deposit_creative_memory(
        self, cm: Any, content_plan: dict[str, Any], niche: str
    ) -> None:
        """Deposit conversion play from content plan to creative memory."""
        angle = content_plan.get("content_angle", "")
        topic = content_plan.get("selected_topic", "")
        if not (angle or topic):
            return
        from backend.memory.types import ConversionPlay

        play = ConversionPlay(
            trigger_condition=topic,
            title_formula=content_plan.get("title_formula", ""),
            opening_hook=content_plan.get("opening_hook", ""),
            niche=niche,
            content_type=str(content_plan.get("content_type", "note")),
        )
        await cm.deposit_play(play)
        play_id = play.get("play_id", "")
        if play_id:
            content_plan["play_id"] = play_id

    async def _schedule_ripple_background(
        self,
        store: BaseStore,
        thread_id: str,
        content_plan: dict[str, Any],
        ripple_timeout: float,
        ripple_env: dict[str, Any] | None,
    ) -> None:
        """Fire-and-forget Ripple in background mode.

        Background task runs predict_spread + validate_pmf, writes results to
        store namespace ``ripple/{thread_id}`` key ``result``, and emits a
        WORKFLOW_DATA_UPDATED event. Exceptions are isolated — logged via done
        callback, never crash the main workflow chain.

        Clears any stale result from a prior run (e.g. a reangle cycle) before
        scheduling, so ``ripple_finalize`` / ``ripple_late_recheck`` never read
        the previous angle's prediction as if it were fresh.
        """

        await self._safe_store_delete(store, thread_id)

        async def _run() -> None:
            stored: dict[str, Any] = {"ripple_pending": False}
            try:
                prediction, pmf = await asyncio.gather(
                    self._ripple_predict(
                        content_plan,
                        max_wait=ripple_timeout,
                        thread_id=thread_id,
                        environment=ripple_env,
                    ),
                    self._ripple_validate_pmf(
                        content_plan,
                        max_wait=ripple_timeout,
                        thread_id=thread_id,
                    ),
                )
            except Exception as e:
                # Safety net only. The Gateway reports tool failures as
                # results, so anything arriving here is a defect in the
                # agent's own reading of them — and a background task must
                # never die silently.
                stored["ripple_reason"] = "unreachable"
                await self._safe_store_put(store, thread_id, stored)
                logger.warning(f"Ripple background failed: {e}", exc_info=True)
                return

            if prediction.reason == "timeout":
                # Surface the reason so finalize won't wait forever. Attempt
                # cancel (best-effort), persist, and stop here — the same
                # shape the pre-migration code had, since a timed-out run has
                # no predictions worth announcing.
                stored["ripple_reason"] = "timeout"
                if prediction.job_id:
                    stored["ripple_job_id"] = prediction.job_id
                await self._safe_store_put(store, thread_id, stored)
                logger.warning(
                    f"Ripple background timed out (job_id={prediction.job_id}), cancel attempted"
                )
                await self._ripple_cancel_safely(prediction.job_id)
                return

            if prediction.ok:
                stored["ripple_prediction"] = prediction.data
            else:
                stored["ripple_reason"] = "unreachable"
            if pmf.ok:
                stored["ripple_pmf"] = pmf.data
            await self._safe_store_put(store, thread_id, stored)

            # 发事件通知 Ripple 结果就绪
            from backend.realtime import EventBusService, EventType

            EventBusService.get_instance().emit(
                EventType.WORKFLOW_DATA_UPDATED,
                thread_id=thread_id,
                payload={"data_type": "ripple_ready", "data": stored},
            )

        def _on_done(task: asyncio.Task[None]) -> None:
            if task.cancelled():
                return
            exc = task.exception()
            if exc:
                logger.error(f"Ripple background task failed: {exc}", exc_info=True)

        task = asyncio.create_task(_run())
        task.add_done_callback(_on_done)

    @staticmethod
    async def _safe_store_put(store: BaseStore, thread_id: str, value: dict[str, Any]) -> None:
        """Persist Ripple background result; swallow store errors (best-effort)."""
        try:
            await store.aput(("ripple", thread_id), "result", value=value)
        except Exception as e:
            logger.error(f"Failed to persist Ripple background result: {e}", exc_info=True)

    @staticmethod
    async def _safe_store_delete(store: BaseStore, thread_id: str) -> None:
        """Clear a stale Ripple result before re-scheduling (reangle/retopic).

        Best-effort: a missing key or store error must not block the new run.
        """
        try:
            await store.adelete(("ripple", thread_id), "result")
        except Exception as e:
            logger.warning(f"Failed to clear stale Ripple result for {thread_id}: {e}")

    async def _ripple_cancel_safely(self, job_id: str) -> None:
        """Best-effort cancel — never raises into the background task."""
        try:
            await self._ripple_cancel(job_id)
        except Exception as e:
            logger.warning(f"Ripple background cancel failed for {job_id}: {e}")

    @staticmethod
    def _extract_candidate_topics(trend_data: dict[str, Any], limit: int = 10) -> list[str]:
        """从 trend_data 提取候选话题标题列表（兼容 dict/str 元素）。"""
        raw = (
            trend_data.get("hot_topics")
            or trend_data.get("trending_topics")
            or trend_data.get("topics")
            or []
        )
        topics: list[str] = []
        for t in raw[:limit]:
            topic = t.get("topic") if isinstance(t, dict) else t
            if topic and topic not in topics:
                topics.append(str(topic))
        return topics

    async def _score_trend_topics(
        self, trend_data: dict[str, Any], niche: str, limit: int = 5
    ) -> str:
        """对候选话题调用 topic_scorer 打分，返回可注入 prompt 的上下文字符串。

        hot_topics 元素可能是 dict（含 topic 字段）或纯字符串，统一兼容。
        任一话题评分失败则跳过，不阻断主流程。

        P1c-S3: goes through the Tool Gateway, so the call carries a timeout
        (LatencyClass.SLOW → 120s), the declared retry policy and a trace
        event. A tool failure arrives as ``ok=False`` instead of an
        exception — the failure mode is the runtime's to define now.
        """
        topics = self._extract_candidate_topics(trend_data, limit=limit)
        if not topics:
            return ""

        lines: list[str] = []
        for topic in topics:
            try:
                scored = await self.tools.invoke(
                    "analysis.topic_scorer", {"topic": topic, "niche": niche}
                )
                if not scored.ok:
                    logger.warning(f"topic_scorer 失败 ({topic}): {scored.error}")
                    continue
                result = scored.value
                if not isinstance(result, dict):
                    continue
                lines.append(
                    f"- {topic}: 热度 {result.get('heat_score', 'N/A')}，"
                    f"趋势 {result.get('growth_trend', 'N/A')}，"
                    f"竞争 {result.get('competition_level', 'N/A')}，"
                    f"推荐 {result.get('recommendation', 'N/A')}"
                )
            except Exception as e:
                logger.warning(f"topic_scorer 失败 ({topic}): {e}")

        if not lines:
            return ""
        return "## 话题热度评分（topic_scorer）\n" + "\n".join(lines)

    async def _ripple_predict(
        self,
        content_plan: dict[str, Any],
        max_wait: float = _DEFAULT_RIPPLE_TIMEOUT,
        thread_id: str | None = None,
        environment: dict[str, Any] | None = None,
    ) -> _RippleCall:
        """调用 Ripple 预测内容传播效果（经 Tool Gateway）

        Args:
            max_wait: 最大等待时间（秒），传给 RippleService.submit_and_wait。
                Gateway 自身的超时是它的上一级兜底，见 catalog 的
                ``_RIPPLE_SAFETY_NET_S`` —— 那不是这个调用等待多久的地方。
            environment: 环境上下文（竞争格局、季节性、平台趋势）

        Returns:
            读数；没有可测话题时 ``reason="skipped"``
        """
        topic = content_plan.get("selected_topic", "")
        if not topic:
            return _RippleCall(reason="skipped")

        ripple_cfg = Settings().ripple
        result = await self.tools.invoke(
            "ripple.predict_spread",
            {
                "topic": topic,
                "content_type": content_plan.get("content_type", "note"),
                "tags": content_plan.get("hashtags", []),
                "tone": content_plan.get("content_angle", ""),
                "description": content_plan.get("content_angle", ""),
                "max_waves": ripple_cfg.default_max_waves,
                "simulation_horizon": ripple_cfg.default_simulation_horizon,
                "max_wait": max_wait,
                "thread_id": thread_id,
                "environment": environment,
            },
            thread_id=thread_id or "",
        )

        call = _RippleCall.read(result, body_key="ripple_prediction")
        if not call.ok:
            logger.warning(f"Ripple prediction unavailable for '{topic}': {result.error}")
            return call

        logger.info(f"Ripple prediction for '{topic}': {call.data}")
        # 下游恢复（ripple_finalize / ripple_late_recheck）从预测体内部读
        # job_id —— 迁移前就是那个形状 —— 所以它跟着数据走，而不是并排存放。
        return replace(call, data={"ripple_job_id": call.job_id, **call.data})

    async def _ripple_validate_pmf(
        self,
        content_plan: dict[str, Any],
        max_wait: float = _DEFAULT_RIPPLE_TIMEOUT,
        thread_id: str | None = None,
    ) -> _RippleCall:
        """调用 Ripple 验证产品市场契合度（经 Tool Gateway）

        Args:
            max_wait: 最大等待时间（秒），传给 RippleService.submit_and_wait

        Returns:
            读数；没有可测话题时 ``reason="skipped"``
        """
        topic = content_plan.get("selected_topic", "")
        if not topic:
            return _RippleCall(reason="skipped")

        ripple_cfg = Settings().ripple
        result = await self.tools.invoke(
            "ripple.validate_pmf",
            {
                "product_name": topic,
                "category": content_plan.get("content_type", "note"),
                "description": content_plan.get("content_angle", ""),
                "differentiators": content_plan.get("key_points", []),
                "max_waves": ripple_cfg.default_max_waves,
                "simulation_horizon": ripple_cfg.default_simulation_horizon,
                "ensemble_runs": ripple_cfg.default_ensemble_runs,
                "max_wait": max_wait,
                "thread_id": thread_id,
            },
            thread_id=thread_id or "",
        )

        call = _RippleCall.read(result, body_key="ripple_pmf")
        if not call.ok:
            logger.warning(f"Ripple PMF unavailable for '{topic}': {result.error}")
            return call

        logger.info(f"Ripple PMF for '{topic}': {call.data}")
        return call

    async def _ripple_cancel(self, job_id: str) -> dict[str, Any] | None:
        """尝试取消 Ripple 模拟任务

        Args:
            job_id: 模拟任务 ID

        Returns:
            取消结果 dict，或 None（如果调用失败）
        """
        if not job_id:
            return None

        try:
            from backend.services.ripple_service import RippleService

            service = RippleService.get_instance()
            result = await service.cancel_simulation(job_id)
            logger.info(f"Ripple cancel result for {job_id}: {result}")
            return result

        except Exception as e:
            logger.warning(f"Ripple cancel failed for {job_id}: {e}")
            return None

    @staticmethod
    def _build_ripple_context(prediction: dict[str, Any], pmf: dict[str, Any] | None) -> str:
        """构建 Ripple 数据的 prompt 上下文"""
        lines = ["\nRipple 传播预测数据："]
        lines.append(f"- 预计触达: {prediction.get('estimated_reach', 'N/A')}")
        lines.append(f"- 预计互动: {prediction.get('estimated_engagement', 'N/A')}")
        lines.append(f"- 爆发概率: {prediction.get('viral_probability', 'N/A')}")
        lines.append(f"- 置信度: {prediction.get('confidence', 'N/A')}")

        if pmf:
            lines.append("\nPMF 验证结果：")
            lines.append(f"- PMF 评分: {pmf.get('pmf_score', 'N/A')}")
            if pmf.get("risk_factors"):
                lines.append(f"- 风险因素: {', '.join(pmf['risk_factors'])}")
            if pmf.get("improvement_strategies"):
                lines.append(f"- 改进建议: {', '.join(pmf['improvement_strategies'])}")

        return "\n".join(lines)
