"""Graph node functions — wraps agent calls into LangGraph nodes."""

from __future__ import annotations

import logging
from typing import Any

from langgraph.store.base import BaseStore

from xhs_growth.agents.orchestrator import OrchestratorAgent
from xhs_growth.agents.trend_scout import TrendScoutAgent
from xhs_growth.agents.content_strategist import ContentStrategistAgent
from xhs_growth.agents.copywriter import CopywriterAgent
from xhs_growth.agents.visual_designer import VisualDesignerAgent
from xhs_growth.agents.publisher import PublisherAgent
from xhs_growth.agents.analyst import AnalystAgent
from xhs_growth.agents.engagement import EngagementAgent
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase, ContentStatus

logger = logging.getLogger("xhs_growth.graph.nodes")

# ── Agent instances (单例) ──
_orchestrator = OrchestratorAgent()
_trend_scout = TrendScoutAgent()
_content_strategist = ContentStrategistAgent()
_copywriter = CopywriterAgent()
_visual_designer = VisualDesignerAgent()
_publisher = PublisherAgent()
_analyst = AnalystAgent()
_engagement = EngagementAgent()


async def orchestrator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    return await _orchestrator(state, store=store)


async def trend_scout_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    return await _trend_scout(state, store=store)


async def content_strategist_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    return await _content_strategist(state, store=store)


async def copywriter_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    return await _copywriter(state, store=store)


async def visual_designer_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    return await _visual_designer(state, store=store)


async def review_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Human-in-the-loop 审核门 — 图在此节点前中断"""
    # 使用 interrupt() 实现人工审核
    from langgraph.types import interrupt

    copy = state.get("copy_content", {})
    visual = state.get("visual_plan", {})
    plan = state.get("content_plan", {})

    review_payload = {
        "topic": plan.get("selected_topic", ""),
        "titles": copy.get("title_candidates", []),
        "body_preview": copy.get("body_text", "")[:200],
        "cover_prompt": visual.get("cover_prompt", ""),
        "hashtags": copy.get("hashtags", []),
    }

    # interrupt() 暂停执行，将 payload 发送给调用方
    decision = interrupt(review_payload)

    # decision 是人工审核结果: {"decision": "approved/needs_revision/rejected", "comments": "...", "revisions": [...]}
    # Handle both enum and string values for compatibility
    decision_value = decision.get("decision")
    if decision_value == ContentStatus.APPROVED or decision_value == "approved":
        return {
            "human_feedback": decision,
            "phase": WorkflowPhase.REVIEWING,
        }
    else:
        return {
            "human_feedback": decision,
            "phase": WorkflowPhase.REVIEWING,
        }


async def publisher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    return await _publisher(state, store=store)


async def analyst_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    return await _analyst(state, store=store)


async def engagement_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    return await _engagement(state, store=store)


async def revise_content_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """修改内容 — 将人工反馈注入到文案重写"""
    feedback = state.get("human_feedback", {})
    revisions = feedback.get("revisions", [])

    # 清除之前的文案内容，让文案 Agent 重新生成
    return {
        "copy_content": {},  # 清空，触发重写
        "visual_plan": {},   # 清空，触发重设计
        "phase": WorkflowPhase.CREATING,
    }