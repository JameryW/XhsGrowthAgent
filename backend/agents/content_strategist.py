"""Content Strategist agent — selects topics and plans content, with Ripple spread prediction."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.config.settings import Settings
from backend.services.ripple_service import RippleTimeoutError
from backend.state.schema import WorkflowPhase, XHSGrowthState

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

        # 召回历史表现洞察
        insights = await self._recall_memory(
            store, account_id, query="content strategy", namespace="performance_insights", limit=5
        )
        memory_context = ""
        if insights:
            memory_context = "\n历史表现洞察：\n"
            for i in insights:
                memory_context += f"- {i.get('insight', '')}\n"

        # 先用基础 prompt 生成初版策略（暂无 Ripple 数据）
        system_prompt = self._build_system_prompt(state, extra_context=memory_context)
        system_prompt = system_prompt.replace("{ripple_context}", "")

        niche = state.get("niche", "母婴")
        trend_data = state.get("trend_data", {})
        user_msg = f"""趋势数据：{trend_data}
账号定位：{account_id}
垂类赛道：{niche}
历史表现洞察：{memory_context}"""

        response = await self.model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        content_plan = self._parse_json_response(response.content)

        # 使用 Ripple 预测传播效果 + PMF 验证（并行调用，带超时保护）
        ripple_timeout = Settings().ripple.workflow_timeout or _DEFAULT_RIPPLE_TIMEOUT

        result = {
            "content_plan": content_plan,
            "phase": WorkflowPhase.PLANNING,
        }

        async def _predict():
            try:
                return await self._ripple_predict(
                    content_plan, max_wait=ripple_timeout, thread_id=thread_id,
                )
            except RippleTimeoutError as e:
                logger.warning(f"Ripple spread prediction timed out: job_id={e.job_id}")
                # 尝试取消任务
                await self._ripple_cancel(e.job_id)
                return {"ripple_job_id": e.job_id, "ripple_reason": "timeout"}
            except TimeoutError:
                logger.warning(f"Ripple spread prediction timed out after {ripple_timeout}s")
                return {"ripple_job_id": "", "ripple_reason": "timeout"}

        async def _validate_pmf():
            try:
                return await self._ripple_validate_pmf(
                    content_plan, max_wait=ripple_timeout, thread_id=thread_id,
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
            is_timeout = (
                isinstance(ripple_prediction, dict)
                and ripple_prediction.get("ripple_reason") == "timeout"
            )
            if is_timeout and ripple_prediction.get("ripple_job_id"):
                fallback_pred["ripple_job_id"] = ripple_prediction["ripple_job_id"]
                result["ripple_job_id"] = ripple_prediction["ripple_job_id"]
            content_plan["ripple_prediction"] = fallback_pred
            result["ripple_prediction"] = fallback_pred
            if is_timeout:
                result["ripple_reason"] = "timeout"

        if ripple_pmf and not isinstance(ripple_pmf, dict):
            ripple_pmf = None

        if ripple_pmf and "ripple_reason" not in ripple_pmf:
            # 成功获取 PMF
            content_plan["ripple_pmf"] = ripple_pmf
            result["ripple_pmf"] = ripple_pmf
        else:
            # 超时或无数据
            is_pmf_timeout = (
                isinstance(ripple_pmf, dict)
                and ripple_pmf.get("ripple_reason") == "timeout"
            )
            fallback_pmf = {
                "pmf_score": 0.0,
                "risk_factors": [
                    "Ripple 模拟超时，结果不可用" if is_pmf_timeout else "Ripple 服务不可用"
                ],
                "improvement_strategies": [],
                "confidence": 0.0,
            }
            # 保存超时时的 job_id 以便后续恢复
            if is_pmf_timeout and ripple_pmf.get("ripple_job_id"):
                fallback_pmf["ripple_job_id"] = ripple_pmf["ripple_job_id"]
                if not result.get("ripple_job_id"):
                    result["ripple_job_id"] = ripple_pmf["ripple_job_id"]
            content_plan["ripple_pmf"] = fallback_pmf
            result["ripple_pmf"] = fallback_pmf
            if is_pmf_timeout and result.get("ripple_reason") is None:
                result["ripple_reason"] = "timeout"

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
            revised_plan = self._parse_json_response(retry_response.content)
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
        return result

    async def _ripple_predict(
        self, content_plan: dict, max_wait: float = _DEFAULT_RIPPLE_TIMEOUT,
        thread_id: str | None = None,
    ) -> dict | None:
        """调用 Ripple 预测内容传播效果

        Args:
            max_wait: 最大等待时间（秒），传递给 RippleService

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
                max_waves=6,
                simulation_horizon="48h",
                max_wait=max_wait,
                thread_id=thread_id,
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
        self, content_plan: dict, max_wait: float = _DEFAULT_RIPPLE_TIMEOUT,
        thread_id: str | None = None,
    ) -> dict | None:
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
                max_wait=max_wait,
                thread_id=thread_id,
            )

            if result.get("ripple_pmf"):
                logger.info(f"Ripple PMF for '{topic}': {result['ripple_pmf']}")
                return result["ripple_pmf"]

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
    def _build_ripple_context(prediction: dict, pmf: dict | None) -> str:
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
