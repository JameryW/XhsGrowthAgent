"""LangGraph graph builder — defines the complete workflow topology.

Nodes, retry policies and the plain edges are declared here. The eighteen
conditional edges are not: they are data in ``backend/graph/wiring.py``, and
this function installs them from that table. See that module for why the edge
set became a declaration rather than eighteen hand-written calls.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
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
    evaluator_node,
    orchestrator_node,
    publish_gate_node,
    publisher_node,
    review_gate_node,
    revise_content_node,
    ripple_finalize_node,
    ripple_gate_node,
    ripple_late_recheck_node,
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
from backend.graph.wiring import CONDITIONAL_EDGES
from backend.state.artifacts import artifact_seam as _artifact_seam
from backend.state.checkpoint_serde import checkpoint_serde
from backend.state.enums import WorkflowMode
from backend.state.schema import XHSGrowthState

NodeFunction = Callable[..., Any]

# Node name -> (attribute name, retry-policy name or None). The attribute name
# is resolved through module globals at build time so tests and operators can
# patch `backend.graph.builder.<node>_node` without rebuilding the module.
_NODE_DEFINITIONS: tuple[tuple[str, NodeFunction, str | None], ...] = (
    ("orchestrator", orchestrator_node, "orchestrator"),
    ("trend_scout", trend_scout_node, "trend_scout"),
    ("content_strategist", content_strategist_node, "content_strategist"),
    ("copywriter", copywriter_node, "copywriter"),
    ("visual_designer", visual_designer_node, "visual_designer"),
    ("review_gate", review_gate_node, "review_gate"),
    ("evaluator_gate", evaluator_node, "evaluator_gate"),
    ("publish_gate", publish_gate_node, None),
    ("publisher", publisher_node, "publisher"),
    ("analyst", analyst_node, "analyst"),
    ("revise_content", revise_content_node, None),
    ("ripple_gate", ripple_gate_node, None),
    ("ripple_finalize", ripple_finalize_node, None),
    ("ripple_late_recheck", ripple_late_recheck_node, None),
    ("draft_gate", draft_gate_node, None),
    ("viral_matcher", viral_matcher_node, None),
    ("blogger_scout", blogger_scout_node, None),
    ("blogger_gate", blogger_gate_node, None),
    ("content_analyzer", content_analyzer_node, None),
    ("version_generator", version_generator_node, None),
    ("choice_gate", choice_gate_node, None),
    ("brief_analyzer", brief_analyzer_node, "brief_analyzer"),
    ("brief_gate", brief_gate_node, None),
    ("shooting_planner", shooting_planner_node, "shooting_planner"),
)

_DIRECT_EDGES: tuple[tuple[str, str], ...] = (
    ("viral_matcher", "blogger_scout"),
    ("blogger_scout", "blogger_gate"),
    ("brief_analyzer", "brief_gate"),
    ("brief_gate", "viral_matcher"),
    ("revise_content", "copywriter"),
    ("publisher", END),
)


def _add_nodes(builder: StateGraph[XHSGrowthState], allowed: set[str] | None = None) -> None:
    for name, function, retry_key in _NODE_DEFINITIONS:
        if allowed is not None and name not in allowed:
            continue
        function_name = getattr(function, "__name__", "")
        node_function = cast(NodeFunction, globals().get(function_name, function))
        if retry_key is None:
            builder.add_node(name, _artifact_seam(node_function))
        else:
            builder.add_node(
                name,
                _artifact_seam(node_function),
                retry_policy=get_retry_policy(retry_key),
            )


def build_graph(mode: WorkflowMode | None = None) -> StateGraph[XHSGrowthState]:
    """构建小红书增长引擎的 LangGraph 状态图。

    ``mode`` 为空时保持完整图（生产默认路径）。传入 ``WorkflowMode`` 时，
    使用 ``backend.graph.plan.export_plan(mode)`` 的可达节点集裁剪节点与边，
    生成一个真正可编译的 mode-specific 子图；未声明的节点不会出现在图中。
    """
    builder = StateGraph(XHSGrowthState)
    allowed_nodes: set[str] | None = None
    if mode is not None:
        # Lazy import: plan.export_plan() inspects the complete graph through
        # build_graph(), so importing it eagerly would close a cycle.
        from backend.graph.plan import export_plan

        allowed_nodes = set(export_plan(mode).nodes)

    # ── 添加节点 ──
    _add_nodes(builder, allowed_nodes)

    # ── 入口 ──
    if allowed_nodes is None or "orchestrator" in allowed_nodes:
        builder.add_edge(START, "orchestrator")

    # ── 条件边 ──
    # Every conditional edge is declared in backend/graph/wiring.py; filter the
    # path map so a JIT subgraph never points at a node outside its plan.
    for edge in CONDITIONAL_EDGES:
        if allowed_nodes is not None and edge.source not in allowed_nodes:
            continue
        path_map = edge.path_map()
        if allowed_nodes is not None:
            path_map = {
                answer: destination
                for answer, destination in path_map.items()
                if destination == END or destination in allowed_nodes
            }
        if path_map:
            builder.add_conditional_edges(edge.source, edge.router, path_map)

    # ── 直边 ──
    for source, destination in _DIRECT_EDGES:
        if allowed_nodes is not None and source not in allowed_nodes:
            continue
        if allowed_nodes is not None and destination != END and destination not in allowed_nodes:
            continue
        builder.add_edge(source, destination)

    return builder


def build_jit_graph(mode: WorkflowMode) -> StateGraph[XHSGrowthState]:
    """Build a mode-specific graph with only the nodes/edges in that plan.

    This is the explicit JIT entry point; ``build_graph(mode)`` remains the
    low-level call used by the compile helpers.
    """

    return build_graph(mode)


_SQLITE_DB = os.environ.get("XHS_SQLITE_PATH", ".xhs/checkpoints.sqlite")


async def compile_graph_dev(mode: WorkflowMode | None = None) -> CompiledStateGraph[Any]:
    """开发模式编译 — 使用 SQLite 持久化检查点 + 存储（带语义搜索）

    ``mode`` 为空时编译完整图；传入模式时编译该模式的独立子图。

    SQLite file location defaults to .xhs/checkpoints.sqlite (configurable
    via XHS_SQLITE_PATH env var).  Falls back to MemorySaver on ImportError.

    Store: If XHS_POSTGRES_URI is set, uses AsyncPostgresStore with semantic
    search index.  Otherwise uses InMemoryStore with index (semantic search
    enabled, but memory resets on restart).
    """
    builder = build_graph(mode) if mode is not None else build_graph()

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
        checkpointer: Any = AsyncSqliteSaver(conn=conn, serde=checkpoint_serde())
        await checkpointer.setup()
        sqlite_conn = conn
    except ImportError:
        import logging

        logging.getLogger("xhs_growth").warning(
            "langgraph-checkpoint-sqlite not installed, using MemorySaver"
        )
        checkpointer = MemorySaver(serde=checkpoint_serde())

    graph = builder.compile(
        checkpointer=checkpointer,
        store=store,
        # review_gate uses dynamic interrupt() like ripple_gate — low-risk
        # auto-pass runs inside the node; everything else interrupts there.
        interrupt_before=[
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
        try:
            await conn.close()
        except Exception as exc:
            # Logged, not silent: a swallowed close failure looks exactly like the
            # old leak (the interpreter hangs waiting for the worker thread).
            logging.getLogger("xhs_growth").warning(
                "close_dev_graph: closing SQLite checkpointer failed: %s: %s",
                type(exc).__name__,
                exc,
            )
        graph._sqlite_conn = None  # type: ignore[attr-defined]


@asynccontextmanager
async def dev_graph(mode: WorkflowMode | None = None) -> AsyncIterator[CompiledStateGraph[Any]]:
    """Compile a dev graph and ensure its SQLite checkpointer is closed on exit.

    Use `async with dev_graph() as graph:` in CLI/short-lived callers so the
    aiosqlite connection never leaks across asyncio.run boundaries.
    """
    graph = await compile_graph_dev(mode)
    try:
        yield graph
    finally:
        await close_dev_graph(graph)


async def compile_graph_prod(
    db_uri: str, mode: WorkflowMode | None = None
) -> tuple[CompiledStateGraph[Any], Any]:
    """生产模式编译 — 使用 Postgres 检查点 + Postgres 存储 + 语义搜索 + 连接池

    ``mode`` 为空时编译完整图；传入模式时编译该模式的独立子图。

    Creates a separate AsyncConnectionPool for the checkpointer.
    The pool is returned to app.py so it can be closed on shutdown
    alongside the app-level DB pool.

    Returns:
        Tuple of (compiled graph, (checkpointer, pool, store_context)) or
        (compiled graph, None) when falling back to memory.
    """
    builder = build_graph(mode) if mode is not None else build_graph()

    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
        from langgraph.store.postgres.aio import AsyncPostgresStore
        from psycopg_pool import AsyncConnectionPool

        from backend.memory.index import get_prod_store_index

        pool = None
        store_context = None
        store_context_entered = False
        graph_interrupts = [
            # review_gate uses dynamic interrupt() like ripple_gate — not here.
            "choice_gate",
            "draft_gate",
        ]

        # Initialize the two LangGraph Postgres resources in sequence.  Opening
        # both pools and running both migration sets concurrently during app
        # startup can starve the shared DB pool and produce a misleading
        # PoolTimeout, which makes the whole app fall back to in-memory state.
        async def _init_checkpointer() -> tuple[Any, Any]:
            nonlocal pool
            _pool = AsyncConnectionPool(
                db_uri, min_size=2, max_size=10, open=False, kwargs={"autocommit": True}
            )
            await _pool.open()
            _cp = AsyncPostgresSaver(conn=cast("Any", _pool), serde=checkpoint_serde())
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

        (pool, checkpointer) = await _init_checkpointer()
        (store_context, store) = await _init_store()
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
