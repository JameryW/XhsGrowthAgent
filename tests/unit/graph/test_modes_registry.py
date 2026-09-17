"""The join between the mode registry and the graph (P2c-S3a).

``backend/state/modes.py`` declares what each mode means; the graph has to live
up to it. Two things are pinned here:

* **the routers read the registry.** Without this, "nine read points converged
  into one registry" would be a claim about a table that production code might
  have stopped consulting -- the S2 lesson, where a table-to-graph traversal had
  to be pinned by behaviour after a mutation survived by rewiring it. Each test
  first pins the unpatched answer and then patches the registry, so a pass
  cannot come from the answer being the same either way.
* **the registry agrees with the plan templates**, through
  ``mode_registry_complaints``: the exhaustive-registry check, the entry check,
  the phase-table check, the initial-phase check, the reanalysis check and the
  blogger-loop check. Each category is shown noticing a synthetic disagreement,
  because a category that cannot be made to fire is an always-true condition
  wearing a check's clothes.

One defect can light up two categories -- a wrong IDLE route is both "the entry
is not what the template calls the entry" and "the phase the orchestrator writes
does not route to the entry" -- and a test below pins that division of labour by
also asserting which category stays *silent*.
"""

from __future__ import annotations

import dataclasses
from types import MappingProxyType
from typing import Any

import pytest

import backend.graph.plan as plan_module
import backend.state.modes as modes_module
from backend.graph.plan import mode_registry_complaints, plan_registry_complaints
from backend.graph.routers import (
    blogger_gate_router,
    draft_gate_router,
    orchestrator_router,
    ripple_finalize_router,
    ripple_gate_router,
    ripple_late_recheck_router,
)
from backend.state.enums import WorkflowMode, WorkflowPhase
from backend.state.modes import WORKFLOW_MODES, ModeSpec


def _registry(mode: WorkflowMode, **changes: Any) -> MappingProxyType:
    """The registry with ``changes`` applied to ``mode``'s spec."""
    out = dict(WORKFLOW_MODES)
    out[mode] = dataclasses.replace(out[mode], **changes)
    return MappingProxyType(out)


def _drop(mode: WorkflowMode) -> MappingProxyType:
    """The registry with ``mode``'s spec removed."""
    return MappingProxyType({k: v for k, v in WORKFLOW_MODES.items() if k is not mode})


def _install(monkeypatch: pytest.MonkeyPatch, registry: MappingProxyType) -> None:
    """Install ``registry`` where it is *used*.

    ``plan.py`` imports the name, so patching only ``backend.state.modes`` would
    leave the checker reading the real table and quietly make these tests pass
    for the wrong reason.
    """
    monkeypatch.setattr(modes_module, "WORKFLOW_MODES", registry)
    monkeypatch.setattr(plan_module, "WORKFLOW_MODES", registry)


class TestTheRegistryIsWhatTheGraphAgreesWith:
    def test_nothing_complains_about_the_shipped_registry(self) -> None:
        assert mode_registry_complaints() == {}

    def test_the_plan_checker_carries_the_mode_categories(self, monkeypatch) -> None:
        # ``plan_registry_complaints() == {}`` is meant to stay the whole
        # assertion, so the mode categories must be merged into it rather than
        # living beside it.
        _install(monkeypatch, _registry(WorkflowMode.TREND, runs_blogger_selection=False))
        assert "blogger_loop_field_disagrees_with_the_template" in plan_registry_complaints()


class TestTheRoutersReadTheRegistry:
    def test_the_entry_router_reads_the_mode_spec(self, monkeypatch) -> None:
        # Pinned first: with the shipped registry, ANALYZING routes to analyst.
        state = {"phase": WorkflowPhase.ANALYZING, "workflow_mode": "trend"}
        assert orchestrator_router(state) == "analyst"

        routes = dict(WORKFLOW_MODES[WorkflowMode.TREND].phase_routes)
        routes[WorkflowPhase.ANALYZING] = "copywriter"
        _install(monkeypatch, _registry(WorkflowMode.TREND, phase_routes=routes))
        assert orchestrator_router(state) == "copywriter"

    def test_the_gate_routers_read_the_blogger_loop_field(self, monkeypatch) -> None:
        # A trend thread with no selected blogger: the gates let it through to
        # the loop.
        state = {"selected_blogger": {}, "workflow_mode": "trend"}
        assert blogger_gate_router(state) == "draft_gate"
        assert draft_gate_router(state) == "viral_matcher"

        _install(monkeypatch, _registry(WorkflowMode.TREND, runs_blogger_selection=False))
        assert blogger_gate_router(state) == "copywriter"
        assert draft_gate_router(state) == "shooting_planner"

    def test_the_ripple_routers_read_the_reanalysis_node(self, monkeypatch) -> None:
        state = {"ripple_decision": {"action": "reangle"}, "workflow_mode": "trend"}
        for router in (ripple_gate_router, ripple_finalize_router, ripple_late_recheck_router):
            assert router(state) == "content_strategist"

        _install(monkeypatch, _registry(WorkflowMode.TREND, reanalysis_node="brief_analyzer"))
        for router in (ripple_gate_router, ripple_finalize_router, ripple_late_recheck_router):
            assert router(state) == "brief_analyzer"


