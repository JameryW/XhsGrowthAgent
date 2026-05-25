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
from xhs_growth.realtime import EventBusService, EventType
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
    result = await _orchestrator(state, store=store)

    # Emit phase change event if phase changed
    old_phase = state.get("phase")
    new_phase = result.get("phase")
    if new_phase and new_phase != old_phase:
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_PHASE_CHANGED,
            thread_id=state.get("thread_id"),
            payload={
                "old_phase": old_phase,
                "new_phase": new_phase,
            },
        )

    return result


async def trend_scout_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _trend_scout(state, store=store)

    # Emit data updated event for trend_data
    thread_id = state.get("thread_id")
    if result.get("trend_data"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "trend_data", "data": result.get("trend_data")},
        )

    return result


async def content_strategist_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _content_strategist(state, store=store)

    # Emit data updated event for content_plan
    thread_id = state.get("thread_id")
    if result.get("content_plan"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "content_plan", "data": result.get("content_plan")},
        )

    return result


async def copywriter_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _copywriter(state, store=store)

    # Emit data updated event for copy_content
    thread_id = state.get("thread_id")
    if result.get("copy_content"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "copy_content", "data": result.get("copy_content")},
        )

    return result


async def visual_designer_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _visual_designer(state, store=store)

    # Emit data updated event for visual_plan
    thread_id = state.get("thread_id")
    if result.get("visual_plan"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "visual_plan", "data": result.get("visual_plan")},
        )

    return result


async def review_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """Human-in-the-loop 审核门 — 图在此节点前中断"""
    # 使用 interrupt() 实现人工审核
    from langgraph.types import interrupt

    copy = state.get("copy_content", {})
    visual = state.get("visual_plan", {})
    plan = state.get("content_plan", {})

    # Emit review pending event before interrupt
    thread_id = state.get("thread_id")
    EventBusService.get_instance().emit(
        EventType.REVIEW_PENDING,
        thread_id=thread_id,
        payload={
            "content_plan": plan,
            "copy_content": copy,
            "visual_plan": visual,
        },
    )

    review_payload = {
        "topic": plan.get("selected_topic", ""),
        "titles": copy.get("title_candidates", []),
        "body_preview": copy.get("body_text", "")[:200],
        "cover_prompt": visual.get("cover_prompt", ""),
        "hashtags": copy.get("hashtags", []),
    }

    # interrupt() 暂停执行，将 payload 发送给调用方
    decision = interrupt(review_payload)

    # decision 是人工审核结果: {"decision": "approved/rejected", "comments": "...", "revisions": [...]}
    if decision.get("decision") == ContentStatus.APPROVED:
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
    result = await _publisher(state, store=store)

    # Emit workflow completed event after publish
    thread_id = state.get("thread_id")
    if result.get("publish_result"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_COMPLETED,
            thread_id=thread_id,
            payload={"publish_result": result.get("publish_result")},
        )

    return result


async def analyst_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _analyst(state, store=store)

    # Emit data updated event for analytics
    thread_id = state.get("thread_id")
    if result.get("analytics"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "analytics", "data": result.get("analytics")},
        )

    return result


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