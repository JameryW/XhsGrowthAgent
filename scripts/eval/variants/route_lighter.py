"""A sample A/B variant: exactly one decision changes (P3/E3 demonstration).

Run it through the gate to see the diff path work end-to-end::

    python scripts/eval/run_gate.py --skip-benchmarks \
        --variant scripts.eval.variants.route_lighter:make_policy

This module is never imported by production code, so it cannot change a default —
that is the point of the E3 posture (variants are injected, defaults are frozen)
until the plan's question 5 is decided.  The route it changes is deliberately
harmless: ``content_analysis`` moves from the general MiMo route to the lighter
``deepseek-v4-flash`` used by the narrow conversion tasks, which is a plausible
real experiment rather than a nonsense mutation.
"""

from __future__ import annotations

from backend.config.models import TaskType
from backend.harness.policy import DefaultHarnessPolicy

LIGHT_MODEL = "deepseek-v4-flash"
_LIGHTENED = frozenset({TaskType.CONTENT_ANALYSIS})


class LighterContentAnalysisPolicy(DefaultHarnessPolicy):
    """Default policy, except one task routes to the lighter model."""

    def route_model(self, task_type: TaskType) -> str:
        if task_type in _LIGHTENED:
            return LIGHT_MODEL
        return super().route_model(task_type)


def make_policy() -> LighterContentAnalysisPolicy:
    """The factory the gate's ``--variant module:factory`` syntax expects."""
    return LighterContentAnalysisPolicy()
