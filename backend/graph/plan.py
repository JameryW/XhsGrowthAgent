"""What a run plans to do -- exported from the graph, declared per mode.

The dynamic-planning ticket (09-11-p2-dynamic-planning) starts from one
observation: the workflow already has a plan, but nothing can *state* it. The
plan is spread over 18 conditional edges, 18 routers and eleven places that
read ``workflow_mode``, and no single object answers "what is this run going to
do". This module is the first half of that object -- a read-only export of the
graph's topology, plus one exhaustive registry saying which part of it belongs
to which :class:`~backend.state.enums.WorkflowMode`.

Three facts the export is built on, all measured (2026-09-16, ruff 520 /
mypy 207 / pytest 3414 baseline) rather than assumed:

1. ``StateGraph.branches`` maps a *source node* to its routers, and
   ``Branch.ends`` is the *path map itself* -- ``{router answer: node}``.
   Reading it as a sequence yields the keys, i.e. the router's vocabulary, not
   the graph's destinations. Across all 18 branches exactly one row differs:
   ``evaluator_gate``'s answer ``"publisher"`` resolves to the node
   ``publish_gate``. An export that read the keys would publish a hop the graph
   cannot take (``evaluator_gate -> publisher``, skipping the human
   authorisation gate) and would leave ``publish_gate`` with no in-plan
   predecessor at all, i.e. out of the plan entirely.
   ``tests/unit/graph/test_conditional_edge_wiring.py`` reads the keys, which is
   right for what it checks -- a router's answer has to be a key -- but that
   leaves the *destination* direction unchecked, and this module is where it
   starts being checked.

2. The topology is mode-blind. Seeded at ``orchestrator`` (the real seed,
   ``builder.add_edge(START, "orchestrator")``) all 24 nodes are reachable.
   Seeded at either mode's *entry* it is 22, the same 22 -- ``orchestrator``
   and ``analyst`` drop out because the only hop back to the root comes from
   ``analyst`` itself. The two sets are equal, so mode membership cannot be
   *derived* from the graph: it has to be declared. That is what
   ``PLAN_TEMPLATES`` is, and what keeps it small is that the two modes differ
   by a handful of *hops*, not by two separate graphs.

3. Where the modes differ, they differ inside six routers, and all six already
   have behaviour tests (``tests/unit/graph/test_routers.py`` for the ripple
   trio, ``tests/unit/test_brief_mode_status.py`` for the two gates). Each
   :class:`ExcludedHop` names the router that decides it, and the check asserts
   that named router really is the one registered at that source -- so an
   exclusion cannot be attributed to a router that has nothing to do with it.

4. The entry router's destinations are readable now. ``orchestrator_router``
   returned a plain ``str`` through S1 -- the only router whose vocabulary could
   not be read at all, and it is the one every run enters through -- so this
   module declared that vocabulary rather than reading it, and corroborated the
   declaration by *calling* the router. S2 gave the router a ``Literal`` (its
   path map needed the value that annotation then exposed: brief mode's
   ``phase=creating`` answers ``"copywriter"`` and there was no such key, the
   P1d failure shape, latent only because nothing observed reached
   ``orchestrator`` at that phase). The declaration here stays anyway: it is per
   *mode*, and the annotation is not -- the union of these two tables is what
   the wiring table has to equal, which is what
   ``entry_vocabulary_disagrees_with_the_edges`` checks.

What this module deliberately does *not* do: nothing in the execution path
reads it. No router imports it and no edge is decided by a plan at run time.
What S2 changed is one step up from that: the edges are now installed from
``backend/graph/wiring.py``'s declaration instead of being hand-written into
``build_graph()``, so the graph this module exports and the modes it declares
have a single origin. This module still only observes the result.

The check is bidirectional and exhaustive in the same way ``RETRY_POLICIES``
(``backend/graph/error_handling.py``) and ``TAKEOVER_HAZARDS``
(``backend/graph/takeover_safety.py``) are exhaustive: forward, every declared
name has to exist in the graph; backward, every node and hop the graph has has
to be reachable in at least one mode. The backward direction is the one that
matters -- an undeclared region of the graph is exactly the condition this
ticket exists to end.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from langgraph.graph import END

from backend.graph.builder import build_graph
from backend.graph.routers import orchestrator_router
from backend.graph.wiring import EDGES_BY_SOURCE
from backend.state.enums import WorkflowMode, WorkflowPhase
from backend.state.modes import WORKFLOW_MODES
from backend.state.schema import XHSGrowthState

__all__ = [
    "PLAN_TEMPLATES",
    "ExcludedHop",
    "ModeTemplate",
    "Plan",
    "PlanExportError",
    "PlanStep",
    "export_plan",
    "get_plan_template",
    "graph_nodes",
    "mode_registry_complaints",
    "orchestrator_destinations",
    "plan_registry_complaints",
    "reachable_nodes",
]

#: The node every run starts from. Named here because it is the seed of every
#: reachability answer this module gives, and it is not a mode's entry.
_ROOT = "orchestrator"


class PlanExportError(RuntimeError):
    """A template names something ``build_graph()`` does not have.

    Raised instead of returning a plan with the unnameable part quietly
    dropped: a plan that silently loses the hop it could not resolve is the
    same class of artifact as a router returning a value its path map lacks.
    """


@dataclass(frozen=True, slots=True)
class ExcludedHop:
    """A hop the graph has but one mode cannot take.

    ``decided_by`` names the branch the graph registers at ``source`` -- the
    router that decides this hop. The field is compared against the graph, not
    taken on trust, so an exclusion cannot be credited to a router that has
    nothing to do with it.
    """

    source: str
    target: str
    decided_by: str


@dataclass(frozen=True, slots=True)
class ModeTemplate:
    """What one mode declares about the graph.

    ``destinations`` is the whole vocabulary ``orchestrator_router`` answers
    with *in this mode*. It stays declared after S2 made that router's
    annotation readable, because the two are different questions: the
    annotation enumerates the entry's vocabulary mode-blind, while a mode's
    destinations say which of those answers the mode can actually produce. The
    union over the modes has to equal the entry edge's answers, and that is
    checked rather than assumed -- see
    ``entry_vocabulary_disagrees_with_the_edges``.
    """

    entry: str
    destinations: frozenset[str]
    excludes: tuple[ExcludedHop, ...]


#: Per-mode declaration. Exhaustive over ``WorkflowMode`` members and, in
#: union, over every node ``build_graph()`` registers -- both directions are
#: asserted in ``tests/unit/graph/test_plan_registry.py``.
PLAN_TEMPLATES: Final[dict[WorkflowMode, ModeTemplate]] = {
    WorkflowMode.TREND: ModeTemplate(
        entry="trend_scout",
        # `orchestrator_router`'s trend table covers SCOUTING / PLANNING /
        # ANALYZING / the three terminal phases, and its fallback is
        # "trend_scout", so BRIEFING lands on trend_scout and never on
        # brief_analyzer.
        destinations=frozenset({"trend_scout", "content_strategist", "analyst", END}),
        excludes=(
            ExcludedHop("orchestrator", "brief_analyzer", "orchestrator_router"),
            # S2: the entry's ``copywriter`` answer is brief-only. Trend mode's
            # table has no CREATING key at all -- ``creating`` falls through to
            # the "trend_scout" default -- so ``copywriter`` stays in this plan
            # through ``copywriter_router``'s own answers while this hop from
            # the entry cannot be taken. Newly visible, and only newly
            # *statable*: the hop did not exist until the entry's path map
            # gained an entry for ``"copywriter"``.
            ExcludedHop("orchestrator", "copywriter", "orchestrator_router"),
            # The ripple trio: `reangle` is the only branch that reads the mode,
            # and trend resolves it to content_strategist. Those are the only
            # ingresses into brief_analyzer, so in trend mode brief_analyzer --
            # and with it brief_gate, its single successor -- is unreachable:
            # 22 of 24 nodes.
            ExcludedHop("ripple_finalize", "brief_analyzer", "ripple_finalize_router"),
            ExcludedHop("ripple_gate", "brief_analyzer", "ripple_gate_router"),
            ExcludedHop("ripple_late_recheck", "brief_analyzer", "ripple_late_recheck_router"),
        ),
    ),
    WorkflowMode.BRIEF: ModeTemplate(
        entry="brief_analyzer",
        # The brief table adds CREATING (-> copywriter) and BRIEFING (-> the
        # brief entry), and its fallback is "brief_analyzer", so trend_scout is
        # never an answer here.
        destinations=frozenset(
            {"brief_analyzer", "content_strategist", "copywriter", "analyst", END}
        ),
        excludes=(
            ExcludedHop("orchestrator", "trend_scout", "orchestrator_router"),
            # blogger_gate_router: brief returns copywriter unconditionally, so
            # draft_gate is not an answer here -- though it stays reachable
            # through copywriter -> draft_gate, which is why the *hop* is
            # excluded and not the node.
            ExcludedHop("blogger_gate", "draft_gate", "blogger_gate_router"),
            # draft_gate_router: brief short-circuits to shooting_planner. The
            # viral_matcher node stays reachable via brief_gate -> viral_matcher.
            ExcludedHop("draft_gate", "viral_matcher", "draft_gate_router"),
            # Same three routers as the trend column, mirrored: reangle in brief
            # mode re-analyzes the brief instead of re-planning the content.
            ExcludedHop("ripple_finalize", "content_strategist", "ripple_finalize_router"),
            ExcludedHop("ripple_gate", "content_strategist", "ripple_gate_router"),
            ExcludedHop("ripple_late_recheck", "content_strategist", "ripple_late_recheck_router"),
        ),
    ),
}

#: Closed in S2, kept as a note rather than a table. S1 registered
#: ``(BRIEF, "orchestrator_router", "copywriter")`` here because the entry's
#: path map had no key for it and adding one would have changed behaviour. S2
#: added the key (the annotation below S1's note made that the honest thing to
#: do, and it is what closes the P1d-shaped hole), so the entry's vocabulary and
#: the map's now agree in both directions, and there is nothing left to exempt.
#:
#: The whole *mechanism* is gone with it, and that is deliberate: with no
#: exemptions, "a router answer the map cannot resolve" is a complaint rather
#: than a complaint-minus-list, and the invariant that made the exemption
#: unnecessary -- the entry edge's answers are exactly the union of the modes'
#: declared destinations -- has its own check below. An always-empty exemption
#: table is the same artifact this ticket keeps finding: a note pinned over a
#: hole that is no longer there. The idiom itself is still in use next door, on
#: ``wiring.ROUTERS_WITHOUT_AN_EDGE``.


@dataclass(frozen=True, slots=True)
class PlanStep:
    """One node in a plan, with the hops into and out of it.

    ``preceded_by`` is restricted to nodes *of this plan* -- a mode that cuts an
    ingress into an interior node leaves that node still reachable by another
    route, so its list of predecessors is shorter than the graph's. A step with
    no ``preceded_by`` other than the root is a place the plan enters from
    outside its own node set.

    ``followed_by`` is restricted the same way, but there it follows from what a
    plan is and needs no filter: see :func:`export_plan`. ``"__end__"`` is kept
    wherever the graph lets the step terminate; the ``"__start__"`` sentinel is
    not, because it is never a step.
    """

    node: str
    preceded_by: tuple[str, ...]
    followed_by: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Plan:
    """The nodes one mode's run may visit, and the hops between them."""

    mode: WorkflowMode
    entry: str
    steps: tuple[PlanStep, ...]

    def step(self, node: str) -> PlanStep:
        for step in self.steps:
            if step.node == node:
                return step
        raise KeyError(node)

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(step.node for step in self.steps)


