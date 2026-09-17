"""The edge table has to be the graph, and every router has to be accounted for.

``build_graph()`` installs its conditional edges from
:data:`~backend.graph.wiring.CONDITIONAL_EDGES`, which means the table can be
wrong in two directions that both fail silently in production:

* an answer listed in a path map that its router can never return is a *dead
  key* -- harmless tonight, and the reason a later reader believes the edge
  handles a case it does not;
* an answer a router can return with no map entry is the P1d ``KeyError`` --
  a crash on a branch nobody exercises.

So the table is compared against the routers' own ``Literal`` annotations in
both directions, and against the graph ``build_graph()`` actually produced.
Neither comparison derives its expectation from the other side: the annotations
are the routers' statement, the table is this module's, and the graph is what
langgraph ended up with.

Ordering is load-bearing twice. ``CONDITIONAL_EDGES`` is written in the order
``build_graph()`` used to install the edges, so ``branches`` keeps its original
order -- which is why ``test_the_table_keeps_the_branch_order`` is not
cosmetic. And an entry's ``answers`` tuple is the path map's key order.
"""

from __future__ import annotations

import inspect
from typing import Any, Literal, get_args, get_origin, get_type_hints

import pytest
from langgraph.graph import END

from backend.graph import routers as routers_module
from backend.graph import wiring as wiring_module
from backend.graph.builder import build_graph
from backend.graph.routers import OrchestratorDestination, orchestrator_router, should_plan
from backend.graph.wiring import (
    CONDITIONAL_EDGES,
    EDGES_BY_SOURCE,
    ROUTERS_WITHOUT_AN_EDGE,
    ConditionalEdge,
)


def _branches() -> dict[str, dict[str, dict[str, str]]]:
    """``{source: {router_name: {answer: destination}}}`` from the live graph."""
    return {
        source: {name: dict(branch.ends or {}) for name, branch in per.items()}
        for source, per in build_graph().branches.items()
    }


def _declared(fn: Any) -> set[str]:
    """Every value ``fn``'s annotation permits, empty when it is not a Literal."""
    annotation = get_type_hints(fn).get("return")
    if get_origin(annotation) is not Literal:
        return set()
    return {str(arg) for arg in get_args(annotation)}


def _router_shaped() -> dict[str, Any]:
    """Top-level functions defined *in* ``routers.py`` with a Literal return.

    ``get_origin(...) is Literal`` rather than ``get_args(...)`` being non-empty:
    ``_check_terminal`` is annotated ``Literal["__end__"] | None``, which has
    args but is a union, not a router's vocabulary.
    """
    return {
        name: fn
        for name, fn in inspect.getmembers(routers_module, inspect.isfunction)
        if getattr(fn, "__module__", "") == routers_module.__name__ and _declared(fn)
    }


