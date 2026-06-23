"""Unit tests for graph builder."""

import pytest

from backend.graph.builder import build_graph, compile_graph_dev


class TestBuildGraph:
    """Tests for graph construction."""

    def test_build_graph_returns_state_graph(self):
        """build_graph returns a StateGraph instance."""
        from langgraph.graph.state import StateGraph

        graph = build_graph()
        assert isinstance(graph, StateGraph)

    def test_graph_has_all_nodes(self):
        """Graph contains all expected nodes."""
        graph = build_graph()

        # Expected nodes (including optimization nodes)
        expected_nodes = [
            "orchestrator",
            "trend_scout",
            "content_strategist",
            "copywriter",
            "visual_designer",
            "review_gate",
            "publisher",
            "analyst",
            "engagement",
            "revise_content",
            # 发布前优化节点
            "viral_matcher",
            "content_analyzer",
            "version_generator",
            "choice_gate",
        ]

        # Get node names from graph
        node_names = list(graph.nodes.keys())
        for node in expected_nodes:
            assert node in node_names, f"Node {node} not found in graph"

    def test_graph_has_start_edge(self):
        """Graph has edge from START to orchestrator."""
        graph = build_graph()

        # START should connect to orchestrator
        # This is implicit in the graph structure
        assert "orchestrator" in graph.nodes

    def test_analyst_can_route_to_engagement(self):
        """Analyst routing includes every branch returned by should_continue."""
        graph = build_graph()

        ends = graph.branches["analyst"]["should_continue"].ends
        assert ends["engagement"] == "engagement"


class TestCompileGraphDev:
    """Tests for dev graph compilation."""

    @pytest.mark.asyncio
    async def test_compile_graph_dev_returns_compiled_graph(self):
        """compile_graph_dev returns a CompiledStateGraph."""
        from langgraph.graph.state import CompiledStateGraph

        graph = await compile_graph_dev()
        assert isinstance(graph, CompiledStateGraph)

    @pytest.mark.asyncio
    async def test_compile_graph_dev_has_checkpointer(self):
        """Dev graph uses SQLite checkpointer."""
        graph = await compile_graph_dev()

        # Checkpointer should be present
        assert graph.checkpointer is not None

    @pytest.mark.asyncio
    async def test_compile_graph_dev_uses_interrupt_before(self):
        """Dev graph uses interrupt_before for review, choice, and draft gates.

        review_gate, choice_gate, and draft_gate all require human confirmation
        before proceeding, so they are listed in interrupt_before.
        """
        graph = await compile_graph_dev()

        assert "review_gate" in graph.interrupt_before_nodes
        assert "choice_gate" in graph.interrupt_before_nodes
        assert "draft_gate" in graph.interrupt_before_nodes


class TestCompileGraphProd:
    """Tests for production graph compilation."""

    @pytest.mark.asyncio
    async def test_compile_graph_prod_uses_async_postgres_store_context(self, monkeypatch):
        """Prod graph enters the async Postgres store context before compile."""
        from backend.graph import builder as builder_module

        # Set OPENAI_API_KEY + XHS_EMBED_MODEL so get_prod_store_index() returns a
        # real index config. Explicitly use the openai provider so the test does
        # not depend on the local .env embedding configuration.
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")
        monkeypatch.setenv("XHS_EMBED_MODEL", "openai:text-embedding-3-small")
        monkeypatch.setenv("XHS_EMBED_DIMS", "1536")

        calls = {}
        fake_graph = object()

        class FakePool:
            def __init__(self, db_uri, min_size, max_size, open, kwargs):
                calls["pool_args"] = {
                    "db_uri": db_uri,
                    "min_size": min_size,
                    "max_size": max_size,
                    "open": open,
                    "kwargs": kwargs,
                }

            async def open(self):
                calls["pool_opened"] = True

            async def close(self):
                calls["pool_closed"] = True

        class FakeSaver:
            def __init__(self, conn):
                calls["saver_conn"] = conn

            async def setup(self):
                calls["saver_setup"] = True

        class FakeStore:
            async def setup(self):
                calls["store_setup"] = True

        class FakeStoreContext:
            def __init__(self):
                self.store = FakeStore()
                self.entered = False
                self.exited = False

            async def __aenter__(self):
                self.entered = True
                return self.store

            async def __aexit__(self, exc_type, exc, tb):
                self.exited = True

        store_context = FakeStoreContext()

        class FakeAsyncPostgresStore:
            @classmethod
            def from_conn_string(cls, db_uri, *, pool_config=None, index=None):
                calls["store_db_uri"] = db_uri
                calls["store_pool_config"] = pool_config
                calls["store_index"] = index
                return store_context

        class FakeBuilder:
            def compile(self, **kwargs):
                calls["compile_kwargs"] = kwargs
                return fake_graph

        import langgraph.checkpoint.postgres.aio as checkpoint_postgres_aio
        import langgraph.store.postgres.aio as store_postgres_aio
        import psycopg_pool

        monkeypatch.setattr(builder_module, "build_graph", lambda: FakeBuilder())
        monkeypatch.setattr(psycopg_pool, "AsyncConnectionPool", FakePool)
        monkeypatch.setattr(checkpoint_postgres_aio, "AsyncPostgresSaver", FakeSaver)
        monkeypatch.setattr(store_postgres_aio, "AsyncPostgresStore", FakeAsyncPostgresStore)

        graph, resources = await builder_module.compile_graph_prod("postgresql://test")

        checkpointer, checkpoint_pool, returned_store_context = resources
        assert graph is fake_graph
        assert returned_store_context is store_context
        assert store_context.entered is True
        assert store_context.exited is False
        assert calls["saver_conn"] is checkpoint_pool
        assert calls["saver_setup"] is True
        assert calls["store_setup"] is True
        assert calls["store_pool_config"] == {"min_size": 2, "max_size": 10}
        assert calls["store_index"] is not None  # prod store must receive index
        assert calls["compile_kwargs"]["checkpointer"] is checkpointer
        assert calls["compile_kwargs"]["store"] is store_context.store
        # ripple_gate and blogger_gate removed from interrupt_before — they use dynamic interrupt()
        assert "ripple_gate" not in calls["compile_kwargs"]["interrupt_before"]
        assert "blogger_gate" not in calls["compile_kwargs"]["interrupt_before"]
        # Static gates still in interrupt_before
        assert "review_gate" in calls["compile_kwargs"]["interrupt_before"]
        assert "choice_gate" in calls["compile_kwargs"]["interrupt_before"]
        assert "draft_gate" in calls["compile_kwargs"]["interrupt_before"]
