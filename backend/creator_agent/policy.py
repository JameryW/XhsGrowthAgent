"""Deterministic publish gating between planning and human confirmation.

P2a-S2.  ``CreatorAdvisor.plan_action`` validates an intent's *shape*; this module
decides whether the intent may become durable at all.  It runs **after** shape
validation and **before** ``create_action``, so a denial leaves no Action Intent
behind -- a policy denial is not something a human should ever be asked to
confirm.

Design constraints (all three are load-bearing):

1. **Deterministic, no LLM.**  The parent task's restraint rule: what a
   deterministic mechanism can decide does not get an Agent.
2. **Fail-closed.**  "Cannot read the input" is a denial, never an allow.  The
   risky direction of this gate is allowing a publish that should have been
   blocked, so every unreadable state resolves to deny.
3. **No service import.**  The engine takes an already-computed
   ``RiskVerdict``; the only place that talks to ``xhs_risk_gate`` is
   ``_risk_gate_publish_verdict``.  That keeps the rule table unit-testable
   without touching global gate state, and keeps the dependency in one function
   instead of spread over the module.

Only **side-effecting** capabilities are gated.  The three non-transactional
capabilities (``compare_options`` / ``save_shortlist`` /
``request_more_evidence``) keep their existing behaviour byte for byte: they
never leave the process, so a publish policy has nothing to say about them.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from backend.creator_agent.models import ActionCapability, ActionIntentRequest


class PolicyId(StrEnum):
    """Stable identifiers for every outcome.  Logged and returned to callers.

    These are part of the observable contract: an operator reading a 403 needs a
    stable string, not a sentence that changes with prose edits.
    """

    ALLOWED = "policy.action.allowed"
    NOT_APPLICABLE = "policy.action.not_applicable"
    ACCOUNT_MISSING = "policy.action.account_missing"
    RISK_COOLDOWN = "policy.action.risk_cooldown"
    RISK_UNAVAILABLE = "policy.action.risk_unavailable"


#: Capabilities that reach outside the process.  Everything else is
#: non-transactional and therefore not gated here.
_SIDE_EFFECTING_CAPABILITIES = frozenset({ActionCapability.PUBLISH})


@dataclass(frozen=True)
class RiskVerdict:
    """The engine's own view of a risk gate -- deliberately not ``GateBlock``.

    ``GateBlock`` lives in ``backend.services``; the engine stays independent of
    it so the rule table can be tested without importing the service, and so the
    engine has no opinion about *which* gate produced the block.
    """

    policy_id: PolicyId
    reason: str
    retry_after_seconds: int | None = None


@dataclass(frozen=True)
class ActionPolicySnapshot:
    """Everything the policy is allowed to look at.

    ``risk`` is ``None`` only when the gate was consulted and returned clear;
    "could not consult" is expressed as ``RiskVerdict(RISK_UNAVAILABLE, ...)``
    rather than as ``None``, because ``None`` already means "clear" and quietly
    folding an unreadable gate into it would turn fail-closed into fail-open.
    """

    capability: ActionCapability
    account_id: str
    risk: RiskVerdict | None = None


@dataclass(frozen=True)
class PolicyVerdict:
    allowed: bool
    policy_id: PolicyId
    reason: str
    retry_after_seconds: int | None = None


class CooldownChecker(Protocol):
    """Boundary to the risk gate; injected so tests never touch global state."""

    def __call__(self, account_id: str) -> RiskVerdict | None: ...


def evaluate_action_policy(snapshot: ActionPolicySnapshot) -> PolicyVerdict:
    """Decide whether an Action Intent may become durable.

    Rule order matters only in that every rule denies; the first denial wins.
    A pure function: same snapshot in, same verdict out.
    """
    if snapshot.capability not in _SIDE_EFFECTING_CAPABILITIES:
        return PolicyVerdict(
            allowed=True,
            policy_id=PolicyId.NOT_APPLICABLE,
            reason="",
        )

    if not snapshot.account_id.strip():
        # Fail-closed: without an account there is nothing to evaluate the
        # publish policy against, and "no account" is not an allow.
        return PolicyVerdict(
            allowed=False,
            policy_id=PolicyId.ACCOUNT_MISSING,
            reason="publish policy requires an account_id",
        )

    if snapshot.risk is not None:
        return PolicyVerdict(
            allowed=False,
            policy_id=snapshot.risk.policy_id,
            reason=snapshot.risk.reason,
            retry_after_seconds=snapshot.risk.retry_after_seconds,
        )

    return PolicyVerdict(allowed=True, policy_id=PolicyId.ALLOWED, reason="")


def build_action_policy_snapshot(
    request: ActionIntentRequest,
    *,
    cooldown_checker: CooldownChecker | None = None,
) -> ActionPolicySnapshot:
    """Collect the snapshot for ``request``.

    ``cooldown_checker`` defaults to the real risk gate; tests inject a fake so
    they exercise the same code path without writing into module-global gate
    state.  (Patching ``xhs_risk_gate`` instead would leave the default path
    itself untested.)
    """
    checker = cooldown_checker or _risk_gate_publish_verdict
    risk = None
    if request.action_kind in _SIDE_EFFECTING_CAPABILITIES:
        risk = _consult_checker(checker, request.account_id.strip())
    return ActionPolicySnapshot(
        capability=request.action_kind,
        account_id=request.account_id,
        risk=risk,
    )


def _consult_checker(checker: CooldownChecker, account_id: str) -> RiskVerdict | None:
    """Fail-closed boundary around *any* checker.

    The guarantee lives here rather than inside ``_risk_gate_publish_verdict``
    on purpose: putting it in the default implementation would mean the
    injectable seam -- the one tests and future callers use -- is *less* safe
    than production, and any alternative checker would silently lose the
    property.  A test that injects a raising checker is what caught the first
    version of this.
    """
    try:
        return checker(account_id)
    except Exception as exc:  # noqa: BLE001 - fail-closed: unreadable gate => deny
        # Deliberately broad.  The checker is consulted for one reason: deciding
        # whether a publish may proceed.  Any failure to answer that question
        # leaves us unable to justify an allow, and allowing a publish that the
        # gate would have blocked is the expensive direction of this mistake.
        # (``CancelledError`` is a ``BaseException`` and still propagates.)
        return RiskVerdict(
            policy_id=PolicyId.RISK_UNAVAILABLE,
            reason=f"publish risk gate could not be read: {type(exc).__name__}",
        )


def _risk_gate_publish_verdict(account_id: str) -> RiskVerdict | None:
    """Ask ``xhs_risk_gate`` whether this account may publish right now.

    Imported here rather than at module level: the gate is a stateful service
    (module-global dicts, a persistence task), and this is the single seam where
    the domain layer touches it.  Late binding also means a test can patch the
    gate itself and the call resolves at call time.
    """
    from backend.services.xhs_risk_gate import check_publish_allowed

    block = check_publish_allowed(account_id=account_id)
    if block is None:
        return None
    return RiskVerdict(
        policy_id=PolicyId.RISK_COOLDOWN,
        reason=block.message,
        retry_after_seconds=block.retry_after_seconds,
    )
