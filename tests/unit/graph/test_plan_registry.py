"""The plan registry has to agree with the graph, in both directions.

``plan_registry_complaints() == {}`` would pass just as happily if the check
were reading nothing at all, so every failure surface is first shown noticing a
*synthetic* disagreement and only then asserted clean on the live graph.

The one that matters most is
:meth:`TestTheExportReadsTheGraphNotItsKeys.test_evaluator_gate_leads_to_the_publish_gate`:
``Branch.ends`` is the path map (router answer -> node), and exactly one row in
the whole graph has an answer that differs from its node, so an export that read
it as a sequence of targets would look right on 17 of 18 branches and quietly
drop the human authorisation gate on the eighteenth.
"""

from __future__ import annotations

import pytest

from backend.graph import plan as plan_module
from backend.graph.builder import build_graph
from backend.graph.plan import (
    PLAN_TEMPLATES,
    ExcludedHop,
    ModeTemplate,
    PlanExportError,
    export_plan,
    get_plan_template,
    graph_nodes,
    orchestrator_destinations,
    plan_registry_complaints,
    reachable_nodes,
)
from backend.graph.wiring import EDGES_BY_SOURCE, ConditionalEdge
from backend.state.enums import WorkflowMode, WorkflowPhase

TREND = WorkflowMode.TREND
BRIEF = WorkflowMode.BRIEF


def _replace(monkeypatch, mode, **changes):
    """Swap in a doctored template for ``mode`` for the duration of one test."""
    monkeypatch.setitem(PLAN_TEMPLATES, mode, ModeTemplate(**{**_as_kwargs(mode), **changes}))


def _as_kwargs(mode):
    template = PLAN_TEMPLATES[mode]
    return {
        "entry": template.entry,
        "destinations": template.destinations,
        "excludes": template.excludes,
    }


def _key_to_target(source_name: str = "evaluator_gate") -> dict[str, str]:
    """The raw path map of the branch at ``source_name``, keys included."""
    for source, per_source in build_graph().branches.items():
        if source == source_name:
            for branch in per_source.values():
                return dict(branch.ends or {})
    raise AssertionError(f"no branch at {source_name!r}")


class TestTheRegistryAndTheGraphAgree:
    def test_state_graph_and_registry_agree(self):
        assert plan_registry_complaints() == {}

    def test_every_registered_node_is_reachable_in_some_mode(self):
        """The backward direction: an undeclared region of the graph is the
        condition this whole ticket exists to end."""
        declared = set()
        for mode in PLAN_TEMPLATES:
            declared |= set(export_plan(mode).nodes)
        assert declared == set(graph_nodes())

    def test_every_workflow_mode_has_a_template(self):
        assert set(PLAN_TEMPLATES) == set(WorkflowMode)

    def test_the_graph_is_mode_blind(self):
        """Fact 2 of the module docstring, measured.

        If this ever stops holding -- a mode-aware edge appears in
        ``build_graph()`` -- then mode membership *can* be derived and the
        registry should become one, so this going red is the signal to look,
        not a nuisance.
        """
        assert reachable_nodes("orchestrator") == graph_nodes()
        assert reachable_nodes(PLAN_TEMPLATES[TREND].entry) == reachable_nodes(
            PLAN_TEMPLATES[BRIEF].entry
        )
        assert reachable_nodes(PLAN_TEMPLATES[TREND].entry) != graph_nodes()

    def test_the_two_modes_do_not_get_the_same_plan(self):
        trend = set(export_plan(TREND).nodes)
        brief = set(export_plan(BRIEF).nodes)
        assert trend < brief
        assert "brief_analyzer" not in trend
        assert "brief_analyzer" in brief

    def test_a_mode_excludes_hops_and_not_only_nodes(self):
        """The node sets are nearly the same, so a registry that only moved
        nodes around would look right. The brief mode's actual difference is
        that it does not *take* the loops into the trend pipeline -- three hops
        whose targets stay in the plan by another route, so only the hop
        assertion can see them.
        """
        trend = export_plan(TREND)
        brief = export_plan(BRIEF)

        assert "trend_scout" not in brief.step("orchestrator").followed_by
        assert "trend_scout" in trend.step("orchestrator").followed_by

        assert "draft_gate" not in brief.step("blogger_gate").followed_by
        assert "draft_gate" in trend.step("blogger_gate").followed_by

        assert "viral_matcher" not in brief.step("draft_gate").followed_by
        assert "viral_matcher" in trend.step("draft_gate").followed_by

        assert "content_strategist" not in brief.step("ripple_gate").followed_by
        assert "content_strategist" in trend.step("ripple_gate").followed_by

        assert "brief_analyzer" not in trend.step("ripple_gate").followed_by
        assert "brief_analyzer" in brief.step("ripple_gate").followed_by

    def test_a_step_the_plan_does_not_contain_is_a_key_error(self):
        with pytest.raises(KeyError):
            export_plan(TREND).step("brief_analyzer")