@dataclass(frozen=True, slots=True)
class _Topology:
    """Everything this module reads out of ``build_graph()``, read once."""

    nodes: frozenset[str]
    hops: frozenset[tuple[str, str]]
    routers: dict[str, str]


def _topology() -> _Topology:
    builder = build_graph()
    hops: set[tuple[str, str]] = set(builder.edges)
    routers: dict[str, str] = {}
    for source, per_source in builder.branches.items():
        # ``per_source`` is keyed by the name langgraph registers the branch
        # under, which is the router's ``__name__``. Read that rather than
        # ``branch.path.__name__``: the latter is ``Any | Runnable``, and the
        # graph's own name is the thing ``decided_by`` should be compared to
        # anyway.
        routers[source] = "|".join(sorted(per_source))
        for branch in per_source.values():
            # ``Branch.ends`` is the path map, not a list of targets: take the
            # *values*. See fact 1 in the module docstring -- this is the line
            # the evaluator_gate/publish_gate asymmetry depends on.
            hops.update((source, destination) for destination in (branch.ends or {}).values())
    return _Topology(frozenset(builder.nodes), frozenset(hops), routers)


def _reachable_from(
    nodes: frozenset[str], hops: frozenset[tuple[str, str]], seed: str
) -> frozenset[str]:
    seen = {seed} & nodes
    frontier = list(seen)
    while frontier:
        source = frontier.pop()
        for src, dst in hops:
            if src == source and dst in nodes and dst not in seen:
                seen.add(dst)
                frontier.append(dst)
    return frozenset(seen)


