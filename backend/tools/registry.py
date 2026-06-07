"""Tool registry — maps agents to their available tools."""

from __future__ import annotations

from langchain_core.tools import BaseTool


class ToolRegistry:
    """Central registry for agent tools."""

    _tools: dict[str, BaseTool] = {}
    _agent_tools: dict[str, list[str]] = {
        "trend_scout": ["xhs_trending", "keyword_monitor", "competitor_analyzer"],
        "content_strategist": [
            "topic_scorer",
            "timing_optimizer",
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
        "blogger_scout": ["xhs_trending", "keyword_monitor"],
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
        from backend.tools.ripple.client import (
            ripple_cancel_simulation,
            ripple_generate_report,
            ripple_get_simulation_log,
            ripple_get_simulation_result,
            ripple_get_simulation_status,
            ripple_predict_content_spread,
            ripple_validate_pmf,
        )

        cls.register_many(
            [
                ripple_predict_content_spread,
                ripple_validate_pmf,
                ripple_get_simulation_status,
                ripple_get_simulation_result,
                ripple_get_simulation_log,
                ripple_generate_report,
                ripple_cancel_simulation,
            ]
        )

    @classmethod
    def register_scheduling_tools(cls) -> None:
        """注册所有调度工具"""
        from backend.tools.scheduling import timing_optimizer

        cls.register_many(
            [
                timing_optimizer,
            ]
        )

    @classmethod
    def register_content_tools(cls) -> None:
        """注册所有内容生成工具"""
        from backend.tools.content import (
            hashtag_researcher,
            image_prompt_generator,
            layout_recommender,
            style_library,
            title_generator,
        )

        cls.register_many(
            [
                hashtag_researcher,
                title_generator,
                image_prompt_generator,
                layout_recommender,
                style_library,
            ]
        )

    @classmethod
    def register_xhs_tools(cls) -> None:
        """注册所有小红书平台工具"""
        from backend.tools.xhs.publisher import (
            ab_test_manager,
            post_scheduler,
            xhs_publisher,
        )

        cls.register_many(
            [
                xhs_publisher,
                ab_test_manager,
                post_scheduler,
            ]
        )

    @classmethod
    def register_all_tools(cls) -> None:
        """注册所有可用工具"""
        cls.register_ripple_tools()
        cls.register_scheduling_tools()
        cls.register_content_tools()
        cls.register_xhs_tools()
