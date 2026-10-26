"""Load plan-time ``ActionPolicyContext`` from a workflow thread checkpoint.

Production ``plan_action(publish)`` auto-loads a stamped
``evaluation_result.publish_eligibility`` (plus account-level fields for
``PLAN_TIME_JUDGERS``) via ``graph.aget_state``.  This module never reads
artifacts — body judgers stay on the execute path.
"""

from __future__ import annotations

from collections.abc import Awaitable, Mapping
from typing import Any, Protocol

from backend.creator_agent.policy import ActionPolicyContext

__all__ = [
    "EligibilityContextUnavailableError",
    "PolicyContextLoader",
    "load_action_policy_context_from_thread",
    "thread_policy_context_loader",
]


class EligibilityContextUnavailableError(Exception):
    """Checkpoint / graph could not be consulted for plan-time eligibility.

    Fail-closed: the plan path must not allow a publish when it cannot read the
    stamped audit that might already forbid it.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class PolicyContextLoader(Protocol):
    """Injectable seam for ``CreatorAdvisor.plan_action`` auto-load."""

    def __call__(self, thread_id: str, account_id: str = "") -> Awaitable[ActionPolicyContext]: ...


def _checkpoint_values(snapshot: Any) -> Mapping[str, Any]:
    """Extract state values from a LangGraph ``StateSnapshot``.

    Empty / missing values are treated as unreadable (fail-closed), not as a
    missing stamp — a publish plan that names a thread must be able to consult
    that thread's checkpoint.
    """
    if snapshot is None:
        raise EligibilityContextUnavailableError("workflow checkpoint snapshot is missing")
    values = getattr(snapshot, "values", None)
    if not isinstance(values, Mapping) or not values:
        raise EligibilityContextUnavailableError("workflow checkpoint has no readable values")
    return values


def _niche_from_values(values: Mapping[str, Any]) -> str:
    niche = str(values.get("niche") or "").strip()
    if niche:
        return niche
    plan = values.get("content_plan")
    if isinstance(plan, Mapping):
        return str(plan.get("niche") or "").strip()
    return ""


def _auto_publish_from_values(values: Mapping[str, Any]) -> bool:
    if values.get("auto_publish") is True:
        return True
    options = values.get("publish_options")
    return bool(isinstance(options, Mapping) and options.get("auto_publish") is True)


def _extra_from_values(values: Mapping[str, Any]) -> dict[str, Any] | None:
    """Carry plan-time signals ``PLAN_TIME_JUDGERS`` may need (no body)."""
    extra: dict[str, Any] = {}
    for key in ("human_feedback", "publish_confirmation", "publish_options"):
        raw = values.get(key)
        if raw is not None:
            extra[key] = raw
    return extra or None


def _stamped_eligibility(values: Mapping[str, Any]) -> dict[str, Any] | None:
    evaluation = values.get("evaluation_result")
    if not isinstance(evaluation, Mapping):
        return None
    stamped = evaluation.get("publish_eligibility")
    if not isinstance(stamped, Mapping):
        return None
    return dict(stamped)


async def load_action_policy_context_from_thread(
    thread_id: str,
    account_id: str = "",
    *,
    graph: Any,
) -> ActionPolicyContext:
    """Build plan-time policy context from a workflow checkpoint.

    * Missing ``publish_eligibility`` → ``publish_eligibility=None`` (not a deny).
    * Graph / ``aget_state`` failure / empty checkpoint →
      :class:`EligibilityContextUnavailableError` (fail-closed).

    ``account_id`` is accepted for call-site symmetry; ownership is enforced by
    the HTTP layer before plan.  This loader does not read artifacts.
    """
    del account_id  # reserved for future account/thread consistency checks
    tid = (thread_id or "").strip()
    if not tid:
        raise EligibilityContextUnavailableError(
            "thread_id is required to load eligibility context"
        )
    if graph is None:
        raise EligibilityContextUnavailableError("workflow graph is unavailable")

    try:
        snapshot = await graph.aget_state({"configurable": {"thread_id": tid}})
    except Exception as exc:  # noqa: BLE001 - fail-closed boundary
        raise EligibilityContextUnavailableError(
            f"workflow checkpoint could not be read: {type(exc).__name__}"
        ) from exc

    values = _checkpoint_values(snapshot)
    # Use the shared commercial detector (mode_spec / brief), never bare
    # ``state.get("is_commercial")`` alone — same contract as judgers.
    from backend.services.compliance_policy import state_is_commercial

    return ActionPolicyContext(
        publish_eligibility=_stamped_eligibility(values),
        niche=_niche_from_values(values),
        auto_publish=_auto_publish_from_values(values),
        is_commercial=state_is_commercial(dict(values)),
        extra=_extra_from_values(values),
    )


def thread_policy_context_loader(graph: Any) -> PolicyContextLoader:
    """Bind a compiled graph into a :class:`PolicyContextLoader` callable."""

    async def _load(thread_id: str, account_id: str = "") -> ActionPolicyContext:
        return await load_action_policy_context_from_thread(thread_id, account_id, graph=graph)

    return _load
