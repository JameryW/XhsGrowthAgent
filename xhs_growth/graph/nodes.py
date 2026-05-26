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
from xhs_growth.agents.viral_matcher import ViralMatcherAgent
from xhs_growth.agents.content_analyzer import ContentAnalyzerAgent
from xhs_growth.agents.version_generator import VersionGeneratorAgent
from xhs_growth.realtime import EventBusService, EventType
from xhs_growth.state.schema import XHSGrowthState
from xhs_growth.state.enums import WorkflowPhase, ContentStatus

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
_viral_matcher = ViralMatcherAgent()
_content_analyzer = ContentAnalyzerAgent()
_version_generator = VersionGeneratorAgent()


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


# ── 发布前优化节点 ──


async def viral_matcher_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """爆款匹配节点 — 搜索和匹配爆款笔记."""
    result = await _viral_matcher(state, store=store)

    # Emit data updated event for viral_posts
    thread_id = state.get("thread_id")
    if result.get("viral_posts"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "viral_posts", "data": result.get("viral_posts")},
        )

    return result


async def content_analyzer_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """对比分析节点 — 分析草稿与爆款笔记的差距."""
    result = await _content_analyzer(state, store=store)

    # Emit data updated event for optimization_analysis
    thread_id = state.get("thread_id")
    if result.get("optimization_analysis"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "optimization_analysis", "data": result.get("optimization_analysis")},
        )

    return result


async def version_generator_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """版本生成节点 — 生成 A/B/C 三版优化内容."""
    result = await _version_generator(state, store=store)

    # Emit data updated event for content_versions
    thread_id = state.get("thread_id")
    if result.get("content_versions"):
        EventBusService.get_instance().emit(
            EventType.WORKFLOW_DATA_UPDATED,
            thread_id=thread_id,
            payload={"data_type": "content_versions", "data": result.get("content_versions")},
        )

    return result


async def choice_gate_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    """版本选择门 — 用户选择 A/B/C 版本."""
    from langgraph.types import interrupt

    versions = state.get("content_versions", [])
    draft = state.get("draft_content", {})
    analysis = state.get("optimization_analysis", {})

    # Emit choice pending event before interrupt
    thread_id = state.get("thread_id")
    EventBusService.get_instance().emit(
        EventType.WORKFLOW_DATA_UPDATED,
        thread_id=thread_id,
        payload={
            "data_type": "choice_pending",
            "data": {
                "versions": versions,
                "draft": draft,
                "analysis": analysis,
            },
        },
    )

    # Prepare choice payload for frontend
    choice_payload = {
        "versions": [
            {
                "version_id": v.get("version_id"),
                "version_type": v.get("version_type"),
                "title": v.get("title"),
                "body_preview": v.get("body", "")[:200],
                "hashtags": v.get("hashtags", []),
                "style_suggestion": v.get("style_suggestion", ""),
                "predicted_score": v.get("predicted_score", 0),
            }
            for v in versions
        ],
        "original_draft": {
            "title": draft.get("title", ""),
            "body_preview": draft.get("text", "")[:200],
        },
        "analysis_summary": {
            "gaps_count": len(analysis.get("gaps", [])),
            "suggestions_count": len(analysis.get("suggestions", [])),
            "viral_patterns": analysis.get("viral_patterns", []),
        },
    }

    # interrupt() 暂停执行，等待用户选择
    decision = interrupt(choice_payload)

    # decision 是用户选择结果: {"selected_version": "A/B/C", "version_id": "..."}
    selected_version_id = decision.get("version_id")
    selected_version_type = decision.get("selected_version")

    # 从版本列表中找到选中版本
    selected_version = next(
        (v for v in versions if v.get("version_id") == selected_version_id),
        None
    )

    if selected_version:
        # 将选中版本内容写入 copy_content 和 visual_plan
        return {
            "selected_version": selected_version_id,
            "copy_content": {
                "title_candidates": [selected_version.get("title", "")],
                "body_text": selected_version.get("body", ""),
                "hashtags": selected_version.get("hashtags", []),
                "tone": selected_version.get("tone", ""),
            },
            "visual_plan": {
                "cover_prompt": selected_version.get("style_suggestion", ""),
                "style": selected_version.get("visual_style", ""),
                "color_palette": selected_version.get("color_palette", {}),
            },
            "phase": WorkflowPhase.CREATING,
        }
    else:
        # 未找到选中版本，保持原状态
        logger.warning(f"Selected version not found: {selected_version_id}")
        return {
            "phase": WorkflowPhase.CREATING,
        }