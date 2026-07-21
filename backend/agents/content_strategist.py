"""Content Strategist agent — selects topics and plans content, with Ripple spread prediction."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.config.settings import Settings
from backend.services.ripple_service import RippleTimeoutError
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.content_strategist")

# Ripple workflow wait timeout (seconds). Real jobs commonly exceed 900s.
_DEFAULT_RIPPLE_TIMEOUT = 1800


class ContentStrategistAgent(BaseAgent):
    task_type = TaskType.STRATEGY
    agent_name = "content_strategist"
    prompt_file = "content_strategist.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")
        thread_id = state.get("session_id")

        # ── Creative Memory: 读取 ──
        from backend.memory.creative import CreativeMemory

        cm = CreativeMemory(account_id, store=store)
        niche = state.get("niche", "母婴")
        styles = await cm.recall_style(query=f"content strategy {niche}")
        plays = await cm.recall_plays(condition="content strategy", niche=niche)
        benchmark = await cm.recall_benchmark(niche)

        # 保留原有的 _recall_memory 召回
        insights = await self._recall_memory(
            store, account_id, query="content strategy", namespace="performance_insights", limit=5
        )
        memory_context = ""
        if insights:
            memory_context = "\n历史表现洞察：\n"
            for i in insights:
                memory_context += f"- {i.get('insight', '')}\n"

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

        # 先用基础 prompt 生成初版策略（暂无 Ripple 数据）
        system_prompt = self._build_system_prompt(state, extra_context=memory_context)
        system_prompt = system_prompt.replace("{ripple_context}", "")

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
        system_prompt = self._build_system_prompt(state, extra_context=memory_context)
        system_prompt = system_prompt.replace("{ripple_context}", "")

        user_msg = f"""趋势数据：{trend_data}
