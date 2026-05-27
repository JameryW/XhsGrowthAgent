"""Graph topology tests — verify node/edge structure."""

from backend.graph.builder import build_graph


def test_graph_builds():
    """图可以正常构建"""
    graph = build_graph()
    assert graph is not None


def test_graph_has_all_nodes():
    """图包含所有必需节点"""
    graph = build_graph()
    expected_nodes = {
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
    }
    # StateGraph.nodes 包含所有添加的节点
    assert expected_nodes.issubset(set(graph.nodes.keys()))


def test_graph_compiles_dev():
    """开发模式图可以正常编译"""
    from backend.graph.builder import compile_graph_dev

    graph = compile_graph_dev()
    assert graph is not None


def test_graph_has_interrupt():
    """编译后的图在 review_gate 前有中断"""
    from backend.graph.builder import compile_graph_dev

    graph = compile_graph_dev()
    # interrupt_before 应包含 review_gate
    assert "review_gate" in graph.interrupt_before_nodes
