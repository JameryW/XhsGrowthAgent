"""Copywriter agent — generates titles, body text, hashtags."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.schema import WorkflowPhase, XHSGrowthState


class CopywriterAgent(BaseAgent):
    task_type = TaskType.WRITING
    agent_name = "copywriter"
    prompt_file = "copywriter.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")
        plan = state.get("content_plan", {})

        # ── Creative Memory: 读取 ──
        from backend.memory.creative import CreativeMemory

        cm = CreativeMemory(account_id, store=store)
        styles = await cm.recall_style(query=plan.get("selected_topic", ""))
        materials = await cm.recall_materials(category="文案片段", tags=["高转化", "爆款标题"])

        # 保留原有的 _recall_memory 召回
        past_content = await self._recall_memory(
            store,
            account_id,
            query=plan.get("selected_topic", ""),
            namespace="content_history",
            limit=3,
        )
        audience_prefs = await self._recall_memory(
            store,
            account_id,
            query=f"audience preference for {plan.get('content_type', 'note')}",
            namespace="audience_preferences",
            limit=3,
        )

        # 构建完整 memory context
        memory_context = ""
        if past_content:
            memory_context += "\n历史爆款参考：\n"
            for pc in past_content:
                title = pc.get("title", "")
                rate = pc.get("engagement_rate", "N/A")
                memory_context += f"- {title} (互动率: {rate})\n"
        if audience_prefs:
            memory_context += "\n受众偏好：\n"
            for ap in audience_prefs:
                memory_context += f"- {ap.get('preference', '')}\n"

        # 拼接 creative memory 上下文
        creative_ctx = cm.build_creative_context(styles, [], materials)
        if creative_ctx:
            memory_context += f"\n{creative_ctx}"

        system_prompt = self._build_system_prompt(state, extra_context=memory_context)

        # 构建 Ripple 传播预测上下文
        ripple_context = self._build_ripple_context(plan)
        system_prompt = system_prompt.replace("{ripple_context}", ripple_context)

        niche = state.get("niche", "母婴")
        user_msg = f"""选题：{plan.get("selected_topic", "")}
角度：{plan.get("content_angle", "")}
目标受众：{plan.get("target_audience", "")}
内容类型：{plan.get("content_type", "note")}
垂类赛道：{niche}"""

        response = await self.model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        copy_content = self._parse_json_response(response.content)

        # ── Creative Memory: 沉淀 ──
        from backend.memory.types import MaterialEntry

        deposited_material_ids: list[str] = []

        selected_title = copy_content.get("selected_title", "")
        if selected_title:
            title_entry = MaterialEntry(
                category="标题模板",
                content=selected_title,
                source_post_id="",
                tags=["auto_deposit", "标题"],
            )
            await cm.deposit_material(title_entry)
            mid = title_entry.get("material_id", "")
            if mid:
                deposited_material_ids.append(mid)

        body_text = copy_content.get("body_text", "")
        if body_text:
            opening = body_text[:100]
            opening_entry = MaterialEntry(
                category="文案片段",
                content=opening,
                source_post_id="",
                tags=["auto_deposit", "开头"],
            )
            await cm.deposit_material(opening_entry)
            mid = opening_entry.get("material_id", "")
            if mid:
                deposited_material_ids.append(mid)

        # Write material IDs back to copy_content for calibration chain
        if deposited_material_ids:
            copy_content["used_material_ids"] = deposited_material_ids

        return {
            "copy_content": copy_content,
            "phase": WorkflowPhase.CREATING,
        }

    @staticmethod
    def _build_ripple_context(plan: dict) -> str:
        """从 content_plan 中提取 Ripple 数据构建 prompt 上下文"""
        prediction = plan.get("ripple_prediction")
        pmf = plan.get("ripple_pmf")

        if not prediction and not pmf:
            return ""

        lines = ["\nRipple 传播预测数据："]
        if prediction:
            lines.append(f"- 预计触达: {prediction.get('estimated_reach', 'N/A')}")
            lines.append(f"- 预计互动: {prediction.get('estimated_engagement', 'N/A')}")
            lines.append(f"- 爆发概率: {prediction.get('viral_probability', 'N/A')}")
        if pmf:
            if pmf.get("risk_factors"):
                lines.append(f"- PMF 风险: {', '.join(pmf['risk_factors'])}")
            if pmf.get("improvement_strategies"):
                lines.append(f"- 改进建议: {', '.join(pmf['improvement_strategies'])}")

        return "\n".join(lines)
