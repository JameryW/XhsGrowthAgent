"""LangGraph graph builder — defines the complete workflow topology."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Any, cast

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
    choice_outcome,
    content_analyzer_router,
    copywriter_router,
    draft_gate_router,
    engagement_router,
    orchestrator_router,
    review_outcome,
    ripple_gate_router,
    shooting_planner_router,
    should_continue,
    should_plan,
    should_present_choice,
    visual_designer_router,
)
from backend.state.schema import XHSGrowthState


def build_graph() -> StateGraph[XHSGrowthState]:
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
            "trend_scout": "trend_scout",
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
    # copywriter → [draft_gate | __end__] (terminal states → __end__)
    builder.add_conditional_edges(
        "copywriter",
        copywriter_router,
        {
            "draft_gate": "draft_gate",
            "__end__": "__end__",
        },
    )

    # draft_gate → [viral_matcher | shooting_planner]
    # (from copywriter → viral_matcher; from blogger_gate → shooting_planner)
    builder.add_conditional_edges(
        "draft_gate",
        draft_gate_router,
        {
            "viral_matcher": "viral_matcher",
            "shooting_planner": "shooting_planner",
        },
    )

    # viral_matcher → blogger_scout (discover bloggers from viral notes)
    builder.add_edge("viral_matcher", "blogger_scout")

    # blogger_scout → blogger_gate (interrupt for user selection)
    builder.add_edge("blogger_scout", "blogger_gate")

    # blogger_gate → [copywriter | draft_gate | __end__]
    # Brief mode: copywriter (AI generates copy from brief + blogger notes)
    # Trend mode: draft_gate (user writes draft manually)
    # Terminal: __end__
    builder.add_conditional_edges(
        "blogger_gate",
        blogger_gate_router,
        {
            "copywriter": "copywriter",
            "draft_gate": "draft_gate",
            "__end__": "__end__",
        },
    )

    # content_analyzer → [choice_gate | version_generator | __end__]
    # If copywriter generated style variants → choice_gate (style selection)
    # Otherwise → version_generator (A/B/C generation)
    builder.add_conditional_edges(
        "content_analyzer",
        content_analyzer_router,
        {
            "choice_gate": "choice_gate",
            "version_generator": "version_generator",
            "__end__": "__end__",
        },
    )

    # version_generator → [choice_gate | visual_designer | __end__]
    # (conditional — only enter choice_gate if multiple versions)
    builder.add_conditional_edges(
        "version_generator",
        should_present_choice,
        {
            "choice_gate": "choice_gate",
            "visual_designer": "visual_designer",
            "__end__": "__end__",
        },
    )

    # choice_gate → [version_generator | visual_designer]
    # Style selection (first gate) → version_generator for A/B/C
    # Version selection (second gate) → visual_designer
    builder.add_conditional_edges(
        "choice_gate",
        choice_outcome,
        {
            "version_generator": "version_generator",
            "visual_designer": "visual_designer",
        },
    )

    # ── 商单 Brief 模式流程 ──
    # brief_analyzer → brief_gate (pause for clarification if needed)
    builder.add_edge("brief_analyzer", "brief_gate")

    # brief_gate → viral_matcher (search viral posts by brief style)
    builder.add_edge("brief_gate", "viral_matcher")

    # viral_matcher already routes to blogger_scout above (trend and brief modes share this path)
    # blogger_gate routes based on workflow mode via blogger_gate_router

    # shooting_planner → [content_analyzer | visual_designer | __end__]
    builder.add_conditional_edges(
        "shooting_planner",
        shooting_planner_router,
        {
            "content_analyzer": "content_analyzer",
            "visual_designer": "visual_designer",
            "__end__": "__end__",
        },
    )

    # visual_designer → review_gate (both modes go through review)
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

    # ── 发布后直接结束（analyst 改为手动触发）──
    builder.add_edge("publisher", END)

    # analyst is kept as a node but no longer auto-triggered after publish.
    # It can be reached by resuming the workflow with phase=analyzing.

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


_SQLITE_DB = os.environ.get("XHS_SQLITE_PATH", ".xhs/checkpoints.sqlite")


async def compile_graph_dev() -> CompiledStateGraph[Any]:
    """开发模式编译 — 使用 SQLite 持久化检查点 + 存储（带语义搜索）

    SQLite file location defaults to .xhs/checkpoints.sqlite (configurable
    via XHS_SQLITE_PATH env var).  Falls back to MemorySaver on ImportError.

    Store: If XHS_POSTGRES_URI is set, uses AsyncPostgresStore with semantic
    search index.  Otherwise uses InMemoryStore with index (semantic search
    enabled, but memory resets on restart).
    """
    builder = build_graph()

    from backend.memory.index import get_prod_store_index, get_store_index

    store_index = get_store_index()
    store: Any = InMemoryStore(index=store_index)

    # If Postgres URI is available, use persistent store with semantic search
    pg_uri = os.environ.get("XHS_POSTGRES_URI", "")
    store_context: Any = None
    store_context_entered = False

    if pg_uri:
        try:
            from langgraph.store.postgres.aio import AsyncPostgresStore

            prod_index = cast("Any", get_prod_store_index())
            store_context = AsyncPostgresStore.from_conn_string(
                pg_uri,
                pool_config={"min_size": 1, "max_size": 5},
                index=prod_index,
            )
            store = await store_context.__aenter__()
            store_context_entered = True
            await store.setup()
        except Exception as e:
            import logging

            logging.getLogger("xhs_growth").warning(
                f"Failed to create Postgres store for dev, falling back to InMemoryStore: {e}"
            )
            if store_context_entered and store_context is not None:
                await store_context.__aexit__(None, None, None)
            # Reset store to InMemoryStore since Postgres store failed
            store = InMemoryStore(index=store_index)

    sqlite_conn: Any = None
    try:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        # Ensure parent directory exists
        db_path = Path(_SQLITE_DB)
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = await aiosqlite.connect(str(db_path))
        checkpointer: Any = AsyncSqliteSaver(conn=conn)
        await checkpointer.setup()
        sqlite_conn = conn
    except ImportError:
        import logging

        logging.getLogger("xhs_growth").warning(
            "langgraph-checkpoint-sqlite not installed, using MemorySaver"
        )
        checkpointer = MemorySaver()

    graph = builder.compile(
        checkpointer=checkpointer,
        store=store,
        interrupt_before=[
            "review_gate",
            "choice_gate",
            "draft_gate",
        ],
    )
    # ponytail: expose sqlite conn so callers can close it (avoid aiosqlite
    # 'Event loop is closed' / 'was deleted before being closed' on shutdown).
    # prod path returns resources explicitly; dev stashes on the graph itself.
    graph._sqlite_conn = sqlite_conn  # type: ignore[attr-defined]
    return graph


async def close_dev_graph(graph: CompiledStateGraph[Any]) -> None:
    """Close the SQLite checkpointer connection owned by a dev-compiled graph.

    Call from a finally block in CLI/short-lived callers. No-op for MemorySaver
    fallback or prod graphs (which manage their own pool).
    """
    conn = getattr(graph, "_sqlite_conn", None)
    if conn is not None:
        with suppress(Exception):
            await conn.close()
        graph._sqlite_conn = None  # type: ignore[attr-defined]


@asynccontextmanager
async def dev_graph() -> AsyncIterator[CompiledStateGraph[Any]]:
    """Compile a dev graph and ensure its SQLite checkpointer is closed on exit.

    Use `async with dev_graph() as graph:` in CLI/short-lived callers so the
    aiosqlite connection never leaks across asyncio.run boundaries.
    """
    graph = await compile_graph_dev()
    try:
        yield graph
    finally:
        await close_dev_graph(graph)


async def compile_graph_prod(db_uri: str) -> tuple[CompiledStateGraph[Any], Any]:
    """生产模式编译 — 使用 Postgres 检查点 + Postgres 存储 + 语义搜索 + 连接池

    Creates a separate AsyncConnectionPool for the checkpointer.
    The pool is returned to app.py so it can be closed on shutdown
    alongside the app-level DB pool.

    Returns:
        Tuple of (compiled graph, (checkpointer, pool, store_context)) or
        (compiled graph, None) when falling back to memory.
    """
    builder = build_graph()

    try:
        import asyncio

        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore
        from psycopg_pool import AsyncConnectionPool

        from backend.memory.index import get_prod_store_index

        pool = None
        store_context = None
        store_context_entered = False
        graph_interrupts = [
            "review_gate",
            "choice_gate",
            "draft_gate",
        ]

        # ponytail: open checkpointer pool + store pool in parallel
        async def _init_checkpointer() -> tuple[Any, Any]:
            nonlocal pool
            _pool = AsyncConnectionPool(
                db_uri, min_size=2, max_size=10, open=False, kwargs={"autocommit": True}
            )
            await _pool.open()
            _cp = AsyncPostgresSaver(conn=cast("Any", _pool))
            await _cp.setup()
            return _pool, _cp

        async def _init_store() -> tuple[Any, Any]:
            nonlocal store_context, store_context_entered
            prod_index = get_prod_store_index()
            _ctx = AsyncPostgresStore.from_conn_string(
                db_uri,
                pool_config={"min_size": 2, "max_size": 10},
                index=cast("Any", prod_index),
            )
            _store = await _ctx.__aenter__()
            store_context_entered = True
            await _store.setup()
            return _ctx, _store

        (pool, checkpointer), (store_context, store) = await asyncio.gather(
            _init_checkpointer(), _init_store()
        )
        graph = builder.compile(
            checkpointer=checkpointer,
            store=store,
            interrupt_before=graph_interrupts,
        )
        # Return resources so app.py can close them on shutdown.
        return graph, (checkpointer, pool, store_context)
    except ImportError:
        # Postgres 不可用时回退到 SQLite
        graph = await compile_graph_dev()
        return graph, None
    except Exception:
        if store_context_entered and store_context is not None:
            await store_context.__aexit__(None, None, None)
        if pool is not None:
            await pool.close()
        raise
