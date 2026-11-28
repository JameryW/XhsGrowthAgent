"""DM quota allocation by causal uplift (ledger scheme #44).

The daily DM quota is hard (``XHS_DM_DAILY_LIMIT``, default 20, enforced by
:func:`backend.services.xhs_risk_gate.check_dm_quota` inside ``send_dm``).  First
come, first served spends it on the wrong people: chatty browsers (lost causes)
and fans who would have converted anyway (sure things) consume the same slot a
hesitant customer needs for the five-slot follow-up.

The classification itself already exists in
:mod:`backend.services.interaction_contracts`
(``DmCandidate`` / ``classify_dm_candidate`` / ``allocate_dm_quota``).  This
module is the adapter that turns what the DM handler can actually observe into a
candidate, plus a small policy layer around the single-message case.

Honesty note: the conversion priors below are **fixed tables**, not measured
rates.  With a handful of notes and ~129 contacts there is nothing to fit, and
a number fitted that early would move every week.  They are inputs to a
*classification* ("is this worth a scarce quota slot now?"), and the module says
so in the report (``priors: "fixed"``) so nobody reads them as a forecast.

Hostility is only judged from text, and text is optional at the call site: when
the caller has no inbound message, evidence is thin and the policy never blocks
— it reports the stratum and sends.  ``evidence_sufficient`` records that
distinction instead of pretending a guess is a measurement.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from backend.services.interaction_contracts import (
    DmAllocation,
    DmCandidate,
    DmStratum,
    allocate_dm_quota,
    classify_dm_candidate,
)

DM_UPLIFT_ENV = "XHS_DM_UPLIFT"
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Fixed priors (see module docstring): base conversion before any DM intervention.
_STAGE_BASE: dict[str, float] = {"new": 0.06, "returning": 0.14, "vip": 0.40}
_DEFAULT_STAGE_BASE = _STAGE_BASE["returning"]
_SLOT_BONUS = 0.04
_INTEREST_BONUS = 0.02
_BASE_CAP = 0.60
_INTERVENTION_WEIGHT = 0.35
_INTERVENTION_FLOOR = 0.02
_INTERVENTION_CAP = 0.98

_STRONG_INTENT_MARKERS: tuple[str, ...] = (
    "多少钱",
    "什么价",
    "价格",
    "押金",
    "怎么定",
    "怎么订",
    "预订",
    "预约",
    "档期",
    "还有车",
    "能租",
    "提车",
    "取车",
    "怎么联系",
    "联系方式",
)
_MEDIUM_INTENT_MARKERS: tuple[str, ...] = (
    "想租",
    "打算",
    "计划",
    "几天",
    "预算",
    "车型",
    "几个人",
    "自驾",
    "路线",
)
_HOSTILE_MARKERS: tuple[str, ...] = (
    "投诉",
    "举报",
    "曝光",
    "骗子",
    "骗人",
    "差评",
    "报警",
    "垃圾",
    "滚",
    "傻",
)

#: Below this many independently observed signals, a block would be a guess.
_MIN_EVIDENCE_SLOTS = 2
_MIN_EVIDENCE_INTERESTS = 2

_PRIORITY: dict[DmStratum, int] = {
    DmStratum.PERSUADABLE: 1,
    DmStratum.SURE_THING: 2,
    DmStratum.LOST_CAUSE: 3,
    DmStratum.SLEEPING_DOG: 4,
}


def dm_uplift_enabled() -> bool:
    """Whether the DM handler should classify before spending quota."""
    return os.environ.get(DM_UPLIFT_ENV, "").strip().lower() in _TRUTHY


@dataclass(frozen=True)
class DmIntake:
    """What the caller can observe about one inbound DM."""

    inbound_message: str = ""
    fan_stage: str = "returning"
    interest_count: int = 0
    qualified_slots: int = 0
    total_slots: int = 5
    has_known_price: bool = False

    @property
    def filled_ratio(self) -> float:
        total = max(1, int(self.total_slots))
        return max(0.0, min(1.0, self.qualified_slots / total))

    @property
    def evidence_sufficient(self) -> bool:
        """Enough independent signals to justify deferring a reply."""
        return bool(self.inbound_message.strip()) or (
            self.qualified_slots >= _MIN_EVIDENCE_SLOTS
            or self.interest_count >= _MIN_EVIDENCE_INTERESTS
        )


@dataclass(frozen=True)
class DmAssessment:
    """One inbound DM, classified for quota spending."""

    intake: DmIntake
    candidate: DmCandidate
    stratum: DmStratum
    action: str
    priority: int
    quota_cost: int
    hostility: str = ""
    evidence_sufficient: bool = False

    @property
    def may_send(self) -> bool:
        """A refused assessment must not open a browser."""
        return self.quota_cost > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "priors": "fixed",
            "stratum": self.stratum.value,
            "action": self.action,
            "priority": self.priority,
            "quota_cost": self.quota_cost,
            "may_send": self.may_send,
            "hostility": self.hostility,
            "evidence_sufficient": self.evidence_sufficient,
            "candidate": self.candidate.as_dict(),
            "signals": {
                "fan_stage": self.intake.fan_stage,
                "interest_count": self.intake.interest_count,
                "qualified_slots": self.intake.qualified_slots,
                "filled_ratio": round(self.intake.filled_ratio, 4),
            },
        }


def detect_hostility(text: str) -> str:
    """The matched hostility marker, or ``""``.

    Deliberately narrow: only explicit accusations/threats.  A frustrated "太贵
    了" is a negotiation, not hostility, and must keep its quota.
    """
    value = (text or "").strip()
    if not value:
        return ""
    for marker in _HOSTILE_MARKERS:
        if marker in value:
            return marker
    return ""


def intent_score(intake: DmIntake) -> float:
    """How clearly the customer is asking to buy, in ``0..1``."""
    text = intake.inbound_message or ""
    strong = sum(1 for marker in _STRONG_INTENT_MARKERS if marker in text)
    medium = sum(1 for marker in _MEDIUM_INTENT_MARKERS if marker in text)
    score = 0.15 * strong + 0.08 * medium
    score += 0.45 * intake.filled_ratio
    score += 0.05 * min(3, max(0, intake.interest_count))
    if intake.has_known_price:
        score += 0.05
    return round(max(0.0, min(1.0, score)), 4)


def base_conversion(intake: DmIntake) -> float:
    """Prior conversion probability with no DM at all."""
    stage = (intake.fan_stage or "").strip().lower()
    base = _STAGE_BASE.get(stage, _DEFAULT_STAGE_BASE)
    base += _SLOT_BONUS * max(0, intake.qualified_slots)
    base += _INTEREST_BONUS * min(3, max(0, intake.interest_count))
    return round(min(_BASE_CAP, base), 4)


def estimate_candidate(intake: DmIntake) -> DmCandidate:
    """Map observable signals onto the contract's ``DmCandidate``."""
    base = base_conversion(intake)
    intent = intent_score(intake)
    gap = max(0.0, intent - base)
    intervention = base + _INTERVENTION_WEIGHT * gap
    # Any reply carries *some* value (a held conversation), so the uplift floor
    # keeps a low-intent fan out of "negative uplift" territory — being chatty is
    # a low-value case, not a harmful one.
    intervention = max(intervention, base + _INTERVENTION_FLOOR)
    return DmCandidate(
        user_id="dm",
        base_conversion=base,
        intervention_conversion=round(min(_INTERVENTION_CAP, intervention), 4),
        intent_score=intent,
        is_hostile=bool(detect_hostility(intake.inbound_message)),
    )


