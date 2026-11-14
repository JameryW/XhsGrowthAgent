"""Fake harness policies shared by the wiring tests.

The module lives in the test tree on purpose: the env-loading test resolves
``XHS_HARNESS_POLICY`` as ``tests.unit.harness._fake_policies:env_policy``, i.e.
through the exact ``importlib`` path production uses.  Anything only one test
needs is defined next to that test instead.
"""

from __future__ import annotations

from backend.config.models import TaskType
from backend.harness.policy import DefaultHarnessPolicy, ToolLimits


class EnvVariantPolicy(DefaultHarnessPolicy):
    """A visibly non-default policy for environment-loading tests."""

    def route_model(self, task_type: TaskType) -> str:
        return "magpie-pdf-ocr"

    def context_budget(self, *, phase: str = "") -> int | None:
        return 18 if phase == "publishing" else None

    def tool_limits(self, capability: str) -> ToolLimits:
        return ToolLimits(capability=capability, max_concurrency=None, timeout_s=0.01)


def env_policy() -> EnvVariantPolicy:
    """Zero-arg factory reached through ``module:factory``."""
    return EnvVariantPolicy()


ENV_POLICY_INSTANCE = EnvVariantPolicy()
"""Module-level policy instance: also a valid (non-callable) spec target."""