def _mode_edges(template: ModeTemplate, topology: _Topology) -> frozenset[tuple[str, str]]:
    """The graph's hops minus the ones this mode cannot take."""
    excluded = {(hop.source, hop.target) for hop in template.excludes}
    return frozenset(hop for hop in topology.hops if hop not in excluded)


def _plan_nodes(template: ModeTemplate, topology: _Topology) -> frozenset[str]:
    return _reachable_from(topology.nodes, _mode_edges(template, topology), _ROOT)


def graph_nodes() -> frozenset[str]:
    """Every node ``build_graph()`` registers. Read-only."""
    return _topology().nodes


def reachable_nodes(seed: str) -> frozenset[str]:
    """Nodes reachable from ``seed`` over every hop, mode-agnostic.

    This keeps fact 2 of the module docstring checkable rather than merely
    asserted: seeded at ``_ROOT`` it returns all 24 nodes, and seeded at either
    mode's entry it returns the same 22. The topology cannot tell the modes
    apart, which is why ``PLAN_TEMPLATES`` is a declaration.
    """
    topology = _topology()
    return _reachable_from(topology.nodes, topology.hops, seed)


def get_plan_template(mode: WorkflowMode | str) -> ModeTemplate:
    """The declaration for one mode.

    Unknown names raise ``KeyError`` -- the same contract as
    ``get_retry_policy`` and ``takeover_hazard``, and for the same reason: a
    default would answer for a mode nobody classified. The key is the
    ``WorkflowMode`` member; a plain ``"trend"`` resolves because
    ``WorkflowMode`` is a ``StrEnum``.
    """
    try:
        key = WorkflowMode(mode)
    except ValueError as exc:
        raise KeyError(mode) from exc
    return PLAN_TEMPLATES[key]


