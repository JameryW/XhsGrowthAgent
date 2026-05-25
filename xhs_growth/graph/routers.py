"""Conditional edge routers for the LangGraph workflow."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END

from xhs_growth.state.enums import WorkflowPhase, ContentStatus
from xhs_growth.state.schema import XHSGrowthState


def orchestrator_router(state: XHSGrowthState) -> str:
    """编排器路由 — 根据当前阶段决定下一个节点"""
    phase = state.get("phase", WorkflowPhase.IDLE)

    routing = {
        WorkflowPhase.SCOUTING: "trend_scout",
        WorkflowPhase.PLANNING: "content_strategist",
        WorkflowPhase.ANALYZING: "analyst",
        WorkflowPhase.ENGAGING: "engagement",
        WorkflowPhase.ERROR: "__end__",
        WorkflowPhase.COMPLETED: "__end__",
        WorkflowPhase.IDLE: "trend_scout",
    }

    return routing.get(phase, "trend_scout")


def should_plan(state: XHSGrowthState) -> Literal["content_strategist", "__end__"]:
    """侦察后判断是否有可操作的趋势"""
    trend_data = state.get("trend_data", {})
    hot_topics = trend_data.get("hot_topics", [])
    if hot_topics:
        return "content_strategist"
    return "__end__"


def review_outcome(state: XHSGrowthState) -> Literal["publisher", "revise_content"]:
    """人工审核路由 — 根据审核结果决定下一步"""
    feedback = state.get("human_feedback", {})
    decision = feedback.get("decision", ContentStatus.REJECTED)
    # Handle both enum and string values for frontend compatibility
    if decision == ContentStatus.APPROVED or decision == "approved":
        return "publisher"
    # needs_revision and rejected both go to revise_content
    return "revise_content"


def should_continue(state: XHSGrowthState) -> Literal["orchestrator", "__end__"]:
    """分析后决定是否继续下一个周期"""
    phase = state.get("phase", WorkflowPhase.IDLE)
    error = state.get("error")

    # 有错误 → 结束
    if error:
        return "__end__"

    # 分析完成 → 回到编排器开始新周期
    if phase == WorkflowPhase.ANALYZING:
        return "orchestrator"

    return "__end__"