class TestTheGraphIsTheTable:
    def test_every_branch_source_has_exactly_one_table_entry(self):
        branches = _branches()
        assert set(branches) == set(EDGES_BY_SOURCE)
        assert all(len(per) == 1 for per in branches.values()), branches

    def test_each_entry_reproduces_its_branch_exactly(self):
        """The table's path map, the router the graph keyed it under, and the
        order of the map's keys.

        The key order is asserted against ``edge.answers`` rather than against
        ``edge.path_map()``: the latter would be comparing the table to itself,
        since the graph's map *is* ``path_map()``'s output.
        """
        branches = _branches()
        for edge in CONDITIONAL_EDGES:
            per_source = branches[edge.source]
            assert list(per_source) == [edge.router_name], edge.source
            assert per_source[edge.router_name] == edge.path_map(), edge.source
            assert list(per_source[edge.router_name]) == list(edge.answers), edge.source

    def test_the_table_keeps_the_branch_order_the_graph_had(self):
        """The order the graph installed its branches in before S2, written out.

        A literal list earns its keep exactly once, and this is it: the slice's
        equivalence claim is "the rewrite reordered nothing", and the table is
        what the order now lives in, so it is pinned against a recorded
        expectation rather than against itself. Measured from
        ``builder.branches`` on the unwired graph, and independently
        corroborated by the golden snapshot taken before the rewrite.
        """
        assert [edge.source for edge in CONDITIONAL_EDGES] == [
            "orchestrator",
            "trend_scout",
            "content_strategist",
            "ripple_finalize",
            "ripple_gate",
            "copywriter",
            "draft_gate",
            "blogger_gate",
            "content_analyzer",
            "version_generator",
            "choice_gate",
            "shooting_planner",
            "visual_designer",
            "ripple_late_recheck",
            "review_gate",
            "evaluator_gate",
            "publish_gate",
            "analyst",
        ]

    def test_the_graph_installs_its_branches_in_the_tables_order(self):
        """Not redundant with the test above -- the two catch different defects.

        The literal list pins the *table's* order and cannot see how
        ``build_graph()`` walks it; this comparison pins the walk and cannot see
        the table being reordered (the graph would reorder with it, since the
        order now has exactly one home). One line of each is what makes the
        equivalence claim readable: the table is the recorded order, *and* the
        graph is the table.
        """
        assert list(_branches()) == [edge.source for edge in CONDITIONAL_EDGES]

    def test_the_sources_are_unique(self):
        sources = [edge.source for edge in CONDITIONAL_EDGES]
        assert len(set(sources)) == len(sources)

    def test_no_declared_answer_is_one_its_router_cannot_return(self):
        """A dead key: an answer in the map that the annotation does not permit."""
        functions = _router_shaped()
        invented = {
            name: sorted(set(ends) - _declared(functions[name]))
            for _source, per in _branches().items()
            for name, ends in per.items()
            if set(ends) - _declared(functions[name])
        }
        assert invented == {}

    def test_no_answer_its_router_can_return_is_missing_from_the_map(self):
        """The P1d direction. Before S2 the entry router had to be skipped here
        because its annotation was a plain ``str``; all eighteen are read now,
        which is why the exemption set in ``test_conditional_edge_wiring.py``
        is empty."""
        functions = _router_shaped()
        missing = {
            name: sorted(_declared(functions[name]) - set(ends))
            for _source, per in _branches().items()
            for name, ends in per.items()
            if _declared(functions[name]) - set(ends)
        }
        assert missing == {}

    def test_the_end_sentinel_is_an_identity(self):
        """``END`` has to be the string the routers say, or every ``__end__``
        in the table would be a dangling destination at once."""
        assert END == "__end__"
        for _source, per in _branches().items():
            for ends in per.values():
                if "__end__" in ends:
                    assert ends["__end__"] == END


class TestTheGraphIsBuiltFromTheTable:
    """Non-vacuity: if the table were decorative, doctoring it would do nothing."""

    def _install(self, monkeypatch, replacement: ConditionalEdge) -> None:
        monkeypatch.setattr(
            "backend.graph.builder.CONDITIONAL_EDGES",
            tuple(replacement if e.source == replacement.source else e for e in CONDITIONAL_EDGES),
        )

    def test_dropping_an_answer_from_the_table_drops_it_from_the_graph(self, monkeypatch):
        entry = EDGES_BY_SOURCE["orchestrator"]
        self._install(
            monkeypatch,
            ConditionalEdge(
                source=entry.source,
                router=entry.router,
                answers=tuple(a for a in entry.answers if a != "copywriter"),
            ),
        )
        assert "copywriter" not in _branches()["orchestrator"]["orchestrator_router"]

    def test_moving_a_redirect_in_the_table_moves_it_in_the_graph(self, monkeypatch):
        """The redirect field is what the graph resolves through, not a comment."""
        entry = EDGES_BY_SOURCE["publish_gate"]
        self._install(
            monkeypatch,
            ConditionalEdge(
                source=entry.source,
                router=entry.router,
                answers=entry.answers,
                redirects=(("publisher", "analyst"),),
            ),
        )
        assert _branches()["publish_gate"]["publish_gate_outcome"]["publisher"] == "analyst"