class TestTheCheckNoticesDisagreements:
    def test_an_entry_that_is_not_a_node(self, monkeypatch):
        _replace(monkeypatch, TREND, entry="not_a_node")
        assert "entry_not_a_graph_node" in plan_registry_complaints()

    def test_export_refuses_an_entry_that_is_not_a_node(self, monkeypatch):
        _replace(monkeypatch, TREND, entry="not_a_node")
        with pytest.raises(PlanExportError, match="not_a_node"):
            export_plan(TREND)

    def test_a_hop_the_graph_does_not_have(self, monkeypatch):
        _replace(
            monkeypatch,
            TREND,
            excludes=(*PLAN_TEMPLATES[TREND].excludes, ExcludedHop("analyst", "publisher", "z")),
        )
        assert "excluded_hop_not_in_graph" in plan_registry_complaints()

    def test_an_exclusion_attributed_to_the_wrong_router(self, monkeypatch):
        """The decider field is checked, not decorative: an exclusion credited
        to a router that does not route that source is a claim nobody owns."""
        template = PLAN_TEMPLATES[TREND]
        miscredited = tuple(
            ExcludedHop(hop.source, hop.target, "copywriter_router") for hop in template.excludes
        )
        _replace(monkeypatch, TREND, excludes=miscredited)
        assert "decider_is_not_the_router_at_that_source" in plan_registry_complaints()

    def test_a_destination_the_router_does_not_answer(self, monkeypatch):
        _replace(
            monkeypatch,
            TREND,
            destinations=PLAN_TEMPLATES[TREND].destinations | {"publisher"},
        )
        complaints = plan_registry_complaints()
        assert "destination_is_not_a_router_answer" in complaints
        # Both levels report it, which is what makes the joint an equality
        # rather than a containment: the per-mode class names the mode, the
        # joint class names the mismatch, and the joint has to fire here too or
        # dropping one of its two directions would be invisible.
        assert "entry_vocabulary_disagrees_with_the_edges" in complaints

    def test_an_unresolvable_router_answer_is_a_complaint(self, monkeypatch):
        """Kept even though the invariant S2 established makes it unreachable
        from the registry side -- every answer the entry router gives now has a
        path-map key. So the disagreement is injected where it can still come
        from: the *graph* losing a hop the router can answer (a hand-edited
        build, or a wiring table that dropped an entry).

        A category that cannot be made to fire is an always-true condition
        wearing a check's clothes, and S1 retired one of those; this is the
        test that keeps this one from becoming another.
        """
        topology = plan_module._topology()
        monkeypatch.setattr(
            plan_module,
            "_topology",
            lambda: plan_module._Topology(
                nodes=topology.nodes,
                hops=frozenset(h for h in topology.hops if h != ("orchestrator", "copywriter")),
                routers=dict(topology.routers),
            ),
        )
        complaints = plan_registry_complaints()
        assert "router_answer_no_path_map_entry" in complaints
        assert any("copywriter" in row for row in complaints["router_answer_no_path_map_entry"])

    def test_a_vocabulary_the_modes_do_not_cover(self, monkeypatch):
        """The joint between this registry and the edge table: the modes say
        which answers belong to them, the edge says which exist. Dropping one
        from both modes has to be visible, because an answer no mode claims is
        an answer nobody has classified.
        """
        for mode in (TREND, BRIEF):
            _replace(
                monkeypatch,
                mode,
                destinations=PLAN_TEMPLATES[mode].destinations - {"analyst"},
            )
        complaints = plan_registry_complaints()
        assert "entry_vocabulary_disagrees_with_the_edges" in complaints
        assert any(
            "analyst" in row for row in complaints["entry_vocabulary_disagrees_with_the_edges"]
        )
        # Removing a destination cannot trip the other direction.
        assert "destination_is_not_a_router_answer" not in complaints

    def test_an_answer_the_modes_do_not_cover(self, monkeypatch):
        """The other side of the same joint, and the reason it is an equality
        rather than a containment: an answer the entry *edge* declares that no
        mode claims belongs to it would mean a mode reading a value the
        registry never classified.
        """
        entry = EDGES_BY_SOURCE["orchestrator"]
        monkeypatch.setitem(
            plan_module.EDGES_BY_SOURCE,
            "orchestrator",
            ConditionalEdge(
                source=entry.source, router=entry.router, answers=(*entry.answers, "publisher")
            ),
        )
        complaints = plan_registry_complaints()
        assert "entry_vocabulary_disagrees_with_the_edges" in complaints
        assert any(
            "publisher" in row for row in complaints["entry_vocabulary_disagrees_with_the_edges"]
        )

    def test_the_brief_only_hop_off_the_entry_is_classified(self):
        """S2's own hop. Adding the entry's ``copywriter`` key created a hop
        that has to be attributed to a mode -- and it is brief-only, because
        trend mode's table has no CREATING key at all: ``creating`` falls
        through to the "trend_scout" default.
        """
        assert "copywriter" in orchestrator_destinations(BRIEF).values()
        assert "copywriter" not in orchestrator_destinations(TREND).values()

        assert "copywriter" in export_plan(BRIEF).step("orchestrator").followed_by
        assert "copywriter" not in export_plan(TREND).step("orchestrator").followed_by

    def test_the_entrys_answers_resolve_through_the_path_map(self):
        """What S1 registered as unresolvable, resolved."""
        assert _key_to_target("orchestrator")["copywriter"] == "copywriter"

    def test_a_hop_no_mode_can_take(self, monkeypatch):
        """``publisher`` has exactly one ingress; excluding it everywhere makes
        the hop unreachable from any plan."""
        for mode in (TREND, BRIEF):
            _replace(
                monkeypatch,
                mode,
                excludes=(
                    *PLAN_TEMPLATES[mode].excludes,
                    ExcludedHop("publish_gate", "publisher", "publish_gate_outcome"),
                ),
            )
        complaints = plan_registry_complaints()
        assert "hop_dead_in_every_mode" in complaints
        assert "node_dead_in_every_mode" in complaints
        assert any("publisher" in row for row in complaints["node_dead_in_every_mode"])


