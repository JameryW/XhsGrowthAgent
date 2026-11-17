"""Mode-specific JIT graph builder tests."""

from __future__ import annotations

from backend.graph.builder import build_graph, build_jit_graph
from backend.graph.plan import export_plan
from backend.state.enums import WorkflowMode


def test_full_graph_is_unchanged() -> None:
    graph = build_graph()

    assert len(graph.nodes) == 24


def test_trend_jit_graph_uses_the_trend_plan_nodes() -> None:
    plan = export_plan(WorkflowMode.TREND)
    graph = build_jit_graph(WorkflowMode.TREND)

    assert set(graph.nodes) == set(plan.nodes)
    assert "brief_analyzer" not in graph.nodes
    assert "brief_gate" not in graph.nodes


def test_brief_jit_graph_uses_the_brief_plan_nodes() -> None:
    plan = export_plan(WorkflowMode.BRIEF)
    graph = build_graph(WorkflowMode.BRIEF)

    assert set(graph.nodes) == set(plan.nodes)


def test_mode_specific_graphs_compile() -> None:
    for mode in (WorkflowMode.TREND, WorkflowMode.BRIEF):
        graph = build_graph(mode).compile()
        assert graph is not None