def assess_dm(intake: DmIntake, *, daily_quota: int = 1) -> DmAssessment:
    """Classify one inbound DM and pick the action the contract prescribes."""
    candidate = estimate_candidate(intake)
    allocation = _allocate_one(candidate, daily_quota=daily_quota)
    return DmAssessment(
        intake=intake,
        candidate=candidate,
        stratum=allocation.stratum,
        action=allocation.action,
        priority=_PRIORITY[allocation.stratum],
        quota_cost=allocation.quota_cost,
        hostility=detect_hostility(intake.inbound_message),
        evidence_sufficient=intake.evidence_sufficient,
    )


def assess_batch(intakes: Iterable[DmIntake], *, daily_quota: int) -> list[DmAssessment]:
    """Classify a whole inbox against one shared quota."""
    items = list(intakes)
    candidates = [
        replace(estimate_candidate(intake), user_id=f"dm:{index}")
        for index, intake in enumerate(items)
    ]
    allocations = allocate_dm_quota(candidates, daily_quota=daily_quota)
    # ``allocate_dm_quota`` returns allocations ordered by priority, so map back by
    # the synthetic id instead of assuming positional agreement.
    by_user = {allocation.user_id: allocation for allocation in allocations}
    results: list[DmAssessment] = []
    for index, (intake, candidate) in enumerate(zip(items, candidates, strict=True)):
        allocation = by_user.get(f"dm:{index}")
        if allocation is None:  # pragma: no cover - the contract allocates every candidate
            continue
        results.append(
            DmAssessment(
                intake=intake,
                candidate=candidate,
                stratum=allocation.stratum,
                action=allocation.action,
                priority=_PRIORITY[allocation.stratum],
                quota_cost=allocation.quota_cost,
                hostility=detect_hostility(intake.inbound_message),
                evidence_sufficient=intake.evidence_sufficient,
            )
        )
    return results


