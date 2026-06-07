"""LangGraph graph builder — defines the complete workflow topology."""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.memory import InMemoryStore

from backend.agents.nodes import (
    analyst_node,
    blogger_gate_node,
    blogger_scout_node,
    brief_analyzer_node,
    brief_gate_node,
    content_strategist_node,
    copywriter_node,
    engagement_node,
    orchestrator_node,
    publisher_node,
    review_gate_node,
    revise_content_node,
    ripple_gate_node,
    shooting_planner_node,
    trend_scout_node,
    visual_designer_node,
)
from backend.agents.nodes.optimization import (
    choice_gate_node,
    content_analyzer_node,
    draft_gate_node,
    version_generator_node,
    viral_matcher_node,
)
from backend.graph.error_handling import get_retry_policy
from backend.graph.routers import (
    blogger_gate_router,
    copywriter_router,
    engagement_router,
    orchestrator_router,
    review_outcome,
    ripple_gate_router,
    should_continue,
    should_plan,
    should_present_choice,
    visual_designer_router,
)
from backend.state.schema import XHSGrowthState


def build_graph() -> StateGraph:
    """构建小红书增长引擎的 LangGraph 状态图"""
    builder = StateGraph(XHSGrowthState)

    # ── 添加节点 ──
    builder.add_node(
        "orchestrator",
        orchestrator_node,
        retry_policy=get_retry_policy("orchestrator"),
    )
    builder.add_node(
        "trend_scout",
        trend_scout_node,
        retry_policy=get_retry_policy("trend_scout"),
    )
    builder.add_node(
        "content_strategist",
        content_strategist_node,
        retry_policy=get_retry_policy("content_strategist"),
    )
    builder.add_node(
        "copywriter",
        copywriter_node,
        retry_policy=get_retry_policy("copywriter"),
    )
    builder.add_node(
        "visual_designer",
        visual_designer_node,
        retry_policy=get_retry_policy("visual_designer"),
    )
    builder.add_node("review_gate", review_gate_node, retry_policy=get_retry_policy("review_gate"))
    builder.add_node("publisher", publisher_node, retry_policy=get_retry_policy("publisher"))
    builder.add_node("analyst", analyst_node, retry_policy=get_retry_policy("analyst"))
    builder.add_node("engagement", engagement_node, retry_policy=get_retry_policy("engagement"))
    builder.add_node("revise_content", revise_content_node)
    # Ripple gate — conditional interrupt when Ripple results are suboptimal
    builder.add_node("ripple_gate", ripple_gate_node)
    # 发布前优化节点
    builder.add_node("draft_gate", draft_gate_node)
    builder.add_node("viral_matcher", viral_matcher_node)
    builder.add_node("blogger_scout", blogger_scout_node)
    builder.add_node("blogger_gate", blogger_gate_node)
    builder.add_node("content_analyzer", content_analyzer_node)
    builder.add_node("version_generator", version_generator_node)
    builder.add_node("choice_gate", choice_gate_node)

    # 商单 Brief 模式节点
    builder.add_node(
        "brief_analyzer",
        brief_analyzer_node,
        retry_policy=get_retry_policy("brief_analyzer"),
    )
    builder.add_node("brief_gate", brief_gate_node)
    builder.add_node(
        "shooting_planner",
        shooting_planner_node,
        retry_policy=get_retry_policy("shooting_planner"),
    )

    # ── 入口 ──
    builder.add_edge(START, "orchestrator")

    # ── Orchestrator 条件路由 ──
    builder.add_conditional_edges(
        "orchestrator",
        orchestrator_router,
        {
            "trend_scout": "trend_scout",
            "brief_analyzer": "brief_analyzer",
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
    # content_strategist → ripple_gate (conditional interrupt for suboptimal Ripple results)
    builder.add_edge("content_strategist", "ripple_gate")

    # ripple_gate → [copywriter | content_strategist | trend_scout] (user decision)
    builder.add_conditional_edges(
        "ripple_gate",
        ripple_gate_router,
        {
            "copywriter": "copywriter",
            "content_strategist": "content_strategist",
            "brief_analyzer": "brief_analyzer",
            "trend_scout": "trend_scout",
            "__end__": END,
        },
    )

    # ── 发布前优化流程 ──
    # copywriter → [draft_gate | visual_designer] (brief mode skips draft_gate)
    builder.add_conditional_edges(
        "copywriter",
        copywriter_router,
        {
            "draft_gate": "draft_gate",
            "visual_designer": "visual_designer",
        },
    )

    # draft_gate → viral_matcher (search for viral references)
    builder.add_edge("draft_gate", "viral_matcher")

    # viral_matcher → blogger_scout (discover bloggers from viral notes)
    builder.add_edge("viral_matcher", "blogger_scout")

    # blogger_scout → blogger_gate (interrupt for user selection)
    builder.add_edge("blogger_scout", "blogger_gate")

    # blogger_gate → [shooting_planner | content_analyzer | visual_designer]
    # (routes based on workflow mode, same logic as should_brief_or_optimize)
    builder.add_conditional_edges(
        "blogger_gate",
        blogger_gate_router,
        {
            "shooting_planner": "shooting_planner",
            "content_analyzer": "content_analyzer",
            "visual_designer": "visual_designer",
        },
    )

    # content_analyzer → version_generator (生成版本)
    builder.add_edge("content_analyzer", "version_generator")

    # version_generator → [choice_gate | visual_designer]
    # (conditional — only enter choice_gate if multiple versions)
    builder.add_conditional_edges(
        "version_generator",
        should_present_choice,
        {
            "choice_gate": "choice_gate",
            "visual_designer": "visual_designer",
        },
    )

    # choice_gate → visual_designer (选择后进入视觉设计)
    builder.add_edge("choice_gate", "visual_designer")

    # ── 商单 Brief 模式流程 ──
    # brief_analyzer → brief_gate (pause for clarification if needed)
    builder.add_edge("brief_analyzer", "brief_gate")

    # brief_gate → viral_matcher (search viral posts by brief style)
    builder.add_edge("brief_gate", "viral_matcher")

    # viral_matcher already routes to blogger_scout above (trend and brief modes share this path)
    # blogger_gate routes based on workflow mode via blogger_gate_router

    # shooting_planner → ripple_gate (brief mode also checks Ripple results)
    builder.add_edge("shooting_planner", "ripple_gate")

    # visual_designer → review_gate
    # visual_designer → [review_gate | END] (brief mode ends here)
    builder.add_conditional_edges(
        "visual_designer",
        visual_designer_router,
        {
            "review_gate": "review_gate",
            "__end__": END,
        },
    )

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
            "engagement": "engagement",
            "__end__": END,
        },
    )

    # ── 互动完成后根据执行模式决定下一步 ──
    builder.add_conditional_edges(
        "engagement",
        engagement_router,
        {
            "orchestrator": "orchestrator",
            "__end__": END,
        },
    )

    return builder


