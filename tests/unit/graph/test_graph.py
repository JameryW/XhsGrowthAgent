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


def test_graph_uses_interrupt_before():
    """编译后的图使用 interrupt_before 在 review_gate 处中断。

    choice_gate 不在 interrupt_before — 使用条件边路由，仅在多版本时进入，
    节点内部动态调用 interrupt()。
    """
    from backend.graph.builder import compile_graph_dev

    graph = compile_graph_dev()
    # interrupt_before 只包含 review_gate
    assert "review_gate" in graph.interrupt_before_nodes
    assert "choice_gate" not in graph.interrupt_before_nodes
