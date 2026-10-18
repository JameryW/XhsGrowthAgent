"""Verification trigger policy (P1-B) — when is verification worth its cost?

The design note's rule: verify when the expected loss avoided exceeds the
cost of verifying, ``p_e · p_d · L > C_v`` — with a floor for high-risk
actions that bypasses the arithmetic entirely. Two things this module refuses
to do:

1. **Never verify everything.** An LLM verifier on every step is the expensive
   way to feel safe; the formula exists to say "not worth it" out loud.
2. **Never let a budget shortfall silently drop a mandatory check.** When the
   remaining budget cannot pay for the chosen tier, the decision degrades to
   the cheapest tier that still checks something (deterministic), and says so
   — it does not become "skip".

Honest limits (by design, not accident):

- ``expected_error_prob`` / ``detection_prob`` are *inputs*. There is no
  calibrated estimator in the repo yet; callers pass priors (or measured
  rates once an eval set exists). Treating a model's self-reported confidence
  as a probability is exactly what the design note warns against.
- No LLM verifier exists in this repo today. The ``LLM`` tier is a decision
  slot that maps onto the existing gates for now; wiring an actual verifier
  is a separate change with its own evaluation bar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

__all__ = [
    "VERIFICATION_EVENT_KIND",
    "ActionRisk",
    "VerificationDecision",
    "VerificationInput",
    "VerificationTier",
    "decide",
    "verification_event",
]

#: Event kind for an emitted decision (registered in
#: ``backend.db.workflow_events.EVENT_KINDS``).
VERIFICATION_EVENT_KIND = "verification"


class ActionRisk(StrEnum):
    """How much damage a wrong action can do."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    """Irreversible external effect (a real publish, a payment)."""


class VerificationTier(StrEnum):
    """Cheapest sufficient check, in ascending cost."""

    NONE = "none"
    DETERMINISTIC = "deterministic"
    """Rules, schema checks, policy gates — no model call."""

    LLM = "llm"
    """A separate model reviews the action (not the actor's own opinion)."""

    HUMAN = "human"


#: Risk floor: an action at this level is verified regardless of the
#: arithmetic. The design note is explicit — for high-risk operations, a low
#: estimated error probability must not buy a pass.
_RISK_FLOOR: dict[ActionRisk, VerificationTier] = {
    ActionRisk.CRITICAL: VerificationTier.HUMAN,
    ActionRisk.HIGH: VerificationTier.DETERMINISTIC,
    ActionRisk.MEDIUM: VerificationTier.NONE,
    ActionRisk.LOW: VerificationTier.NONE,
}


@dataclass(frozen=True)
class VerificationInput:
    """Everything the decision needs, explicit and inspectable.

    Defaults are conservative priors, not measurements: 10% error probability,
    80% detection, unit loss, 0.2 unit verify cost. A caller with better data
    should pass it — the defaults exist so a forgotten parameter degrades to
    "verify" rather than "skip".
    """

    action: str
    risk: ActionRisk
    expected_error_prob: float = 0.1
    detection_prob: float = 0.8
    loss: float = 1.0
    verify_cost: float = 0.2
    budget_remaining: float | None = None
    dry_run: bool = False

    def __post_init__(self) -> None:
        for name in ("expected_error_prob", "detection_prob"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name} must be in [0, 1], got {value}")
        for name in ("loss", "verify_cost"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} must be >= 0")


@dataclass(frozen=True)
class VerificationDecision:
    required: bool
    tier: VerificationTier
    reason: str
    expected_benefit: float
    """``p_e·p_d·L − C_v``. Negative means verifying costs more than it saves."""

    def to_event(self, *, action: str, account_id: str = "", thread_id: str = "") -> dict[str, Any]:
        return verification_event(self, action=action, account_id=account_id, thread_id=thread_id)


def decide(inp: VerificationInput) -> VerificationDecision:
    """Decide whether (and how expensively) to verify one action.

    Order matters:

    1. Dry runs are rehearsals — nothing reaches the outside world, so there
       is nothing worth verifying.
    2. The risk floor: CRITICAL is always HUMAN; HIGH is at least
       DETERMINISTIC. This is checked before the arithmetic so a confident
       caller cannot talk the system out of a mandatory gate.
    3. Budget: when the remaining budget cannot pay the chosen tier's cost,
       degrade to the cheapest tier that still checks (deterministic) and
       report ``budget_exhausted`` — never silently skip a floored check.
    4. The expected-value rule: verify only when the avoided loss exceeds the
       cost.
    """
    benefit = inp.expected_error_prob * inp.detection_prob * inp.loss - inp.verify_cost

    if inp.dry_run:
        return VerificationDecision(
            required=False,
            tier=VerificationTier.NONE,
            reason="dry_run",
            expected_benefit=benefit,
        )

    floor = _RISK_FLOOR[inp.risk]
    if floor is VerificationTier.HUMAN:
        return VerificationDecision(
            required=True,
            tier=VerificationTier.HUMAN,
            reason="critical_risk_floor",
            expected_benefit=benefit,
        )

    if inp.budget_remaining is not None and inp.verify_cost > inp.budget_remaining:
        tier = (
            VerificationTier.DETERMINISTIC
            if floor is not VerificationTier.NONE
            else VerificationTier.NONE
        )
        return VerificationDecision(
            required=tier is not VerificationTier.NONE,
            tier=tier,
            reason="budget_exhausted",
            expected_benefit=benefit,
        )

    if benefit > 0:
        # MEDIUM+ is where an independent reviewer earns its cost; below that
        # deterministic rules are the proportionate check.
        tier = (
            VerificationTier.LLM
            if inp.risk in (ActionRisk.MEDIUM, ActionRisk.HIGH)
            else VerificationTier.DETERMINISTIC
        )
        if _tier_rank(floor) > _tier_rank(tier):
            tier = floor
        return VerificationDecision(
            required=True,
            tier=tier,
            reason="expected_loss_exceeds_cost",
            expected_benefit=benefit,
        )

    # Not worth it — but a HIGH-risk action still keeps its deterministic
    # floor; the arithmetic only ever raises the tier, never lowers the floor.
    if floor is not VerificationTier.NONE:
        return VerificationDecision(
            required=True,
            tier=floor,
            reason="risk_floor_kept",
            expected_benefit=benefit,
        )
    return VerificationDecision(
        required=False,
        tier=VerificationTier.NONE,
        reason="below_threshold",
        expected_benefit=benefit,
    )


def _tier_rank(tier: VerificationTier) -> int:
    return {
        VerificationTier.NONE: 0,
        VerificationTier.DETERMINISTIC: 1,
        VerificationTier.LLM: 2,
        VerificationTier.HUMAN: 3,
    }[tier]


def verification_event(
    decision: VerificationDecision,
    *,
    action: str,
    account_id: str = "",
    thread_id: str = "",
) -> dict[str, Any]:
    """Render a decision as an Event-store entry (reserved keys last).

    Emitted on the real publish path so an operator can see *why* a run went
    through a gate instead of inferring it from the gate's presence.
    """
    entry: dict[str, Any] = {
        "action": action,
        "required": decision.required,
        "tier": decision.tier.value,
        "reason": decision.reason,
        "expected_benefit": round(decision.expected_benefit, 6),
        "kind": VERIFICATION_EVENT_KIND,
        "account_id": account_id,
        "thread_id": thread_id,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    return entry