def export_plan(mode: WorkflowMode | str) -> Plan:
    """The plan for ``mode``, read out of ``build_graph()``.

    Refuses (``PlanExportError``) when the template names a node or hop the
    graph does not have, rather than returning a plan with that part dropped.
    """
    template = get_plan_template(mode)
    topology = _topology()

    bad_entry = template.entry not in topology.nodes
    bad_hops = sorted(
        f"{hop.source} -> {hop.target}"
        for hop in template.excludes
        if (hop.source, hop.target) not in topology.hops
    )
    if bad_entry or bad_hops:
        raise PlanExportError(
            f"template for {str(mode)!r} names things the graph does not have: "
            f"entry {template.entry!r} present={not bad_entry}, "
            f"hops missing from the graph={bad_hops}"
        )

    node_set = _plan_nodes(template, topology)
    kept = _mode_edges(template, topology)
    steps = tuple(
        PlanStep(
            node=node,
            # The filter is load-bearing here: a predecessor can sit outside the
            # plan while the hop into a reachable node is still there. In trend
            # mode ``viral_matcher`` is reachable through ``draft_gate`` while
            # its other ingress comes from ``brief_gate``, which that mode
            # cannot reach.
            preceded_by=tuple(sorted(src for src, dst in kept if dst == node and src in node_set)),
            # No filter needed, and that is a one-line proof rather than a
            # coincidence: the plan is the set reachable from the root through
            # ``kept``, so a kept hop out of a plan node lands in the plan -- or
            # on the ``__end__`` sentinel, which is not a node. A guard here
            # would be a condition that is never false.
            followed_by=tuple(sorted(dst for src, dst in kept if src == node)),
        )
        for node in sorted(node_set)
    )
    return Plan(mode=WorkflowMode(mode), entry=template.entry, steps=steps)