def compile_graph_dev() -> CompiledStateGraph:
    """开发模式编译 — 使用内存检查点和内存存储"""
    builder = build_graph()
    checkpointer = MemorySaver()
    store = InMemoryStore()

    graph = builder.compile(
        checkpointer=checkpointer,
        store=store,
        interrupt_before=[
            "review_gate",
            "choice_gate",
            "draft_gate",
            "brief_gate",
            "ripple_gate",
            "blogger_gate",
        ],
    )
    return graph


async def compile_graph_prod(db_uri: str) -> tuple[CompiledStateGraph, Any]:
    """生产模式编译 — 使用 Postgres 检查点 + 连接池

    Creates a separate AsyncConnectionPool for the checkpointer.
    The pool is returned to app.py so it can be closed on shutdown
    alongside the app-level DB pool.

    Returns:
        Tuple of (compiled graph, (checkpointer, pool)) or (compiled graph, None)
        when falling back to memory.
    """
    builder = build_graph()

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.memory import InMemoryStore
        from psycopg_pool import AsyncConnectionPool

        pool = AsyncConnectionPool(
            db_uri, min_size=2, max_size=10, open=False, kwargs={"autocommit": True}
        )
        await pool.open()
        checkpointer = AsyncPostgresSaver(conn=pool)
        await checkpointer.setup()
        store = InMemoryStore()
        graph = builder.compile(
            checkpointer=checkpointer,
            store=store,
            interrupt_before=[
                "review_gate",
                "choice_gate",
                "draft_gate",
                "brief_gate",
                "ripple_gate",
                "blogger_gate",
            ],
        )
        # Return pool so app.py can close it on shutdown
        return graph, (checkpointer, pool)
    except ImportError:
        # Postgres 不可用时回退到内存
        graph = compile_graph_dev()
        return graph, None
