"""LangGraph graph builder — defines the complete workflow topology."""

from __future__ import annotations

from typing import Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.checkpoint.memory import MemorySaver

from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase
from xhs_growth.graph.nodes import (
    orchestrator_node,
    trend_scout_node,
    content_strategist_node,
    copywriter_node,
    visual_designer_node,
    review_gate_node,
    publisher_node,
    analyst_node,
    engagement_node,
    revise_content_node,
)
from xhs_growth.graph.routers import should_plan, should_continue, review_outcome, orchestrator_router


def build_graph() -> StateGraph:
    """构建小红书增长引擎的 LangGraph 状态图"""
    builder = StateGraph(XHSGrowthState)

    # ── 添加节点 ──
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("trend_scout", trend_scout_node)
    builder.add_node("content_strategist", content_strategist_node)
    builder.add_node("copywriter", copywriter_node)
    builder.add_node("visual_designer", visual_designer_node)
    builder.add_node("review_gate", review_gate_node)
    builder.add_node("publisher", publisher_node)
    builder.add_node("analyst", analyst_node)
    builder.add_node("engagement", engagement_node)
    builder.add_node("revise_content", revise_content_node)

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
    builder.add_edge("copywriter", "visual_designer")
    builder.add_edge("visual_designer", "review_gate")

    # ── 人工审核路由 ──
    builder.add_conditional_edges(
        "review_gate",
        review_outcome,
        {
            "publisher": "publisher",
            "revise_content": "revise_content",
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
    """开发模式编译 — 使用内存检查点"""
    builder = build_graph()
    checkpointer = MemorySaver()

    graph = builder.compile(
        checkpointer=checkpointer,
        interrupt_before=["review_gate"],  # human-in-the-loop 审核门
    )
    return graph


async def compile_graph_prod(db_uri: str) -> CompiledStateGraph:
    """生产模式编译 — 使用 Postgres 检查点"""
    builder = build_graph()

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        async with AsyncPostgresSaver.from_conn_string(db_uri) as checkpointer:
            await checkpointer.setup()
            graph = builder.compile(
                checkpointer=checkpointer,
                interrupt_before=["review_gate"],
            )
            return graph
    except ImportError:
        # Postgres 不可用时回退到内存
        return compile_graph_dev()