def orchestrator_destinations(mode: WorkflowMode) -> dict[WorkflowPhase, str]:
    """What ``orchestrator_router`` answers in ``mode``, phase by phase.

    Read by *calling* the router, not by reading its annotation. Now that the
    annotation is a ``Literal`` (S2) the two would agree, and that is exactly
    why the weaker-reading-but-stronger-evidence one is kept: this is the only
    statement in the module that observes the router rather than restating it,
    so ``destination_is_not_a_router_answer`` compares a declaration against
    behaviour instead of against a second reading of the same declaration.

    The router reads state and returns a name -- nothing is written.
    """
    return {
        phase: orchestrator_router(XHSGrowthState(workflow_mode=mode, phase=phase))
        for phase in WorkflowPhase
    }


#: The three routers that all ask one question -- where does a ``reangle`` send
#: the run -- and the two hops that exist only when a mode walks the
#: ``viral_matcher -> blogger_scout -> blogger_gate`` loop. Named constants so the
#: checks below read as statements about routers rather than about strings.
_REANGLE_ROUTERS: Final[tuple[str, ...]] = (
    "ripple_finalize",
    "ripple_gate",
    "ripple_late_recheck",
)
_BLOGGER_LOOP_HOPS: Final[tuple[tuple[str, str], ...]] = (
    ("blogger_gate", "draft_gate"),
    ("draft_gate", "viral_matcher"),
)