class TestTheOneRowThatIsNotAnIdentity:
    def test_the_declared_redirects_are_the_graphs_redirects(self):
        """Both sides of the single asymmetry, read from graph and from table.

        ``evaluator_gate``'s answer ``"publisher"`` lands on ``publish_gate``:
        the verdict is a quality statement and the human authorisation is the
        next hop. Every other row of every other map is the identity, which is
        why seventeen entries have no ``redirects`` at all.
        """
        declared = {
            (edge.source, answer, destination)
            for edge in CONDITIONAL_EDGES
            for answer, destination in edge.redirects
        }
        observed = {
            (source, answer, destination)
            for source, per in _branches().items()
            for ends in per.values()
            for answer, destination in ends.items()
            if answer != destination
        }
        assert declared == observed == {("evaluator_gate", "publisher", "publish_gate")}


class TestEveryRouterIsAccountedFor:
    def test_every_router_shaped_function_is_wired_or_registered(self):
        wired = {edge.router_name for edge in CONDITIONAL_EDGES}
        assert set(_router_shaped()) == wired | ROUTERS_WITHOUT_AN_EDGE

    def test_the_registered_names_are_not_also_wired(self):
        wired = {edge.router_name for edge in CONDITIONAL_EDGES}
        assert wired & ROUTERS_WITHOUT_AN_EDGE == set()

    def test_the_helper_router_is_called_by_another_router(self):
        """``should_optimize`` is a callee, not a branch."""
        source = inspect.getsource(routers_module)
        assert source.count("should_optimize(") == 2, "one definition, one call"

    def test_the_unused_router_is_called_by_nothing(self):
        """The reverse assertion on the exemption: if it is ever wired up, or
        given a caller, the exemption has to be deleted rather than left to rot.
        """
        source = inspect.getsource(routers_module)
        assert source.count("should_brief_or_optimize(") == 1, "its own definition only"
        assert "should_brief_or_optimize" not in {
            name for per in _branches().values() for name in per
        }


class TestMalformedEntriesAreRefused:
    """Five ways an entry looks reasonable and is not."""

    def _edge(self, **changes: Any) -> ConditionalEdge:
        base: dict[str, Any] = {
            "source": "trend_scout",
            "router": should_plan,
            "answers": ("content_strategist", "trend_scout", "__end__"),
        }
        return ConditionalEdge(**{**base, **changes})

    def test_an_edge_with_no_answers(self):
        with pytest.raises(ValueError, match="no answers"):
            self._edge(answers=())

    def test_a_repeated_answer(self):
        with pytest.raises(ValueError, match="repeated"):
            self._edge(answers=("trend_scout", "trend_scout"))

    def test_a_redirect_that_is_not_one_of_the_answers(self):
        with pytest.raises(ValueError, match="not one of its answers"):
            self._edge(redirects=(("copywriter", "copywriter"),))

    def test_a_redirect_that_moves_nothing(self):
        """An identity mapping declared as a redirect is a claim about an
        asymmetry while asserting none."""
        with pytest.raises(ValueError, match="redirects to itself"):
            self._edge(redirects=(("trend_scout", "trend_scout"),))

    def test_the_end_sentinel_is_not_a_source(self):
        with pytest.raises(ValueError, match="not a node"):
            self._edge(source=END)

    def test_two_edges_leaving_one_node(self):
        with pytest.raises(ValueError, match="two conditional edges"):
            wiring_module._by_source((self._edge(), self._edge()))


class TestTheEntrysVocabularyIsDeclared:
    """Fact 4 of the wiring table: the entry's destinations are declared rather
    than probed. S1 had to *call* the router to enumerate them, which is why
    that router was the one branch the wiring check had to skip; the annotation
    is what let the two-directional comparison cover all eighteen."""

    def test_the_entry_router_annotates_its_destinations(self):
        declared = sorted(_declared(orchestrator_router))
        assert declared == sorted(EDGES_BY_SOURCE["orchestrator"].answers)

    def test_the_annotation_is_a_named_type_not_an_inline_literal(self):
        """So the vocabulary is importable under a name rather than repeated at
        the one signature that happens to state it."""
        assert OrchestratorDestination == get_type_hints(orchestrator_router)["return"]

    def test_the_annotation_includes_the_brief_only_answer(self):
        """``copywriter`` is reachable only from brief mode's ``creating``
        phase -- and it is the value S1 registered as unresolved, because the
        path map had no key for it."""
        assert "copywriter" in EDGES_BY_SOURCE["orchestrator"].answers