def assess_dm_if_enabled(
    *,
    inbound_message: str = "",
    qualification: Any = None,
    fan_stage: str = "returning",
    fan_interests: Sequence[str] | None = None,
    known_prices: Sequence[float] | None = None,
    daily_quota: int = 1,
) -> DmAssessment | None:
    """``assess_dm`` behind ``XHS_DM_UPLIFT``; ``None`` when switched off."""
    if not dm_uplift_enabled():
        return None
    return assess_dm(
        intake_from_context(
            inbound_message=inbound_message,
            qualification=qualification,
            fan_stage=fan_stage,
            fan_interests=fan_interests,
            known_prices=known_prices,
        ),
        daily_quota=daily_quota,
    )


def intake_from_context(
    *,
    inbound_message: str = "",
    qualification: Any = None,
    fan_stage: str = "returning",
    fan_interests: Sequence[str] | None = None,
    known_prices: Sequence[float] | None = None,
) -> DmIntake:
    """Build a ``DmIntake`` from the DM handler's own arguments.

    The slot count comes from the qualification the handler already carries (a
    ``QualificationFSM`` or its ``{slots: {...}}`` mapping); nothing is
    re-extracted from text here, so this cannot disagree with the FSM that gates
    the send.
    """
    values = _slot_values(qualification)
    return DmIntake(
        inbound_message=str(inbound_message or ""),
        fan_stage=str(fan_stage or "returning"),
        interest_count=len(list(fan_interests or ())),
        qualified_slots=sum(1 for value in values if value),
        total_slots=len(values) if len(values) > 5 else 5,
        has_known_price=bool(known_prices),
    )


def _slot_values(qualification: Any) -> list[Any]:
    """Slot values from a qualification FSM instance or its mapping form."""
    if qualification is None:
        return []
    slots = getattr(qualification, "slots", None)
    if isinstance(slots, Mapping):
        return list(slots.values())
    if isinstance(qualification, Mapping):
        raw = qualification.get("slots")
        source = raw if isinstance(raw, Mapping) else qualification
        if isinstance(source, Mapping):
            return list(source.values())
    return []


def _allocate_one(candidate: DmCandidate, *, daily_quota: int) -> DmAllocation:
    """Allocate a single candidate; a ``quota<=0`` still yields its stratum."""
    allocations = allocate_dm_quota([candidate], daily_quota=max(1, int(daily_quota)))
    return allocations[0]


__all__ = [
    "DM_UPLIFT_ENV",
    "DmAssessment",
    "DmIntake",
    "assess_batch",
    "assess_dm",
    "assess_dm_if_enabled",
    "base_conversion",
    "classify_dm_candidate",
    "detect_hostility",
    "dm_uplift_enabled",
    "estimate_candidate",
    "intake_from_context",
    "intent_score",
]