class TestTheExportReadsTheGraphNotItsKeys:
    def test_the_path_map_has_exactly_one_answer_that_is_not_its_node(self):
        """A measurement, kept as a tripwire.

        If this ever gains or loses a row, the docstring's fact 1 has to be
        re-measured. S2 changed the number of *rows* (the orchestrator map
        gained ``copywriter``) without adding one here, because that entry is
        the identity -- worth knowing when reading this as a change detector.
        """
        offenders = set()
        for source, per_source in build_graph().branches.items():
            for branch in per_source.values():
                for answer, node in (branch.ends or {}).items():
                    if answer != node:
                        offenders.add((source, answer, node))
        assert offenders == {("evaluator_gate", "publisher", "publish_gate")}

    def test_evaluator_gate_leads_to_the_publish_gate(self):
        """Non-vacuous: the graph's *keys* here are ``publisher``, so a
        sequence read would have produced ``evaluator_gate -> publisher``."""
        assert _key_to_target() == {
            "publisher": "publish_gate",
            "revise_content": "revise_content",
            "__end__": "__end__",
        }

        step = export_plan(TREND).step("evaluator_gate")
        assert "publish_gate" in step.followed_by
        assert "publisher" not in step.followed_by

        plan = export_plan(TREND)
        assert "publish_gate" in plan.nodes
        assert plan.step("publish_gate").preceded_by == ("evaluator_gate",)
        assert plan.step("publisher").preceded_by == ("publish_gate",)

    def test_the_export_never_invents_a_hop_the_graph_lacks(self):
        """Every followed_by has to be a real destination of that node."""
        for mode in PLAN_TEMPLATES:
            plan = export_plan(mode)
            known = set(plan.nodes) | {"__end__"}
            for step in plan.steps:
                assert set(step.followed_by) <= known, f"{mode}: {step.node}"
                assert set(step.preceded_by) <= set(plan.nodes), f"{mode}: {step.node}"

    def test_a_plan_is_a_reachability_set_not_a_node_filter(self, monkeypatch):
        """A plan is what the mode can *reach*, not the node list minus the cut
        endpoints: excluding one ingress takes the whole sub-graph behind it off
        the plan (``viral_matcher``, and with it ``blogger_scout``), and what
        remains reports only what remains.
        """
        _replace(
            monkeypatch,
            TREND,
            excludes=(
                *PLAN_TEMPLATES[TREND].excludes,
                ExcludedHop("draft_gate", "viral_matcher", "draft_gate_router"),
            ),
        )
        plan = export_plan(TREND)
        assert "viral_matcher" not in plan.nodes
        assert "blogger_scout" not in plan.nodes
        assert plan.step("draft_gate").followed_by == ("shooting_planner",)


class TestTheDeclaredVocabularyIsTheRouters:
    def test_the_entry_is_what_the_router_answers_for_an_idle_run(self):
        """``orchestrator_router`` answered a plain ``str`` until S2, so the
        declared entry was the only thing that could be checked against it, and
        the *brief* branch had no other test at all -- so it is corroborated by
        calling the router rather than by reading its annotation."""
        for mode in PLAN_TEMPLATES:
            assert orchestrator_destinations(mode)[WorkflowPhase.IDLE] == PLAN_TEMPLATES[mode].entry

    def test_the_declared_destinations_are_exactly_what_the_router_gives(self):
        for mode in PLAN_TEMPLATES:
            observed = set(orchestrator_destinations(mode).values())
            assert observed == set(PLAN_TEMPLATES[mode].destinations)


class TestUnknownModesAreRefused:
    def test_a_mode_nobody_classified_is_a_key_error(self):
        with pytest.raises(KeyError):
            get_plan_template("copywriter_mode")

    def test_export_refuses_a_mode_nobody_classified(self):
        with pytest.raises(KeyError):
            export_plan("copywriter_mode")

    def test_a_known_mode_resolves_through_its_string_value(self):
        assert get_plan_template("trend").entry == PLAN_TEMPLATES[TREND].entry
