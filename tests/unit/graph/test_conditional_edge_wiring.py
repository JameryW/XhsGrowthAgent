"""Every conditional edge must resolve every value its router can return.

P1d found this the expensive way. ``content_strategist_router`` returns
``"__end__"`` from its terminal guard — deliberately, so that ``ripple_gate``
cannot swallow an error by auto-accepting — while the path map in
``builder.py`` listed only ``ripple_finalize`` and ``ripple_gate``. LangGraph
resolves a router's value by looking it up in that map, so the workflow died
with ``KeyError: '__end__'`` instead of ending: a crash on the *failure* path,
where no test was looking, in a branch whose four siblings all had the entry.

The two halves of that contract are both introspectable — a router's ``Literal``
return annotation enumerates every value it can produce, and ``builder.branches``
exposes the map it has to be found in — so they are compared here rather than
left to review.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Literal, get_args, get_type_hints

import pytest
from langgraph.graph import END

from backend.graph.builder import build_graph

#: Routers whose return annotation is a plain ``str``, so this check cannot read
#: the set of values they may produce. Kept as an explicit list rather than a
#: silent skip: adding another one has to be a decision, and the exemption is
#: only honest while it is small enough to read.
_NON_LITERAL_ROUTERS = frozenset({"orchestrator_router"})


def _branches() -> list[tuple[str, Callable[..., Any], tuple[str, ...]]]:
    """``(source, router_fn, mapped_targets)`` for every conditional edge."""
    builder = build_graph()
    found: list[tuple[str, Callable[..., Any], tuple[str, ...]]] = []
    for source, per_source in builder.branches.items():
        for branch in per_source.values():
            # ``branch.path`` is langgraph's RunnableCallable wrapper.
            router = getattr(branch.path, "func", branch.path)
            found.append((source, router, tuple(branch.ends or ())))
    return found


def _declared_targets(router: Callable[..., Any]) -> set[str]:
    """Every value ``router`` can return, from its annotation."""
    annotation = get_type_hints(router).get("return")
    declared = get_args(annotation)
    if not declared:
        raise AssertionError(
            f"{router.__name__} does not annotate its return as a Literal, so its "
            f"possible destinations cannot be read"
        )
    return {str(item) for item in declared}


def _unmapped(
    branches: Iterable[tuple[str, Callable[..., Any], tuple[str, ...]]],
) -> dict[str, list[str]]:
    """``{source: [targets the router can return but the map does not resolve]}``.

    Routers in ``_NON_LITERAL_ROUTERS`` are passed over rather than raising,
    because their annotation cannot be read at all — and that exemption is
    itself asserted, so it cannot grow unnoticed.
    """
    problems: dict[str, list[str]] = {}
    for source, router, mapped in branches:
        if router.__name__ in _NON_LITERAL_ROUTERS:
            continue
        missing = sorted(_declared_targets(router) - set(mapped))
        if missing:
            problems[source] = missing
    return problems


class TestEveryRouterValueIsResolvable:
    def test_no_router_returns_a_value_its_path_map_cannot_resolve(self):
        assert _unmapped(_branches()) == {}

    def test_the_check_notices_a_missing_entry(self):
        """Non-vacuous: the historical defect, reproduced.

        Without this, the test above would pass just as happily if it were
        reading the wrong attribute and comparing nothing.
        """

        def content_strategist_router(state: Any) -> Literal["a", "b", "__end__"]:
            return "a"

        problems = _unmapped([("content_strategist", content_strategist_router, ("a", "b"))])
        assert problems == {"content_strategist": ["__end__"]}

    def test_a_router_with_an_unreadable_annotation_is_rejected(self):
        """A check that silently skips what it cannot read reports "all green"
        on a tree it never inspected."""

        def opaque_router(state: Any) -> Any:
            return "__end__"

        with pytest.raises(AssertionError, match="Literal"):
            _declared_targets(opaque_router)

    def test_the_routers_this_check_cannot_read_are_a_named_list(self):
        unreadable = set()
        for _source, router, _mapped in _branches():
            try:
                _declared_targets(router)
            except AssertionError:
                unreadable.add(router.__name__)
        assert unreadable == set(_NON_LITERAL_ROUTERS)


class TestEveryPathMapTargetIsReal:
    def test_each_target_is_a_registered_node_or_the_end_sentinel(self):
        """The other direction: a typo in the *map* is just as fatal, and just
        as invisible until that branch is taken."""
        builder = build_graph()
        known = set(builder.nodes) | {END}
        unknown: dict[str, list[str]] = {}
        for source, per_source in builder.branches.items():
            for branch in per_source.values():
                bad = sorted(set(branch.ends or ()) - known)
                if bad:
                    unknown[source] = bad
        assert unknown == {}
