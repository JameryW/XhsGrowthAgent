"""The graph's conditional edges, declared once as data.

``build_graph()`` used to spell out eighteen ``add_conditional_edges`` calls,
each with its router and its hand-written path map. That is a plan -- the
workflow's decision structure -- expressed as control flow, which is why
``backend/graph/plan.py`` had to *simulate* the graph to say what a run would
do. This module is where those eighteen edges live now, so the graph and the
plan have one origin: ``build_graph()`` walks this table, the export walks the
graph, and the table is compared against the routers' own annotations in both
directions (``tests/unit/graph/test_conditional_edge_wiring.py``,
``tests/unit/graph/test_wiring_registry.py``).

Three facts the table rests on, measured on the unwired graph before it moved
here (2026-09-17, ruff 522 / mypy 208 / pytest 3438 baseline) rather than
assumed:

1. LangGraph registers a branch under the *router's* ``__name__``, and each of
   the eighteen sources has exactly one. Measured: no source has two, and no
   branch key differs from ``router.__name__``.
2. ``Branch.ends`` is the path map itself, so an answer and its destination are
   different things. Across all eighteen branches exactly one row is not an
   identity -- ``evaluator_gate``'s answer ``"publisher"`` lands on
   ``publish_gate``, because the verdict is a quality statement and the human
   authorisation is the hop after it. Every other branch is the identity, which
   is why :meth:`ConditionalEdge.redirects` is empty for seventeen of them.
3. ``langgraph.graph.END`` *is* the string ``"__end__"``, so the terminal
   answer needs no special case here: an identity mapping already resolves it
   to the sentinel. ``test_the_end_sentinel_is_an_identity`` pins that, because
   if it ever stopped holding, every ``__end__`` in this table would become a
   dangling destination at once.

``answers`` is declared, not read from the router's annotation. That looks like
duplication and is deliberate: the annotation and this table are two
independent statements of the same fact, and comparing them is the only way one
of them being wrong can be noticed. Deriving one from the other would make the
comparison a tautology -- a check that cannot fail. It is the same contract
``RETRY_POLICIES`` (``error_handling.py``) and ``TAKEOVER_HAZARDS``
(``takeover_safety.py``) have with the nodes they describe.

What this module is not: it does not decide anything. The routers still read
state and return an answer; nothing here inspects state, and no edge is chosen
at runtime by a table lookup.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any, Final, cast

from langgraph.graph import END

from backend.graph.routers import (
    blogger_gate_router,
    choice_outcome,
    content_analyzer_router,
    content_strategist_router,
    copywriter_router,
    draft_gate_router,
    evaluator_outcome,
    orchestrator_router,
    publish_gate_outcome,
    review_outcome,
    ripple_finalize_router,
    ripple_gate_router,
    ripple_late_recheck_router,
    shooting_planner_router,
    should_continue,
    should_plan,
    should_present_choice,
    visual_designer_router,
)
from backend.state.schema import XHSGrowthState

__all__ = [
    "CONDITIONAL_EDGES",
    "EDGES_BY_SOURCE",
    "ROUTERS_WITHOUT_AN_EDGE",
    "ConditionalEdge",
]

Router = Callable[[XHSGrowthState], str]


@dataclass(frozen=True, slots=True)
class ConditionalEdge:
    """One source node's conditional edge.

    ``router`` is the function that answers; ``answers`` is every value it is
    allowed to give, in the order the path map should list them; ``redirects``
    names the answers whose *destination* is not the answer itself.

    The constructor refuses the three ways an entry can be malformed while
    still looking reasonable: an empty answer list, a repeated answer, and a
    redirect that is not one of the answers -- or that points at the answer it
    started from, which would be a claim about an asymmetry while asserting
    none.
    """

    source: str
    router: Router
    answers: tuple[str, ...]
    redirects: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not self.source or self.source == END:
            raise ValueError(f"{self.source!r} is not a node a conditional edge can leave")
        if not self.answers:
            raise ValueError(f"{self.source}: an edge with no answers is not an edge")
        repeated = sorted({answer for answer in self.answers if self.answers.count(answer) > 1})
        if repeated:
            raise ValueError(f"{self.source}: repeated answers {repeated}")
        for answer, destination in self.redirects:
            if answer not in self.answers:
                raise ValueError(f"{self.source}: redirects {answer!r}, not one of its answers")
            if destination == answer:
                raise ValueError(
                    f"{self.source}: {answer!r} redirects to itself -- an identity mapping "
                    f"is not a redirect"
                )

    @property
    def router_name(self) -> str:
        """The name ``build_graph()`` registers this branch under."""
        return str(cast("Any", self.router).__name__)

    def path_map(self) -> dict[Hashable, str]:
        """The map langgraph resolves this router's answer through.

        ``Hashable`` rather than ``str`` because that is how
        ``add_conditional_edges`` declares the parameter; the keys here are
        node names, so every key this returns is a string.
        """
        redirects = dict(self.redirects)
        return {answer: redirects.get(answer, answer) for answer in self.answers}


#: Every conditional edge ``build_graph()`` installs, in the order the graph
#: used to install them -- so building from this table leaves ``branches`` in
#: the same order it was in before, and the rewrite's diff is exactly the one
#: deliberate change recorded in ``orchestrator``'s entry.
CONDITIONAL_EDGES: Final[tuple[ConditionalEdge, ...]] = (
    ConditionalEdge(
        source="orchestrator",
        router=orchestrator_router,
        # S2: `copywriter` is new here. The router has always been able to
        # answer it -- brief mode's table maps `phase=creating` to it, and
        # `WorkflowPhase.CREATING` is not terminal, so the branch is reachable
        # -- while this map had no such key, which is the P1d failure shape
        # (an answer langgraph cannot resolve: `KeyError`, on a resume path).
        # S1 registered it as `UNRESOLVED_ROUTER_VALUES` and left the execution
        # path alone; adding the key is what lets this router carry an honest
        # ``Literal`` (``OrchestratorDestination``, routers.py), and the plan
        # registry now classifies the hop: trend mode can never take it, brief
        # mode can.
        answers=(
            "trend_scout",
            "brief_analyzer",
            "content_strategist",
            "copywriter",
            "analyst",
            "__end__",
        ),
    ),
    # ── 侦察后判断是否有可操作趋势 ──
    ConditionalEdge(
        source="trend_scout",
        router=should_plan,
        answers=("content_strategist", "trend_scout", "__end__"),
    ),
    # ── 内容创作流水线 ──
    # content_strategist → [ripple_finalize | ripple_gate | __end__] based on
    # Ripple mode. Background mode (ripple_pending): skip ripple_gate, go to
    # ripple_finalize which reads the store-written background result. Blocking
    # mode: ripple_gate.
    #
    # P1d: `__end__` was missing from this map while `content_strategist_router`
    # returned it (its terminal guard, added so ripple_gate cannot swallow an
    # error by auto-accepting). LangGraph resolves a router's value through this
    # map, so the router's documented terminal branch raised `KeyError:
    # '__end__'` instead of ending the workflow — every content_strategist
    # failure crashed the graph. Found when P1d let that node fail for the first
    # time; the four sibling branches below all had the entry.
    ConditionalEdge(
        source="content_strategist",
        router=content_strategist_router,
        answers=("ripple_finalize", "ripple_gate", "__end__"),
    ),
    # ripple_finalize → [copywriter | content_strategist | trend_scout] (user decision)
    ConditionalEdge(
        source="ripple_finalize",
        router=ripple_finalize_router,
        answers=("copywriter", "content_strategist", "brief_analyzer", "trend_scout", "__end__"),
    ),
    # ripple_gate → [copywriter | content_strategist | trend_scout] (user decision)
    ConditionalEdge(
        source="ripple_gate",
        router=ripple_gate_router,
        answers=("copywriter", "content_strategist", "brief_analyzer", "trend_scout", "__end__"),
    ),
    # ── 发布前优化流程 ──
    # copywriter → [choice_gate | draft_gate | __end__]
    # Multi-style blogger variants pause at choice_gate for style selection.
    ConditionalEdge(
        source="copywriter",
        router=copywriter_router,
        answers=("choice_gate", "draft_gate", "__end__"),
    ),
    # draft_gate → [viral_matcher | shooting_planner]
    # (from copywriter → viral_matcher; from blogger_gate → shooting_planner)
    ConditionalEdge(
        source="draft_gate",
        router=draft_gate_router,
        answers=("viral_matcher", "shooting_planner"),
    ),
    # blogger_gate → [copywriter | draft_gate | __end__]
    # Brief mode and trend mode with selected blogger notes: copywriter.
    # Trend mode without selected blogger notes: draft_gate.
    # Terminal: __end__
    ConditionalEdge(
        source="blogger_gate",
        router=blogger_gate_router,
        answers=("copywriter", "draft_gate", "__end__"),
    ),
    # content_analyzer → [choice_gate | version_generator | __end__]
    # If copywriter generated style variants → choice_gate (style selection)
    # Otherwise → version_generator (A/B/C generation)
    ConditionalEdge(
        source="content_analyzer",
        router=content_analyzer_router,
        answers=("choice_gate", "version_generator", "__end__"),
    ),
    # version_generator → [choice_gate | visual_designer | __end__]
    # (conditional — only enter choice_gate if multiple versions)
    ConditionalEdge(
        source="version_generator",
        router=should_present_choice,
        answers=("choice_gate", "visual_designer", "__end__"),
    ),
    # choice_gate → [version_generator | visual_designer]
    # Style selection (first gate) → version_generator for A/B/C
    # Version selection (second gate) → visual_designer
    ConditionalEdge(
        source="choice_gate",
        router=choice_outcome,
        answers=("version_generator", "visual_designer"),
    ),
    # ── 商单 Brief 模式流程 ──
    # shooting_planner → [content_analyzer | visual_designer | __end__]
    ConditionalEdge(
        source="shooting_planner",
        router=shooting_planner_router,
        answers=("content_analyzer", "visual_designer", "__end__"),
    ),
    # visual_designer → [ripple_late_recheck | review_gate | __end__]
    # Background mode with a still-pending Ripple result → ripple_late_recheck
    # (bounded-polls the store for the late-arriving prediction, may interrupt).
    # Blocking mode or result already consumed → review_gate directly.
    # review_gate uses dynamic interrupt() (like ripple_gate): low-risk auto-pass
    # happens inside the node, so the router never bypasses it.
    ConditionalEdge(
        source="visual_designer",
        router=visual_designer_router,
        answers=("ripple_late_recheck", "review_gate", "__end__"),
    ),
    # ripple_late_recheck → [review_gate | content_strategist | brief_analyzer |
    # trend_scout | __end__] accept (or poll-timeout fail-open) → review_gate;
    # reangle → strategist/brief_analyzer; retopic → trend_scout. Mirrors
    # ripple_finalize_router but accept lands at review_gate (after visual).
    ConditionalEdge(
        source="ripple_late_recheck",
        router=ripple_late_recheck_router,
        answers=("review_gate", "content_strategist", "brief_analyzer", "trend_scout", "__end__"),
    ),
    # ── 人工审核路由 ──
    # approved → evaluator_gate (AI 质量评估关卡) → publisher | revise_content
    ConditionalEdge(
        source="review_gate",
        router=review_outcome,
        answers=("evaluator_gate", "revise_content", "__end__"),
    ),
    # ── 创作质量评估路由 (RQGM agent-as-a-judge) ──
    # P0-W5: __end__ is the fail-closed human channel — the evaluator node has
    # already parked the workflow in the existing paused status when it decides
    # a human must look (degraded evaluation or compliance/policy rejection).
    ConditionalEdge(
        source="evaluator_gate",
        router=evaluator_outcome,
        answers=("publisher", "revise_content", "__end__"),
        # The verdict is still spelled "publisher" — it means "this content MAY
        # be published", which is a quality statement. The human authorisation
        # is the next hop, not this one. This is the graph's only redirect.
        redirects=(("publisher", "publish_gate"),),
    ),
    # ── 发布确认 → 发布 或 结束（P2a-S4b）──
    ConditionalEdge(
        source="publish_gate",
        router=publish_gate_outcome,
        answers=("publisher", "__end__"),
    ),
    # ── 分析后决定是否继续 ──
    ConditionalEdge(
        source="analyst",
        router=should_continue,
        answers=("orchestrator", "__end__"),
    ),
)


def _by_source(edges: tuple[ConditionalEdge, ...]) -> dict[str, ConditionalEdge]:
    """Index the table, refusing two edges that leave the same node.

    A second conditional edge on one source is not something langgraph forbids,
    but it *is* something this table cannot represent honestly: the export reads
    one entry per source, so the second would be silently invisible.
    """
    index: dict[str, ConditionalEdge] = {}
    for edge in edges:
        if edge.source in index:
            raise ValueError(
                f"two conditional edges leave {edge.source!r} "
                f"({index[edge.source].router_name} and {edge.router_name})"
            )
        index[edge.source] = edge
    return index


#: What ``build_graph()`` walks. Keys are source nodes.
EDGES_BY_SOURCE: Final[dict[str, ConditionalEdge]] = _by_source(CONDITIONAL_EDGES)

#: Router-shaped functions in ``routers.py`` that no edge installs -- anything
#: with a ``Literal`` return annotation that is not one of the eighteen above.
#: Two of them, and the difference between the two is what the tests pin:
#:
#: ``should_optimize``
#:     a helper. ``shooting_planner_router`` delegates to it, so it is a
#:     branch's callee rather than a branch.
#: ``should_brief_or_optimize``
#:     unreachable. It answers ``shooting_planner`` / ``__end__`` for the hop
#:     after ``viral_matcher``, but the graph reaches ``blogger_scout`` from
#:     there with a plain edge and has done since before this table existed, so
#:     nothing calls it at all.
#:
#: Registered rather than deleted, because removing public code is a different
#: decision from making the edge set declarable -- and registered rather than
#: ignored, so that wiring either of them up later has to come here and delete
#: the exemption (``tests/unit/graph/test_wiring_registry.py``).
ROUTERS_WITHOUT_AN_EDGE: Final[frozenset[str]] = frozenset(
    {"should_optimize", "should_brief_or_optimize"}
)
