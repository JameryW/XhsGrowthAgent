"""Brief Analyzer agent — parses commercial brief text/documents into structured data."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.brief_analyzer")

# Confidence threshold below which we flag the brief as vague
_CLARIFICATION_THRESHOLD = 0.6


class BriefAnalyzerAgent(BaseAgent):
    task_type = TaskType.BRIEF_ANALYSIS
    agent_name = "brief_analyzer"
    prompt_file = "brief_analyzer.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        brief_content = state.get("brief_content", {})
        raw_text = brief_content.get("raw_text", "")

        if not raw_text:
            return {
                "error": "No brief content provided",
                "phase": WorkflowPhase.ERROR,
            }

        # Parse the brief using LLM
        system_prompt = self._build_system_prompt(state)
        user_msg = f"""请解析以下商单 brief，提取结构化信息：

---
{raw_text}
---

请输出 JSON 格式，包含以下字段：
- brand_name: 品牌名称
- product_name: 产品名称
- product_specs: 产品规格列表
- selling_points: 必提卖点列表
- required_keywords: 必含关键词列表
- required_hashtags: 必带话题列表
- optional_hashtags: 选带话题列表
- content_direction: 内容方向
- target_audience: 目标受众
- style_requirements: 风格/视觉要求
- shooting_requirements: 拍摄要求
- notes: 特殊注意事项列表
- confidence: 解析置信度 (0-1，信息越模糊越低)"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        parsed = self._parse_json_response(response.content)

        # Merge with existing brief_content (preserves raw_text, source_type)
        brief_result = {
            **brief_content,
            "brand_name": parsed.get("brand_name", ""),
            "product_name": parsed.get("product_name", ""),
            "product_specs": parsed.get("product_specs", []),
            "selling_points": parsed.get("selling_points", []),
            "required_keywords": parsed.get("required_keywords", []),
            "required_hashtags": parsed.get("required_hashtags", []),
            "optional_hashtags": parsed.get("optional_hashtags", []),
            "content_direction": parsed.get("content_direction", ""),
            "target_audience": parsed.get("target_audience", ""),
            "style_requirements": parsed.get("style_requirements", ""),
            "shooting_requirements": parsed.get("shooting_requirements", ""),
            "notes": parsed.get("notes", []),
            "confidence": parsed.get("confidence", 0.5),
        }

        result: dict[str, Any] = {
            "brief_content": brief_result,
            "phase": WorkflowPhase.BRIEFING,
        }

        # If confidence is low, generate clarification questions
        confidence = parsed.get("confidence", 0.5)
        if confidence < _CLARIFICATION_THRESHOLD:
            clarification = await self._generate_clarification(brief_result, raw_text, state)
            result["brief_clarification"] = clarification
        else:
            result["brief_clarification"] = {"questions": [], "resolved": True}

        return result

    async def _generate_clarification(
        self, brief_result: dict, raw_text: str, state: XHSGrowthState
    ) -> dict[str, Any]:
        """Generate clarification questions for vague briefs."""
        system_prompt = self._build_system_prompt(state)
        user_msg = f"""以下商单 brief 解析置信度较低，请生成澄清问题：

已解析的信息：
{brief_result}

原始 brief：
{raw_text[:1000]}

请输出 JSON 格式的澄清问题列表，每个问题包含：
- field: 需要澄清的字段名
- question: 向用户提问的问题
- options: 2-3个建议选项列表
- inferred_value: LLM 推断的默认值"""

        response = await self.model.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_msg),
        ])

        parsed = self._parse_json_response(response.content)
        if isinstance(parsed, list):
            questions = parsed
        else:
            questions = parsed.get("questions", [])

        return {
            "questions": questions,
            "resolved": False,
        }


__all__ = ["BriefAnalyzerAgent"]
