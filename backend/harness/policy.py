"""Harness decision points (P3/E2): one injectable policy, default = today's behaviour.

The Adaptive Harness plan (`docs/adaptive-harness-eval-plan.md`) allows variants to
change exactly four things: model routing, context budget, tool retry/concurrency/
timeout limits, and escalation triggers.  Today those decisions are spread across
``config.models.resolve_model_id``, the context compiler's optional ``budget``
argument, the tool catalogue's ``max_concurrency`` / ``effective_timeout_s``, and
"nothing" (there is no escalation path).

This module gives them **one shape**.  ``DefaultHarnessPolicy`` only *reads* those
owners — it is deliberately not wired into any production call site, so importing
it changes no behaviour.  E3's A/B runner and E4's small-sample experiment consume
this interface; wiring the default policy into the runtime is a separate decision
(proposal question 5: defaults vs A/B-only).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any, Protocol, runtime_checkable

from backend.config.models import TaskType, resolve_model_id

__all__ = [
    "DefaultHarnessPolicy",
    "HarnessPolicy",
    "ToolLimits",
    "default_policy",
    "describe",
]


@dataclass(frozen=True)
class ToolLimits:
    """The runtime limits a capability declares today."""

    capability: str
    max_concurrency: int | None
    timeout_s: float | None


@runtime_checkable
class HarnessPolicy(Protocol):
    """The four decisions a harness variant may make differently."""

    def route_model(self, task_type: TaskType) -> str: ...

    def context_budget(self, *, phase: str = "") -> int | None: ...

    def tool_limits(self, capability: str) -> ToolLimits: ...

    def escalation_targets(self, task_type: TaskType) -> tuple[str, ...]: ...


@lru_cache(maxsize=1)
def _registry() -> Any:
    """The production catalogue, built once (import cost is the tools' imports)."""
    from backend.tools.runtime.catalog import build_registry

    return build_registry()


class DefaultHarnessPolicy:
    """The policy equivalent to today's code paths — and only that.

    Every method delegates to the module that already owns the answer, so a test
    can pin "default policy == current behaviour" instead of duplicating literals
    here.  No escalation exists yet, so that method answers honestly with ``()``.
    """

    def route_model(self, task_type: TaskType) -> str:
        return resolve_model_id(task_type)

    def context_budget(self, *, phase: str = "") -> int | None:
        # Agents call compile_prompt without a budget today, i.e. no trimming.
        return None

    def tool_limits(self, capability: str) -> ToolLimits:
        spec = _registry().spec(capability)
        timeout = spec.effective_timeout_s
        return ToolLimits(
            capability=capability,
            max_concurrency=spec.max_concurrency,
            timeout_s=float(timeout) if timeout is not None else None,
        )

    def escalation_targets(self, task_type: TaskType) -> tuple[str, ...]:
        # The router falls back to MODEL_FALLBACKS after retries; it never
        # escalates to a stronger model, so there is nothing to declare.
        return ()


def default_policy() -> DefaultHarnessPolicy:
    """The default policy singleton (stateless, so a new instance is harmless)."""
    return DefaultHarnessPolicy()


def describe(
    policy: HarnessPolicy,
    *,
    capabilities: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """A JSON-able snapshot of every decision the policy makes.

    This is what E3 compares between a baseline and a variant: two snapshots that
    are equal mean "the variant changed nothing", and a diff names exactly which
    decision moved.
    """
    limits = capabilities if capabilities is not None else _registry().capabilities()
    return {
        "models": {task.value: policy.route_model(task) for task in TaskType},
        "context_budget": policy.context_budget(),
        "escalation": {task.value: list(policy.escalation_targets(task)) for task in TaskType},
        "tool_limits": {name: asdict(policy.tool_limits(name)) for name in limits},
    }
