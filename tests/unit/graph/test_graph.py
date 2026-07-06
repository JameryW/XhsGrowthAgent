"""Graph topology tests — verify node/edge structure."""

import pytest

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


@pytest.mark.asyncio
async def test_graph_compiles_dev():
    """开发模式图可以正常编译"""
    from backend.graph.builder import dev_graph

    async with dev_graph() as graph:
        assert graph is not None


@pytest.mark.asyncio
async def test_graph_uses_interrupt_before():
    """编译后的图使用 interrupt_before 在 choice_gate, draft_gate 处中断。

    review_gate 改用动态 interrupt()（同 ripple_gate），低风险自动放行在节点内
    执行，故不在 interrupt_before。choice_gate / draft_gate 仍需人工确认。
    """
    from backend.graph.builder import dev_graph

    async with dev_graph() as graph:
        assert "review_gate" not in graph.interrupt_before_nodes
        assert "choice_gate" in graph.interrupt_before_nodes
        assert "draft_gate" in graph.interrupt_before_nodes