def mode_registry_complaints() -> dict[str, list[str]]:
    """Every way ``WORKFLOW_MODES`` and the plan templates disagree.

    The mode registry (``backend/state/modes.py``) declares what each mode
    *means*; ``PLAN_TEMPLATES`` declares what each mode *can reach*. They are two
    independent statements about the same two modes, which is the only reason
    comparing them can find anything: deriving either one from the other would
    make every check below true by construction.

    Categories:

    ``mode_without_a_spec``
        a ``WorkflowMode`` member the registry does not describe.
    ``spec_entry_disagrees_with_the_template``
        the node the spec's IDLE route names is not the template's entry.
    ``phase_routes_disagree_with_the_template``
        the set of nodes the spec's phase table can route to is not exactly the
        set the template says this mode reaches through its entry.
    ``initial_phase_route_is_not_the_entry``
        ``phase_routes[initial_phase]`` is not the entry. The phase
        ``OrchestratorAgent`` writes and the node the entry router picks are one
        decision written down twice, so they are compared rather than assumed.
    ``reanalysis_node_is_not_a_router_answer``
        a ``reanalysis_node`` that one of the three ripple routers cannot return.
    ``blogger_loop_field_disagrees_with_the_template``
        ``runs_blogger_selection`` and the template's exclusions tell different
        stories about whether this mode walks the blogger loop. Both directions
        are complaints: the field describes the loop, so the plan must contain
        the loop's hops when it is true and exclude them when it is false.
    """
    no_spec: list[str] = []
    bad_entry: list[str] = []
    bad_routes: list[str] = []
    bad_initial: list[str] = []
    bad_reanalysis: list[str] = []
    bad_loop: list[str] = []

    for mode in WorkflowMode:
        spec = WORKFLOW_MODES.get(mode)
        template = PLAN_TEMPLATES.get(mode)
        if spec is None:
            no_spec.append(str(mode))
            continue
        if template is None:
            # A missing template is ``plan_registry_complaints``' category.
            continue

        if spec.entry != template.entry:
            bad_entry.append(
                f"{str(mode)}: the phase table's IDLE route is {spec.entry!r} while the "
                f"template's entry is {template.entry!r}"
            )

        routed = frozenset(spec.phase_routes.values())
        if routed != template.destinations:
            bad_routes.append(
                f"{str(mode)}: the phase table routes to {sorted(routed)} while the "
                f"template declares {sorted(template.destinations)}; only on one side: "
                f"{sorted(routed ^ template.destinations)}"
            )

        initial_destination = spec.route(spec.initial_phase)
        if initial_destination != spec.entry:
            bad_initial.append(
                f"{str(mode)}: initial_phase {str(spec.initial_phase)!r} routes to "
                f"{initial_destination!r}, not the entry {spec.entry!r}"
            )

        for source in _REANGLE_ROUTERS:
            if spec.reanalysis_node not in EDGES_BY_SOURCE[source].answers:
                bad_reanalysis.append(
                    f"{str(mode)}: reanalysis_node {spec.reanalysis_node!r} is not an "
                    f"answer of {source}"
                )

        excluded = {(hop.source, hop.target) for hop in template.excludes}
        for source, target in _BLOGGER_LOOP_HOPS:
            excluded_here = (source, target) in excluded
            if excluded_here and spec.runs_blogger_selection:
                bad_loop.append(
                    f"{str(mode)}: runs_blogger_selection is True but the template "
                    f"excludes {source} -> {target}"
                )
            elif not excluded_here and not spec.runs_blogger_selection:
                bad_loop.append(
                    f"{str(mode)}: runs_blogger_selection is False but the template does "
                    f"not exclude {source} -> {target}"
                )

    complaints = {
        "mode_without_a_spec": no_spec,
        "spec_entry_disagrees_with_the_template": bad_entry,
        "phase_routes_disagree_with_the_template": bad_routes,
        "initial_phase_route_is_not_the_entry": bad_initial,
        "reanalysis_node_is_not_a_router_answer": bad_reanalysis,
        "blogger_loop_field_disagrees_with_the_template": bad_loop,
    }
    return {key: sorted(rows) for key, rows in complaints.items() if rows}


