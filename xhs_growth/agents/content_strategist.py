"""Content Strategist agent — selects topics and plans content, with Ripple spread prediction."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase

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

        system_prompt = self._build_system_prompt(state, extra_context=memory_context)

        trend_data = state.get("trend_data", {})
        user_msg = f"""趋势数据：{trend_data}
账号定位：{account_id}
历史表现洞察：{memory_context}"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        content_plan = self._parse_json_response(response.content)

        # 使用 Ripple 预测内容传播效果（可选增强）
        ripple_prediction = await self._ripple_predict(content_plan)
        if ripple_prediction:
            content_plan["ripple_prediction"] = ripple_prediction

        return {
            "content_plan": content_plan,
            "phase": WorkflowPhase.PLANNING,
        }

    async def _ripple_predict(self, content_plan: dict) -> dict | None:
        """调用 Ripple 预测内容传播效果"""
        try:
            from xhs_growth.tools.ripple.integration import predict_spread, parse_spread_prediction

            topic = content_plan.get("selected_topic", "")
            if not topic:
                return None

            result = await predict_spread(
                topic=topic,
                content_type=content_plan.get("content_type", "note"),
                tags=content_plan.get("hashtags", []),
                tone=content_plan.get("content_angle", ""),
                description=content_plan.get("content_angle", ""),
                max_waves=6,  # 策略阶段用较少 wave 快速评估
                simulation_horizon="48h",
            )

            parsed = parse_spread_prediction(result)
            if parsed.get("ripple_prediction"):
                logger.info(f"Ripple prediction for '{topic}': {parsed['ripple_prediction']}")
                return parsed["ripple_prediction"]

        except Exception as e:
            logger.warning(f"Ripple prediction skipped: {e}")

        return None