账号定位：{account_id}
垂类赛道：{niche}
用户指定主题：{user_topic or "（未指定，从趋势候选中选取）"}
历史表现洞察：{memory_context}"""

        response = await self.model.ainvoke(
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
            retry_prompt = self._build_system_prompt(
                state,
                extra_context=memory_context
                + f"\n【纠偏】上一次输出的 selected_topic='{chosen}' 不在候选话题内。"
                f"候选话题为：{candidates}。必须从中选取一个，不得自创或改写措辞。",
            )
            retry_prompt = retry_prompt.replace("{ripple_context}", "")
            retry_response = await self.model.ainvoke(
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
            self._schedule_ripple_background(
                store, thread_id, content_plan, ripple_timeout, ripple_env
            )
            content_plan["ripple_pending"] = True
            result["ripple_pending"] = True
            result["ripple_reason"] = "pending"
            # ── Creative Memory: 沉淀策略 ──
            await self._deposit_creative_memory(cm, content_plan, niche)
            return result

        async def _predict() -> dict[str, Any] | None:
            try:
                return await self._ripple_predict(
                    content_plan,
                    max_wait=ripple_timeout,
                    thread_id=thread_id,
                    environment=ripple_env,
                )
            except RippleTimeoutError as e:
                logger.warning(f"Ripple spread prediction timed out: job_id={e.job_id}")
                # 尝试取消任务
                await self._ripple_cancel(e.job_id)
                return {"ripple_job_id": e.job_id, "ripple_reason": "timeout"}
            except TimeoutError:
                logger.warning(f"Ripple spread prediction timed out after {ripple_timeout}s")
                return {"ripple_job_id": "", "ripple_reason": "timeout"}

        async def _validate_pmf() -> dict[str, Any] | None:
            try:
                return await self._ripple_validate_pmf(
                    content_plan,
                    max_wait=ripple_timeout,
                    thread_id=thread_id,
                )
            except RippleTimeoutError as e:
                logger.warning(f"Ripple PMF validation timed out: job_id={e.job_id}")
                # 尝试取消任务
                await self._ripple_cancel(e.job_id)
                return {"ripple_job_id": e.job_id, "ripple_reason": "timeout"}
            except TimeoutError:
                logger.warning(f"Ripple PMF validation timed out after {ripple_timeout}s")
                return {"ripple_job_id": "", "ripple_reason": "timeout"}

        ripple_prediction, ripple_pmf = await asyncio.gather(_predict(), _validate_pmf())

        # Set Ripple data (including fallback when unavailable)
        if ripple_prediction and not isinstance(ripple_prediction, dict):
            # Should not happen, but guard against unexpected types
            ripple_prediction = None

        if ripple_prediction and "ripple_reason" not in ripple_prediction:
            # 成功获取预测
            content_plan["ripple_prediction"] = ripple_prediction
            result["ripple_prediction"] = ripple_prediction
        else:
            # 超时或无数据
            fallback_pred = {
                "estimated_reach": 0,
                "estimated_engagement": 0,
                "viral_probability": 0.0,
                "confidence": 0.0,
                "spread_path": [],
                "key_influencers": [],
            }
            # 保存超时时的 job_id 以便后续恢复
            timeout_pred: dict[str, Any] | None = (
                ripple_prediction if isinstance(ripple_prediction, dict) else None
            )
            is_timeout = bool(timeout_pred and timeout_pred.get("ripple_reason") == "timeout")
            if is_timeout and timeout_pred and timeout_pred.get("ripple_job_id"):
                job_id = timeout_pred["ripple_job_id"]
                fallback_pred["ripple_job_id"] = job_id
                result["ripple_job_id"] = job_id
            content_plan["ripple_prediction"] = fallback_pred
            result["ripple_prediction"] = fallback_pred
            if is_timeout:
                result["ripple_reason"] = "timeout"
            else:
                result["ripple_reason"] = "unreachable"

        if ripple_pmf and not isinstance(ripple_pmf, dict):
            ripple_pmf = None

        if ripple_pmf and "ripple_reason" not in ripple_pmf:
            # 成功获取 PMF
            content_plan["ripple_pmf"] = ripple_pmf
            result["ripple_pmf"] = ripple_pmf
        else:
            # 超时或无数据
            timeout_pmf: dict[str, Any] | None = (
                ripple_pmf if isinstance(ripple_pmf, dict) else None
            )
            is_pmf_timeout = bool(timeout_pmf and timeout_pmf.get("ripple_reason") == "timeout")
            fallback_pmf = {
                "pmf_score": 0.0,
                "risk_factors": [
                    "Ripple 模拟超时，结果不可用" if is_pmf_timeout else "Ripple 服务不可用"
                ],
                "improvement_strategies": [],
                "confidence": 0.0,
            }
            # 保存超时时的 job_id 以便后续恢复
            if is_pmf_timeout and timeout_pmf and timeout_pmf.get("ripple_job_id"):
                pmf_job_id = timeout_pmf["ripple_job_id"]
                fallback_pmf["ripple_job_id"] = pmf_job_id
                if not result.get("ripple_job_id"):
                    result["ripple_job_id"] = pmf_job_id
            content_plan["ripple_pmf"] = fallback_pmf
            result["ripple_pmf"] = fallback_pmf
            if result.get("ripple_reason") is None:
                result["ripple_reason"] = "timeout" if is_pmf_timeout else "unreachable"

        # 如果传播预测偏低，注入 Ripple 数据重新生成策略
        if (
            ripple_prediction
            and "ripple_reason" not in ripple_prediction
            and ripple_prediction.get("viral_probability", 1.0) < 0.3
        ):
            logger.info(
                f"Low viral probability ({ripple_prediction['viral_probability']:.2f}), "
                f"regenerating strategy with Ripple insights"
            )
            ripple_context = self._build_ripple_context(ripple_prediction, ripple_pmf)
            retry_prompt = self._build_system_prompt(state, extra_context=memory_context)
            # 将 ripple_context 直接拼入 system prompt
            retry_prompt = retry_prompt.replace("{ripple_context}", ripple_context)

            retry_response = await self.model.ainvoke(
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
            revised_plan["ripple_prediction"] = ripple_prediction
            revised_plan["ripple_pmf"] = ripple_pmf
            revised_plan["ripple_revised"] = True
            content_plan = revised_plan

        result["content_plan"] = content_plan
        # Also set top-level Ripple fields for API exposure
        if (
            ripple_prediction
            and "ripple_reason" not in ripple_prediction
            and "ripple_prediction" not in result
        ):
            result["ripple_prediction"] = ripple_prediction
        if ripple_pmf and "ripple_reason" not in ripple_pmf and "ripple_pmf" not in result:
            result["ripple_pmf"] = ripple_pmf

        # ── Creative Memory: 沉淀策略 ──
        await self._deposit_creative_memory(cm, content_plan, niche)

        return result

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

    def _schedule_ripple_background(
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
        """

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
            except RippleTimeoutError as e:
                # Background Ripple timed out — surface reason so finalize won't
                # wait forever. Attempt cancel (best-effort), then persist.
                stored["ripple_reason"] = "timeout"
                if e.job_id:
                    stored["ripple_job_id"] = e.job_id
                await self._safe_store_put(store, thread_id, stored)
                logger.warning(f"Ripple background timed out (job_id={e.job_id}), cancel attempted")
                await self._ripple_cancel_safely(e.job_id)
                return
            except Exception as e:
                stored["ripple_reason"] = "unreachable"
                await self._safe_store_put(store, thread_id, stored)
                logger.warning(f"Ripple background failed: {e}")
                return

            if prediction and isinstance(prediction, dict) and "ripple_reason" not in prediction:
                stored["ripple_prediction"] = prediction
            elif isinstance(prediction, dict) and prediction.get("ripple_reason") == "timeout":
                stored["ripple_reason"] = "timeout"
                if job_id := prediction.get("ripple_job_id"):
                    stored["ripple_job_id"] = job_id
            else:
                stored["ripple_reason"] = "unreachable"
            if pmf and isinstance(pmf, dict) and "ripple_reason" not in pmf:
                stored["ripple_pmf"] = pmf
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

        try:
            task = asyncio.create_task(_run())
            task.add_done_callback(_on_done)
        except RuntimeError:
            # No running event loop — degrade to blocking would defeat the
            # purpose; just log and continue without ripple.
            logger.warning("No event loop for background Ripple, skipping")

    @staticmethod
    async def _safe_store_put(store: BaseStore, thread_id: str, value: dict[str, Any]) -> None:
        """Persist Ripple background result; swallow store errors (best-effort)."""
        try:
            await store.aput(("ripple", thread_id), "result", value=value)
        except Exception as e:
            logger.error(f"Failed to persist Ripple background result: {e}", exc_info=True)

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
        """
        from backend.tools.analysis.topic_scorer import topic_scorer

        topics = self._extract_candidate_topics(trend_data, limit=limit)
        if not topics:
            return ""

        lines: list[str] = []
        for topic in topics:
            try:
                result = await topic_scorer.ainvoke({"topic": topic, "niche": niche})
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
    ) -> dict[str, Any] | None:
        """调用 Ripple 预测内容传播效果

        Args:
            max_wait: 最大等待时间（秒），传递给 RippleService
            environment: 环境上下文（竞争格局、季节性、平台趋势）

        Returns:
            包含 ripple_job_id 和预测数据的 dict，或 None
        """
        try:
            from backend.tools.ripple.integration import predict_spread

            topic = content_plan.get("selected_topic", "")
            if not topic:
                return None

            result = await predict_spread(
                topic=topic,
                content_type=content_plan.get("content_type", "note"),
                tags=content_plan.get("hashtags", []),
                tone=content_plan.get("content_angle", ""),
                description=content_plan.get("content_angle", ""),
                max_waves=3,
                simulation_horizon="12h",
                max_wait=max_wait,
                thread_id=thread_id,
                environment=environment,
            )

            if result.get("ripple_prediction"):
                logger.info(f"Ripple prediction for '{topic}': {result['ripple_prediction']}")
                # 返回包含 job_id 和预测数据的完整结果
                return {
                    "ripple_job_id": result.get("ripple_job_id", ""),
                    **result["ripple_prediction"],
                }

            if result.get("error"):
                logger.warning(f"Ripple prediction error for '{topic}': {result['error']}")

        except RippleTimeoutError:
            # 让 RippleTimeoutError 传播到调用方，以便保存 job_id 并尝试取消
            raise
        except Exception as e:
            logger.warning(f"Ripple prediction skipped: {e}")

        return None

    async def _ripple_validate_pmf(
        self,
        content_plan: dict[str, Any],
        max_wait: float = _DEFAULT_RIPPLE_TIMEOUT,
        thread_id: str | None = None,
    ) -> dict[str, Any] | None:
        """调用 Ripple 验证产品市场契合度

        Args:
            max_wait: 最大等待时间（秒），传递给 RippleService
        """
        try:
            from backend.tools.ripple.integration import validate_pmf

            topic = content_plan.get("selected_topic", "")
            if not topic:
                return None

            result = await validate_pmf(
                product_name=topic,
                category=content_plan.get("content_type", "note"),
                description=content_plan.get("content_angle", ""),
                differentiators=content_plan.get("key_points", []),
                max_waves=3,
                simulation_horizon="12h",
                ensemble_runs=1,
                max_wait=max_wait,
                thread_id=thread_id,
            )

            if result.get("ripple_pmf"):
                logger.info(f"Ripple PMF for '{topic}': {result['ripple_pmf']}")
                return cast(dict[str, Any], result["ripple_pmf"])

            if result.get("error"):
                logger.warning(f"Ripple PMF error for '{topic}': {result['error']}")

        except RippleTimeoutError:
            # 让 RippleTimeoutError 传播到调用方，以便保存 job_id 并尝试取消
            raise
        except Exception as e:
            logger.warning(f"Ripple PMF validation skipped: {e}")

        return None

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