def plan_registry_complaints() -> dict[str, list[str]]:
    """Every way the registry and ``build_graph()`` disagree.

    An empty mapping means they agree. Empty categories are omitted, so
    ``== {}`` is the whole assertion. Every category is shown noticing a
    synthetic disagreement in ``tests/unit/graph/test_plan_registry.py`` --
    a category that cannot be made to fire is an always-true condition wearing
    a check's clothes, and S1 retired one of those for that reason. The
    categories are:

    ``mode_without_template``
        a ``WorkflowMode`` member nothing declares.
    ``entry_not_a_graph_node``
        a template's entry is not a node.
    ``excluded_hop_not_in_graph``
        a template excludes a hop the graph does not have.
    ``decider_is_not_the_router_at_that_source``
        an exclusion names a router that is not the one registered there.
    ``destination_is_not_a_router_answer``
        a declared destination the router does not actually return (measured by
        calling it, not by re-reading its annotation).
    ``entry_vocabulary_disagrees_with_the_edges``
        the union of the modes' declared destinations is not exactly what the
        entry *edge* declares it may answer. This is the joint between this
        module and ``backend/graph/wiring.py``: the modes say which answers
        belong to them, the edge says which answers exist, and neither may
        mention one the other has never heard of.
    ``hop_dead_in_every_mode`` / ``node_dead_in_every_mode``
        the backward direction: something the graph has that no mode's plan
        reaches.

    The mode registry's own half of this -- ``WORKFLOW_MODES`` against the same
    templates -- is :func:`mode_registry_complaints`, merged into the mapping
    below so that ``== {}`` stays the whole assertion.
    """
    topology = _topology()
    observed = {mode: orchestrator_destinations(mode) for mode in WorkflowMode}
    resolvable = frozenset(dst for src, dst in topology.hops if src == _ROOT)
    entry_answers = frozenset(EDGES_BY_SOURCE[_ROOT].answers)
    declared_vocabulary = frozenset().union(
        *(template.destinations for template in PLAN_TEMPLATES.values())
    )

    missing_template: list[str] = []
    bad_entry: list[str] = []
    bad_exclude: list[str] = []
    bad_decider: list[str] = []
    unreturned: list[str] = []
    unresolvable: list[str] = []
    vocabulary: list[str] = []

    if entry_answers != declared_vocabulary:
        vocabulary.append(
            f"the {_ROOT} edge answers {sorted(entry_answers)} while the templates "
            f"declare {sorted(declared_vocabulary)}; only on one side: "
            f"{sorted(entry_answers ^ declared_vocabulary)}"
        )

    for mode in WorkflowMode:
        template = PLAN_TEMPLATES.get(mode)
        if template is None:
            missing_template.append(str(mode))
            continue

        if template.entry not in topology.nodes:
            bad_entry.append(f"{str(mode)}: entry {template.entry!r} is not a node")

        answers = set(observed[mode].values())
        for destination in sorted(template.destinations - answers):
            unreturned.append(f"{str(mode)}: {destination!r} is not an answer it gives")
        # No exemption list any more (S2): a destination the router really gives
        # while the path map cannot resolve it is a complaint, full stop.
        for destination in sorted(template.destinations - resolvable):
            unresolvable.append(
                f"{str(mode)}: router answers {destination!r} and the path map has no entry"
            )

        for hop in template.excludes:
            if (hop.source, hop.target) not in topology.hops:
                bad_exclude.append(f"{str(mode)}: {hop.source} -> {hop.target} is not a hop")
            registered = topology.routers.get(hop.source)
            if registered != hop.decided_by:
                bad_decider.append(
                    f"{str(mode)}: {hop.source} is routed by {registered!r}, not {hop.decided_by!r}"
                )

    plans = {mode: _plan_nodes(template, topology) for mode, template in PLAN_TEMPLATES.items()}
    declared_nodes: set[str] = set()
    for nodes in plans.values():
        declared_nodes |= nodes
    excluded_everywhere = (
        set.intersection(
            *({(hop.source, hop.target) for hop in t.excludes} for t in PLAN_TEMPLATES.values())
        )
        if plans
        else set()
    )
    dead_hops = sorted(hop for hop in topology.hops if hop in excluded_everywhere)

    complaints = {
        "mode_without_template": missing_template,
        "entry_not_a_graph_node": bad_entry,
        "excluded_hop_not_in_graph": bad_exclude,
        "decider_is_not_the_router_at_that_source": bad_decider,
        "destination_is_not_a_router_answer": unreturned,
        "entry_vocabulary_disagrees_with_the_edges": vocabulary,
        "router_answer_no_path_map_entry": unresolvable,
        "hop_dead_in_every_mode": [f"{src} -> {dst}" for src, dst in dead_hops],
        "node_dead_in_every_mode": sorted(topology.nodes - declared_nodes),
    }
    own = {key: sorted(rows) for key, rows in complaints.items() if rows}
    return {**mode_registry_complaints(), **own}
