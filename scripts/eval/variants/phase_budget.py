"""A sample A/B variant: one decision changed — the publishing-phase budget.

Before #756 this example routed ``content_analysis`` to a lighter direct model.
That is no longer a meaningful demo: every task now egresses through the magpie
gateway to the same upstream (``magpie-deepseek-v4.1-flash``) and direct DeepSeek
is disabled.  A per-phase context budget is still a real harness decision, and E2
samples ``context_budget(phase=...)`` for every WorkflowPhase, so this variant
shows up as exactly one diff entry (``context_budgets``) and nothing else.

Run it through the gate::

    python scripts/eval/run_gate.py --skip-benchmarks \
        --variant scripts.eval.variants.phase_budget:make_policy

It is never imported by production code, so it cannot change a default.
"""

from __future__ import annotations

from backend.harness.policy import DefaultHarnessPolicy

PUBLISHING_BUDGET = 4000


class PublishingBudgetPolicy(DefaultHarnessPolicy):
    """Default policy, except the publishing phase caps its context budget."""

    def context_budget(self, *, phase: str = "") -> int | None:
        if phase == "publishing":
            return PUBLISHING_BUDGET
        return super().context_budget(phase=phase)


def make_policy() -> PublishingBudgetPolicy:
    """The factory the gate's ``--variant module:factory`` syntax expects."""
    return PublishingBudgetPolicy()
