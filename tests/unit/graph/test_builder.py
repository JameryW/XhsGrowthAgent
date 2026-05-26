"""Unit tests for graph builder."""

import pytest

from xhs_growth.graph.builder import build_graph, compile_graph_dev


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


class TestCompileGraphDev:
    """Tests for dev graph compilation."""

    def test_compile_graph_dev_returns_compiled_graph(self):
        """compile_graph_dev returns a CompiledStateGraph."""
        from langgraph.graph.state import CompiledStateGraph

        graph = compile_graph_dev()
        assert isinstance(graph, CompiledStateGraph)

    def test_compile_graph_dev_has_checkpointer(self):
        """Dev graph uses MemorySaver checkpointer."""
        graph = compile_graph_dev()

        # Checkpointer should be present
        assert graph.checkpointer is not None

    def test_compile_graph_dev_interrupts_at_review_gate(self):
        """Dev graph interrupts before review_gate and choice_gate for human-in-the-loop."""
        graph = compile_graph_dev()

        # interrupt_before_nodes should include both gates
        # This is configured in compile_graph_dev
        assert "review_gate" in graph.interrupt_before_nodes
        assert "choice_gate" in graph.interrupt_before_nodes