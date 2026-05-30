"""Conditional edge routers for the LangGraph workflow."""

from __future__ import annotations

import os
from typing import Literal

from langgraph.graph import END

from backend.state.enums import WorkflowPhase, ContentStatus
from backend.state.schema import XHSGrowthState


def _xhs_configured() -> bool:
    """Check if XHS platform credentials are available."""
    return bool(os.environ.get("XHS_COOKIE") and os.environ.get("XHS_USER_ID"))


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


def review_outcome(state: XHSGrowthState) -> Literal["publisher", "revise_content", "__end__"]:
    """人工审核路由 — 根据审核结果决定下一步"""
    feedback = state.get("human_feedback", {})
    decision = feedback.get("decision", ContentStatus.REJECTED)
    # Handle both enum and string values for frontend compatibility
    if decision == ContentStatus.APPROVED or decision == "approved":
        # Skip publishing if XHS credentials are not configured (preview-only mode)
        if not _xhs_configured():
            return "__end__"
        return "publisher"
    if decision == ContentStatus.NEEDS_REVISION or decision == "needs_revision":
        return "revise_content"
    # rejected → end workflow (do not enter revision loop)
    return "__end__"


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


# ── 发布前优化路由 ──


def should_optimize(state: XHSGrowthState) -> Literal["content_analyzer", "visual_designer"]:
    """判断是否进入优化流程."""
    # 用户明确跳过优化 → 直接进入视觉设计
    if state.get("skip_optimization"):
        return "visual_designer"

    # 有爆款参考 → 进入对比分析
    viral_posts = state.get("viral_posts", [])
    if viral_posts and len(viral_posts) > 0:
        return "content_analyzer"

    # 无爆款参考 → 直接进入视觉设计
    return "visual_designer"


def choice_outcome(state: XHSGrowthState) -> Literal["visual_designer"]:
    """版本选择后路由 — 统一进入视觉设计."""
    # 用户选择完成后，进入视觉设计节点
    return "visual_designer"