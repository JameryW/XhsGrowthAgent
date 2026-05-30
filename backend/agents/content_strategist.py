"""Content Strategist agent — selects topics and plans content, with Ripple spread prediction."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.schema import WorkflowPhase, XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.content_strategist")


class ContentStrategistAgent(BaseAgent):
    task_type = TaskType.STRATEGY
    agent_name = "content_strategist"
    prompt_file = "content_strategist.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")

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

        # 使用 Ripple 预测传播效果 + PMF 验证
        ripple_prediction = await self._ripple_predict(content_plan)
        ripple_pmf = await self._ripple_validate_pmf(content_plan)

        if ripple_prediction:
            content_plan["ripple_prediction"] = ripple_prediction
        if ripple_pmf:
            content_plan["ripple_pmf"] = ripple_pmf

        # 如果传播预测偏低，注入 Ripple 数据重新生成策略
        if ripple_prediction and ripple_prediction.get("viral_probability", 1.0) < 0.3:
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

        return {
            "content_plan": content_plan,
            "phase": WorkflowPhase.PLANNING,
        }

    async def _ripple_predict(self, content_plan: dict) -> dict | None:
        """调用 Ripple 预测内容传播效果"""
        try:
            from backend.tools.ripple.integration import parse_spread_prediction, predict_spread

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
            )

            parsed = parse_spread_prediction(result)
            if parsed.get("ripple_prediction"):
                logger.info(f"Ripple prediction for '{topic}': {parsed['ripple_prediction']}")
                return parsed["ripple_prediction"]

        except Exception as e:
            logger.warning(f"Ripple prediction skipped: {e}")

        return None

    async def _ripple_validate_pmf(self, content_plan: dict) -> dict | None:
        """调用 Ripple 验证产品市场契合度"""
        try:
            from backend.tools.ripple.integration import parse_pmf_result, validate_pmf

            topic = content_plan.get("selected_topic", "")
            if not topic:
                return None

            result = await validate_pmf(
                product_name=topic,
                category=content_plan.get("content_type", "note"),
                description=content_plan.get("content_angle", ""),
                differentiators=content_plan.get("key_points", []),
            )

            parsed = parse_pmf_result(result)
            if parsed.get("ripple_pmf"):
                logger.info(f"Ripple PMF for '{topic}': {parsed['ripple_pmf']}")
                return parsed["ripple_pmf"]

        except Exception as e:
            logger.warning(f"Ripple PMF validation skipped: {e}")

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
