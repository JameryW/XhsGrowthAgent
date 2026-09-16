"""Which nodes an automatic takeover refuses (P2b-S3).

Two different claims are pinned here.

1. **The registry is exhaustive and strict.** Every node ``build_graph()``
   installs has an entry, and an unknown name raises rather than defaulting.
   The direction matters: a default would answer "safe" for a node nobody
   classified, and "safe" is the one dangerous answer available.

2. **The refusal set is the one the rulings named.** Red line 2 ("never
   automatically re-run a node that already produced a side effect") is
   ``publisher``. Ruling 3 ("a takeover may restore the execution loop, never
   make a person's decision for them") is every node that parks on
   ``interrupt()`` -- resuming one with a bare ``ainvoke(None)`` would hand the
   gate ``None`` as the answer.

``takeover_verdict`` deliberately classifies only the *pending* nodes. The last
test here is what makes that sufficient rather than merely cheap: it pins the
structural fact that the only way into ``publisher`` is through
``publish_gate``, which is itself a refusal. If someone later adds a second
edge into ``publisher``, this file fails and the verdict's premise has to be
re-argued.
"""

from __future__ import annotations

from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any

import pytest

from backend.graph.builder import build_graph
from backend.graph.error_handling import get_retry_policy
from backend.graph.takeover_safety import (
    TAKEOVER_HAZARDS,
    TakeoverHazard,
    takeover_hazard,
    takeover_verdict,
)
from backend.state.machine import derive_status

#: Nodes whose body calls interrupt(). Read off the node sources, not off the
#: registry, so this list is an independent statement of the same fact.
_INTERRUPT_NODES = (
    "blogger_gate",
    "brief_gate",
    "publish_gate",
    "review_gate",
    "ripple_finalize",
    "ripple_gate",
    "ripple_late_recheck",
)


def _graph_node_names() -> list[str]:
    return [name for name in build_graph().nodes if name not in ("__start__", "__end__")]


def _branch_targets(builder: Any) -> Iterable[tuple[str, str]]:
    """``(source, target)`` for every conditional edge, flattened."""
    for source, branches in builder.branches.items():
        for spec in branches.values():
            ends = getattr(spec, "ends", None)
            if not isinstance(ends, dict):
                continue
            for target in ends.values():
                yield source, str(target)


class TestTheRegistryIsExhaustive:
    def test_every_graph_node_is_registered(self):
        missing = [name for name in _graph_node_names() if name not in TAKEOVER_HAZARDS]
        assert missing == []

    def test_no_entry_describes_a_node_that_no_longer_exists(self):
        """A stale entry is a claim about code that is gone."""
        extra = [name for name in TAKEOVER_HAZARDS if name not in _graph_node_names()]
        assert extra == []

    def test_an_unknown_node_raises_instead_of_defaulting(self):
        with pytest.raises(KeyError):
            takeover_hazard("no_such_node")

    def test_every_value_is_a_hazard_class(self):
        for node, hazard in TAKEOVER_HAZARDS.items():
            assert isinstance(hazard, TakeoverHazard), node


class TestTheRefusalSet:
    def test_every_interrupt_node_needs_a_human(self):
        for node in _INTERRUPT_NODES:
            assert takeover_hazard(node) is TakeoverHazard.NEEDS_HUMAN, node

    def test_the_publisher_is_irreversible_not_merely_unsafe(self):
        assert takeover_hazard("publisher") is TakeoverHazard.IRREVERSIBLE

    def test_the_publisher_is_the_only_irreversible_node(self):
        irreversible = [
            name
            for name, hazard in TAKEOVER_HAZARDS.items()
            if hazard is TakeoverHazard.IRREVERSIBLE
        ]
        assert irreversible == ["publisher"]

    def test_it_agrees_with_the_retry_registry_about_that_node(self):
        """Both registries single out the same node for the same reason.

        P0-W3 refused ``publisher`` framework-level auto retry; S3 refuses it
        automatic resume. If these ever disagree, one of them is wrong.
        """
        assert get_retry_policy("publisher") is None
        assert takeover_hazard("publisher") is TakeoverHazard.IRREVERSIBLE


