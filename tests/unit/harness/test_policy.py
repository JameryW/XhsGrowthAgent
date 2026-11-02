"""P3/E2: the default harness policy must be *exactly* today's behaviour.

The point of the interface is that a variant's snapshot can be diffed against a
baseline's.  If the baseline itself quietly disagreed with the current routing,
budget or tool limits, every later comparison would be measuring the wrong
thing -- so these tests delegate to the same owners the policy claims to read.
"""

from __future__ import annotations

import json

import pytest

from backend.config.models import TaskType, resolve_model_id
from backend.harness.policy import (
    DefaultHarnessPolicy,
    HarnessPolicy,
    ToolLimits,
    default_policy,
    describe,
)
from backend.tools.runtime.catalog import build_registry
from backend.tools.runtime.registry import UnknownCapabilityError


def test_the_default_policy_satisfies_the_protocol():
    assert isinstance(default_policy(), HarnessPolicy)


def test_route_model_matches_the_router_for_every_task_type():
    policy = DefaultHarnessPolicy()
    for task in TaskType:
        assert policy.route_model(task) == resolve_model_id(task), task


def test_context_budget_is_the_current_no_trimming_behaviour():
    policy = DefaultHarnessPolicy()
    assert policy.context_budget() is None
    assert policy.context_budget(phase="reviewing") is None


def test_escalation_is_honestly_empty():
    policy = DefaultHarnessPolicy()
    assert all(policy.escalation_targets(task) == () for task in TaskType)


def test_tool_limits_are_read_from_the_catalogue():
    policy = DefaultHarnessPolicy()
    spec = build_registry().spec("xhs.publish")

    limits = policy.tool_limits("xhs.publish")

    assert limits == ToolLimits(
        capability="xhs.publish",
        max_concurrency=spec.max_concurrency,
        timeout_s=float(spec.effective_timeout_s) if spec.effective_timeout_s is not None else None,
    )


def test_an_unknown_capability_is_refused_rather_than_invented():
    with pytest.raises(UnknownCapabilityError):
        DefaultHarnessPolicy().tool_limits("xhs.does_not_exist")


def test_describe_is_a_stable_json_snapshot_of_the_same_answers():
    policy = DefaultHarnessPolicy()
    snapshot = describe(policy, capabilities=("xhs.publish",))

    json.dumps(snapshot)  # must be JSON-able: this is what E3 diffs
    assert snapshot["models"] == {task.value: resolve_model_id(task) for task in TaskType}
    assert snapshot["context_budget"] is None
    assert snapshot["escalation"] == {task.value: [] for task in TaskType}
    assert snapshot["tool_limits"]["xhs.publish"]["capability"] == "xhs.publish"


def test_describe_differs_when_a_variant_routes_differently():
    class _Variant(DefaultHarnessPolicy):
        def route_model(self, task_type: TaskType) -> str:
            return "variant-model"

    baseline = describe(DefaultHarnessPolicy(), capabilities=("xhs.publish",))
    variant = describe(_Variant(), capabilities=("xhs.publish",))

    assert variant["models"]["writing"] == "variant-model"
    assert variant["models"] != baseline["models"]
    assert variant["tool_limits"] == baseline["tool_limits"]


def test_describe_samples_the_context_budget_per_phase():
    """A variant that only changes a phase budget must show up in the diff."""
    from backend.harness.policy import describe

    class _PhaseBudget(DefaultHarnessPolicy):
        def context_budget(self, *, phase: str = "") -> int | None:
            return 4000 if phase == "publishing" else None

    baseline = describe(DefaultHarnessPolicy(), capabilities=("xhs.publish",))
    variant = describe(_PhaseBudget(), capabilities=("xhs.publish",))
    assert baseline["context_budgets"]["publishing"] is None
    assert variant["context_budgets"]["publishing"] == 4000
    assert variant["context_budgets"]["reviewing"] is None
    assert baseline["context_budget"] == variant["context_budget"] is None
