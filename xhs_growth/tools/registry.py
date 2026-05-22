"""Tool registry — maps agents to their available tools."""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool


class ToolRegistry:
    """Central registry for agent tools."""

    _tools: dict[str, BaseTool] = {}
    _agent_tools: dict[str, list[str]] = {
        "trend_scout": ["xhs_trending", "keyword_monitor", "competitor_analyzer"],
        "content_strategist": [
            "topic_scorer",
            "timing_optimizer",
            "calendar_manager",
            # Ripple — 传播预测 + PMF 验证
            "ripple_predict_content_spread",
            "ripple_validate_pmf",
        ],
        "copywriter": [
            "hashtag_researcher",
            "title_generator",
            # Ripple — 文案传播预测
            "ripple_predict_content_spread",
        ],
        "visual_designer": ["image_prompt_generator", "layout_recommender", "style_library"],
        "publisher": ["xhs_publisher", "ab_test_manager", "post_scheduler"],
        "analyst": [
            "analytics_reader",
            "pattern_detector",
            "report_generator",
            # Ripple — 模拟报告
            "ripple_get_simulation_result",
            "ripple_get_simulation_log",
            "ripple_generate_report",
        ],
        "engagement": ["comment_replier", "dm_handler", "escalation_flagger"],
    }

    @classmethod
    def register(cls, tool: BaseTool) -> None:
        cls._tools[tool.name] = tool

    @classmethod
    def register_many(cls, tools: list[BaseTool]) -> None:
        for tool in tools:
            cls.register(tool)

    @classmethod
    def get_tools_for_agent(cls, agent_name: str) -> list[BaseTool]:
        tool_names = cls._agent_tools.get(agent_name, [])
        return [cls._tools[name] for name in tool_names if name in cls._tools]

    @classmethod
    def get_all_tools(cls) -> list[BaseTool]:
        return list(cls._tools.values())

    @classmethod
    def available_tool_names(cls) -> list[str]:
        return list(cls._tools.keys())

    @classmethod
    def register_ripple_tools(cls) -> None:
        """注册所有 Ripple MCP 工具"""
        from xhs_growth.tools.ripple.client import (
            ripple_predict_content_spread,
            ripple_validate_pmf,
            ripple_get_simulation_status,
            ripple_get_simulation_result,
            ripple_get_simulation_log,
            ripple_generate_report,
        )

        cls.register_many([
            ripple_predict_content_spread,
            ripple_validate_pmf,
            ripple_get_simulation_status,
            ripple_get_simulation_result,
            ripple_get_simulation_log,
            ripple_generate_report,
        ])