class TestTheVerdict:
    def test_safe_pending_work_may_resume(self):
        assert takeover_verdict(["copywriter", "visual_designer"]) == (True, None)

    def test_nothing_pending_may_resume(self):
        """The scan filters empty sets earlier; the verdict must not invent a
        refusal for one."""
        assert takeover_verdict([]) == (True, None)

    def test_a_pending_gate_refuses(self):
        assert takeover_verdict(["copywriter", "review_gate"]) == (
            False,
            TakeoverHazard.NEEDS_HUMAN,
        )

    def test_a_pending_publisher_refuses(self):
        assert takeover_verdict(["publisher"]) == (False, TakeoverHazard.IRREVERSIBLE)

    def test_the_worst_hazard_is_the_one_reported(self):
        allowed, worst = takeover_verdict(["review_gate", "publisher"])
        assert allowed is False
        assert worst is TakeoverHazard.IRREVERSIBLE

    def test_the_answer_does_not_depend_on_the_order(self):
        assert takeover_verdict(["publisher", "review_gate"])[1] is TakeoverHazard.IRREVERSIBLE
        assert takeover_verdict(["review_gate", "publisher"])[1] is TakeoverHazard.IRREVERSIBLE

    def test_an_unknown_pending_node_refuses_by_raising(self):
        """Refusing is the only safe failure, and raising is how it refuses."""
        with pytest.raises(KeyError):
            takeover_verdict(["copywriter", "no_such_node"])


class TestThePendingOnlyPremise:
    def test_the_only_way_into_the_publisher_is_a_gate(self):
        """The whole argument for classifying pending nodes only.

        A resume that can reach ``publisher`` must first park on
        ``publish_gate``, and ``publish_gate`` is NEEDS_HUMAN -- so the gate
        stops it before the re-post. Add a direct edge into ``publisher`` and
        this test fails, which is the point: the premise, not just the code.
        """
        builder = build_graph()
        sources: set[str] = {str(src) for src, dst in builder.edges if str(dst) == "publisher"}
        sources |= {str(src) for src, dst in _branch_targets(builder) if dst == "publisher"}

        assert sources == {"publish_gate"}
        assert takeover_hazard("publish_gate") is TakeoverHazard.NEEDS_HUMAN


#: Nodes ``derive_status`` parks the workflow on, read off its own gate list.
#: ``test_it_parks_the_workflow`` below is what makes this list evidence rather
#: than a restatement: each name is fed to ``derive_status`` and has to come
#: back as an ``awaiting_*`` status.
_AWAITING_GATES = (
    "review_gate",
    "choice_gate",
    "draft_gate",
    "brief_gate",
    "ripple_gate",
    "blogger_gate",
    "publish_gate",
)

#: The one refusal with no structural source -- see the test that names it.
_NAMED_WITHOUT_A_SOURCE = {"evaluator_gate"}


def _parked_on(node: str) -> SimpleNamespace:
    return SimpleNamespace(values={"session_id": "t"}, next=(node,), interrupts=(), tasks=())


class TestGatesParkAndThereforeRefuse:
    """The reasoning, rather than the table: a node that parks the workflow for
    a person is a node a scan must not advance on that person's behalf."""

    @pytest.mark.parametrize("gate", _AWAITING_GATES)
    def test_it_parks_the_workflow(self, gate: str):
        assert derive_status(_parked_on(gate)).value.startswith("awaiting_")

    @pytest.mark.parametrize("gate", _AWAITING_GATES)
    def test_and_is_therefore_refused(self, gate: str):
        assert takeover_hazard(gate) is TakeoverHazard.NEEDS_HUMAN


class TestEveryRefusalHasANamedSource:
    def test_the_needs_human_set_is_exactly_its_sources(self):
        """No entry is an opinion without a reason outside this module.

        Interrupt callers (``_INTERRUPT_NODES``, grepped from the node sources)
        plus the nodes ``derive_status`` parks on (``_AWAITING_GATES``, itself
        verified above) plus the one named exception account for the whole set.
        An entry with no source here would mean a node was classified by feel;
        a *missing* entry would mean a refusal the scan does not perform.
        """
        needs_human = {
            name
            for name, hazard in TAKEOVER_HAZARDS.items()
            if hazard is TakeoverHazard.NEEDS_HUMAN
        }
        assert needs_human == set(_INTERRUPT_NODES) | set(_AWAITING_GATES) | _NAMED_WITHOUT_A_SOURCE

    def test_the_named_exception_is_the_parked_evaluator_loop(self):
        """``evaluator_gate`` is the one refusal that is not structural.

        Its reason is the P0-W5 continuation channel: ``/resume`` treats
        ``PAUSE_REASON_EVALUATOR_FAIL_CLOSED`` as a thread the evaluator parked
        on purpose, and only a person restarts it. Named here so the entry has
        a written justification rather than looking like an omission upstream.
        """
        assert takeover_hazard("evaluator_gate") is TakeoverHazard.NEEDS_HUMAN
        assert {"evaluator_gate"} == _NAMED_WITHOUT_A_SOURCE
