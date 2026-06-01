"""LangGraph graph builder — defines the complete workflow topology."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.memory import InMemoryStore

from backend.agents.nodes import (
    analyst_node,
    choice_gate_node,
    content_analyzer_node,
    content_strategist_node,
    copywriter_node,
    engagement_node,
    orchestrator_node,
    publisher_node,
    review_gate_node,
    revise_content_node,
    trend_scout_node,
    version_generator_node,
    viral_matcher_node,
    visual_designer_node,
)
from backend.graph.error_handling import get_retry_policy
from backend.graph.routers import (
    orchestrator_router,
    review_outcome,
    should_continue,
    should_optimize,
    should_plan,
)
from backend.state.schema import XHSGrowthState


def build_graph() -> StateGraph:
    """构建小红书增长引擎的 LangGraph 状态图"""
    builder = StateGraph(XHSGrowthState)

    # ── 添加节点 ──
    builder.add_node("orchestrator", orchestrator_node, retry_policy=get_retry_policy("orchestrator"))
    builder.add_node("trend_scout", trend_scout_node, retry_policy=get_retry_policy("trend_scout"))
    builder.add_node("content_strategist", content_strategist_node, retry_policy=get_retry_policy("content_strategist"))
    builder.add_node("copywriter", copywriter_node, retry_policy=get_retry_policy("copywriter"))
    builder.add_node("visual_designer", visual_designer_node, retry_policy=get_retry_policy("visual_designer"))
    builder.add_node("review_gate", review_gate_node, retry_policy=get_retry_policy("review_gate"))
    builder.add_node("publisher", publisher_node, retry_policy=get_retry_policy("publisher"))
    builder.add_node("analyst", analyst_node, retry_policy=get_retry_policy("analyst"))
    builder.add_node("engagement", engagement_node, retry_policy=get_retry_policy("engagement"))
    builder.add_node("revise_content", revise_content_node)
    # 发布前优化节点
    builder.add_node("viral_matcher", viral_matcher_node)
    builder.add_node("content_analyzer", content_analyzer_node)
    builder.add_node("version_generator", version_generator_node)
    builder.add_node("choice_gate", choice_gate_node)

    # ── 入口 ──
    builder.add_edge(START, "orchestrator")

    # ── Orchestrator 条件路由 ──
    builder.add_conditional_edges(
        "orchestrator",
        orchestrator_router,
        {
            "trend_scout": "trend_scout",
            "content_strategist": "content_strategist",
            "analyst": "analyst",
            "engagement": "engagement",
            "__end__": END,
        },
    )

    # ── 侦察后判断是否有可操作趋势 ──
    builder.add_conditional_edges(
        "trend_scout",
        should_plan,
        {
            "content_strategist": "content_strategist",
            "__end__": END,
        },
    )

    # ── 内容创作流水线 ──
    builder.add_edge("content_strategist", "copywriter")

    # ── 发布前优化流程 ──
    # copywriter → viral_matcher (搜索爆款参考)
    builder.add_edge("copywriter", "viral_matcher")

    # viral_matcher → [content_analyzer | visual_designer] (条件路由)
    builder.add_conditional_edges(
        "viral_matcher",
        should_optimize,
        {
            "content_analyzer": "content_analyzer",
            "visual_designer": "visual_designer",
        },
    )

    # content_analyzer → version_generator (生成版本)
    builder.add_edge("content_analyzer", "version_generator")

    # version_generator → choice_gate (用户选择)
    builder.add_edge("version_generator", "choice_gate")

    # choice_gate → visual_designer (选择后进入视觉设计)
    builder.add_edge("choice_gate", "visual_designer")

    # visual_designer → review_gate
    builder.add_edge("visual_designer", "review_gate")

    # ── 人工审核路由 ──
    builder.add_conditional_edges(
        "review_gate",
        review_outcome,
        {
            "publisher": "publisher",
            "revise_content": "revise_content",
            "__end__": END,
        },
    )

    # ── 修改后回到文案 ──
    builder.add_edge("revise_content", "copywriter")

    # ── 发布后分析 ──
    builder.add_edge("publisher", "analyst")

    # ── 分析后决定是否继续 ──
    builder.add_conditional_edges(
        "analyst",
        should_continue,
        {
            "orchestrator": "orchestrator",
            "__end__": END,
        },
    )

    # ── 互动完成后回到编排器 ──
    builder.add_edge("engagement", "orchestrator")

    return builder


def compile_graph_dev() -> CompiledStateGraph:
    """开发模式编译 — 使用内存检查点和内存存储"""
    builder = build_graph()
    checkpointer = MemorySaver()
    store = InMemoryStore()

    graph = builder.compile(
        checkpointer=checkpointer,
        store=store,
        # Nodes use dynamic interrupt() instead of interrupt_before
    )
    return graph


async def compile_graph_prod(db_uri: str) -> tuple[CompiledStateGraph, Any]:
    """生产模式编译 — 使用 Postgres 检查点

    Returns:
        Tuple of (compiled graph, checkpointer) so the caller can manage
        the checkpointer lifecycle (must close on shutdown).
        checkpointer is None when falling back to memory.
    """
    builder = build_graph()

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        checkpointer = AsyncPostgresSaver.from_conn_string(db_uri)
        await checkpointer.setup()
        graph = builder.compile(
            checkpointer=checkpointer,
            # Nodes use dynamic interrupt() instead of interrupt_before
        )
        return graph, checkpointer
    except ImportError:
        # Postgres 不可用时回退到内存
        graph = compile_graph_dev()
        return graph, None