class TestTheRegistryIsExhaustive:
    def test_a_mode_with_no_spec_is_a_complaint(self, monkeypatch) -> None:
        _install(monkeypatch, _drop(WorkflowMode.TREND))
        complaints = mode_registry_complaints()
        assert "trend" in "".join(complaints["mode_without_a_spec"])


class TestTheEntryTheSpecNames:
    def test_an_idle_route_the_template_does_not_call_the_entry(self, monkeypatch) -> None:
        routes = dict(WORKFLOW_MODES[WorkflowMode.TREND].phase_routes)
        routes[WorkflowPhase.IDLE] = "analyst"
        _install(monkeypatch, _registry(WorkflowMode.TREND, phase_routes=routes))
        complaints = mode_registry_complaints()
        assert "'analyst'" in "".join(complaints["spec_entry_disagrees_with_the_template"])
        # The *set* of routed nodes is unchanged -- SCOUTING still routes to
        # trend_scout -- so the set-level check stays silent. That is the point
        # of having both: it is not a second report of the same defect.
        assert "phase_routes_disagree_with_the_template" not in complaints
        # What it cannot see, the initial-phase check does.
        assert "initial_phase_route_is_not_the_entry" in complaints

    def test_a_phase_the_template_does_not_declare(self, monkeypatch) -> None:
        # BRIEFING is not a trend phase at all: its route target belongs to the
        # brief mode, so the two declarations cannot both be right.
        routes = dict(WORKFLOW_MODES[WorkflowMode.TREND].phase_routes)
        routes[WorkflowPhase.BRIEFING] = "brief_analyzer"
        _install(monkeypatch, _registry(WorkflowMode.TREND, phase_routes=routes))
        complaints = mode_registry_complaints()
        assert "brief_analyzer" in "".join(complaints["phase_routes_disagree_with_the_template"])

    def test_an_initial_phase_that_does_not_route_to_the_entry(self, monkeypatch) -> None:
        # ``analyst`` is a legal trend destination, so this is a disagreement
        # about *which* route is the starting one and not about the vocabulary.
        routes = dict(WORKFLOW_MODES[WorkflowMode.TREND].phase_routes)
        routes[WorkflowPhase.SCOUTING] = "analyst"
        _install(monkeypatch, _registry(WorkflowMode.TREND, phase_routes=routes))
        complaints = mode_registry_complaints()
        assert sorted(complaints) == ["initial_phase_route_is_not_the_entry"]

    def test_a_reanalysis_node_no_ripple_router_can_return(self, monkeypatch) -> None:
        _install(monkeypatch, _registry(WorkflowMode.TREND, reanalysis_node="analyst"))
        complaints = mode_registry_complaints()
        assert "analyst" in "".join(complaints["reanalysis_node_is_not_a_router_answer"])


class TestTheBloggerLoopField:
    def test_claiming_the_loop_while_the_template_excludes_it(self, monkeypatch) -> None:
        # brief mode's template excludes both loop hops, so a spec claiming the
        # loop is a spec nothing can honour.
        _install(monkeypatch, _registry(WorkflowMode.BRIEF, runs_blogger_selection=True))
        rows = "".join(mode_registry_complaints()["blogger_loop_field_disagrees_with_the_template"])
        assert "brief" in rows
        assert "blogger_gate -> draft_gate" in rows
        assert "draft_gate -> viral_matcher" in rows

    def test_disclaiming_the_loop_while_the_template_allows_it(self, monkeypatch) -> None:
        # The direction that mattered before this slice: nothing at all noticed
        # a mode whose spec said "no blogger loop" while its plan still walked
        # into one.
        _install(monkeypatch, _registry(WorkflowMode.TREND, runs_blogger_selection=False))
        rows = "".join(mode_registry_complaints()["blogger_loop_field_disagrees_with_the_template"])
        assert "trend" in rows
        assert "blogger_gate -> draft_gate" in rows
        assert "draft_gate -> viral_matcher" in rows


class TestTheSpecItself:
    def test_the_shipped_specs_derive_their_entries(self) -> None:
        for spec in WORKFLOW_MODES.values():
            assert isinstance(spec, ModeSpec)
            assert spec.entry == spec.phase_routes[WorkflowPhase.IDLE]
