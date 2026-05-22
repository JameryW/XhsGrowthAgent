"""Analyst agent — reads engagement data, generates insights, with Ripple report integration."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase

logger = logging.getLogger("xhs_growth.agents.analyst")


class AnalystAgent(BaseAgent):
    task_type = TaskType.ANALYSIS
    agent_name = "analyst"
    prompt_file = "analyst.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")
        publish_result = state.get("publish_result", {})

        # 召回历史数据
        history = await self._recall_memory(
            store, account_id, query="content performance", namespace="content_history", limit=10
        )

        # 尝试获取 Ripple 预测报告（如果之前有模拟）
        ripple_report = await self._ripple_report(state)

        system_prompt = self._build_system_prompt(state)

        ripple_context = ""
        if ripple_report:
            ripple_context = f"\nRipple 传播预测报告：\n{ripple_report}\n"

        user_msg = f"""帖子数据：{publish_result}
历史数据：{history}
账号定位：{account_id}{ripple_context}"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        analytics = self._parse_json_response(response.content)

        # 将 Ripple 预测与实际数据对比
        if ripple_report:
            analytics["ripple_comparison"] = self._compare_prediction_vs_actual(
                state.get("content_plan", {}).get("ripple_prediction"),
                publish_result,
            )

        # 将洞察存入长期记忆
        from xhs_growth.memory.store import MemoryManager

        mm = MemoryManager(account_id)
        for insight in analytics.get("insights", []):
            await mm.store_insight(store, insight, {"source": "analyst", "post_id": publish_result.get("post_id", "")})

        for rec in analytics.get("recommendations", []):
            await mm.store_strategy_note(store, rec, {"source": "analyst"})

        return {
            "analytics": analytics,
            "phase": WorkflowPhase.ANALYZING,
        }

    async def _ripple_report(self, state: XHSGrowthState) -> str | None:
        """尝试获取 Ripple 模拟报告"""
        ripple_prediction = state.get("content_plan", {}).get("ripple_prediction", {})
        job_id = ripple_prediction.get("ripple_job_id") if isinstance(ripple_prediction, dict) else None

        if not job_id:
            return None

        try:
            from xhs_growth.tools.ripple.integration import get_report

            report = await get_report(job_id)
            if "error" not in report:
                # 提取报告文本
                rounds = report.get("rounds", [])
                texts = []
                for r in rounds:
                    texts.append(r.get("content", r.get("text", str(r))))
                return "\n".join(texts)
        except Exception as e:
            logger.warning(f"Ripple report retrieval skipped: {e}")

        return None

    def _compare_prediction_vs_actual(
        self, prediction: dict | None, actual: dict
    ) -> dict[str, Any]:
        """对比 Ripple 预测与实际表现"""
        if not prediction:
            return {}

        return {
            "predicted_reach": prediction.get("estimated_reach", 0),
            "predicted_viral_prob": prediction.get("viral_probability", 0),
            "actual_engagement_rate": actual.get("engagement_rate", 0),
            "prediction_accuracy": "待评估",  # 需要更多数据点才能计算
        }