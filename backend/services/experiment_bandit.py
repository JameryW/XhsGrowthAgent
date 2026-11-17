"""Sliding-window bandit ranking for the weekly A/B review.

The existing ``ab_test_manager`` tool only records a configuration.  This
module adds the decision half: given recent variant observations, rank arms by
an upper confidence bound and a Wilson lower bound, then name a canary arm for
the next review window.

It is deliberately small and pure.  The weekly loop still asks a human to
approve the canary; nothing here promotes a policy automatically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

DEFAULT_WINDOW = 30
DEFAULT_MIN_IMPRESSIONS = 20
DEFAULT_CANARY_FRACTION = 0.2
DEFAULT_EXPLORATION = 1.0


def wilson_lower_bound(successes: float, trials: float, *, z: float = 1.96) -> float:
    """Wilson score interval lower bound for a binomial proportion."""
    if trials <= 0:
        return 0.0
    p = max(0.0, min(1.0, successes / trials))
    z2 = z * z
    denominator = 1.0 + z2 / trials
    centre = p + z2 / (2.0 * trials)
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * trials)) / trials)
    return max(0.0, (centre - margin) / denominator)


def ucb_score(
    successes: float,
    trials: float,
    total_trials: float,
    *,
    exploration: float = DEFAULT_EXPLORATION,
) -> float:
    """Smoothed UCB1: an unobserved arm is optimistic, not NaN."""
    if trials <= 0:
        return 1.0 + exploration
    mean = successes / trials
    bonus = exploration * math.sqrt(2.0 * math.log(max(2.0, total_trials)) / trials)
    return mean + bonus


@dataclass(frozen=True)
class ArmStats:
    variant_id: str
    impressions: int
    conversions: int
    rate: float
    ucb: float
    wilson_lower: float
    eligible: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "variant_id": self.variant_id,
            "impressions": self.impressions,
            "conversions": self.conversions,
            "rate": round(self.rate, 4),
            "ucb": round(self.ucb, 4),
            "wilson_lower": round(self.wilson_lower, 4),
            "eligible": self.eligible,
        }


@dataclass
class BanditDecision:
    arms: list[ArmStats] = field(default_factory=list)
    leader: str = ""
    canary_variant: str = ""
    canary_fraction: float = DEFAULT_CANARY_FRACTION
    confidence: float = 0.0
    status: str = "insufficient_data"
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "leader": self.leader,
            "canary_variant": self.canary_variant,
            "canary_fraction": self.canary_fraction,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "arms": [arm.as_dict() for arm in self.arms],
        }


@dataclass(frozen=True)
class SequentialStep:
    """One step of a sequential A/B schedule.

    Exploration is strictly one arm at a time: every variant must reach the
    minimum impression count before the bandit may exploit a leader.  This
    avoids the fixed-split failure mode where a promising arm is starved by an
    early random allocation.
    """

    action: str
    variant_id: str
    reason: str
    impressions: int
    min_impressions: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "variant_id": self.variant_id,
            "reason": self.reason,
            "impressions": self.impressions,
            "min_impressions": self.min_impressions,
        }


def rank_arms(
    observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    *,
    window: int = DEFAULT_WINDOW,
    min_impressions: int = DEFAULT_MIN_IMPRESSIONS,
    canary_fraction: float = DEFAULT_CANARY_FRACTION,
) -> BanditDecision:
    """Aggregate the most recent observations and choose a canary arm.

    Each observation is ``{variant_id, impressions, conversions}``.  A
    variant's counts are summed over the last ``window`` observations; only
    arms with at least ``min_impressions`` are eligible to lead.  The canary
    is the eligible leader, and the control is every other arm.  With fewer
    than two eligible arms there is not enough evidence to promote anything.
    """
    if not observations:
        return BanditDecision(reason="no_observations")

    recent = list(observations)[-max(1, window) :]
    totals: dict[str, list[float]] = {}
    for row in recent:
        if not isinstance(row, dict):
            continue
        variant = str(row.get("variant_id") or "").strip()
        if not variant:
            continue
        impressions = max(0.0, float(row.get("impressions") or 0))
        conversions = max(0.0, float(row.get("conversions") or 0))
        if conversions > impressions:
            conversions = impressions
        bucket = totals.setdefault(variant, [0.0, 0.0])
        bucket[0] += impressions
        bucket[1] += conversions

    total_trials = sum(bucket[0] for bucket in totals.values())
    arms: list[ArmStats] = []
    for variant, (impressions, conversions) in totals.items():
        rate = conversions / impressions if impressions > 0 else 0.0
        arms.append(
            ArmStats(
                variant_id=variant,
                impressions=int(impressions),
                conversions=int(conversions),
                rate=rate,
                ucb=ucb_score(conversions, impressions, total_trials),
                wilson_lower=wilson_lower_bound(conversions, impressions),
                eligible=impressions >= min_impressions,
            )
        )
    arms.sort(key=lambda arm: (-arm.ucb, -arm.wilson_lower, arm.variant_id))
    eligible = [arm for arm in arms if arm.eligible]
    if len(eligible) < 2:
        return BanditDecision(
            arms=arms,
            status="insufficient_data",
            reason="need_two_arms_with_min_impressions",
            canary_fraction=canary_fraction,
        )

    leader = eligible[0]
    runner_up = eligible[1]
    confidence = max(0.0, leader.ucb - runner_up.ucb)
    return BanditDecision(
        arms=arms,
        leader=leader.variant_id,
        canary_variant=leader.variant_id,
        canary_fraction=canary_fraction,
        confidence=confidence,
        status="ready_for_canary",
        reason="leader_selected_by_ucb",
    )


def sequential_plan(
    variant_ids: list[str] | tuple[str, ...],
    observations: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
    *,
    window: int = DEFAULT_WINDOW,
    min_impressions: int = DEFAULT_MIN_IMPRESSIONS,
) -> dict[str, Any]:
    """Return the next arm a sequential A/B run should expose.

    Every variant is explored until it has ``min_impressions`` observations;
    only then does the bandit exploit its UCB leader.  The caller still owns
    allocation and publication -- this function only names the next arm.
    """
    variants: list[str] = []
    for raw in variant_ids:
        variant = str(raw or "").strip()
        if variant and variant not in variants:
            variants.append(variant)
    if not variants:
        step = SequentialStep("stop", "", "no_variants", 0, min_impressions)
        return {**step.as_dict(), "decision": None}

    recent = list(observations or [])[-max(1, window) :]
    impressions: dict[str, int] = dict.fromkeys(variants, 0)
    valid_rows: list[dict[str, Any]] = []
    for row in recent:
        if not isinstance(row, dict):
            continue
        variant = str(row.get("variant_id") or "").strip()
        if variant not in impressions:
            continue
        valid_rows.append(row)
        impressions[variant] += max(0, int(row.get("impressions") or 0))

    decision = rank_arms(valid_rows, window=window, min_impressions=min_impressions)
    underexplored = [
        (impressions[variant], index, variant)
        for index, variant in enumerate(variants)
        if impressions[variant] < min_impressions
    ]
    if underexplored:
        count, _, variant = min(underexplored)
        step = SequentialStep(
            "explore",
            variant,
            "variant_needs_more_impressions",
            count,
            min_impressions,
        )
    elif decision.status == "ready_for_canary" and decision.leader:
        step = SequentialStep(
            "exploit",
            decision.leader,
            "ucb_leader_after_exploration",
            impressions[decision.leader],
            min_impressions,
        )
    else:
        step = SequentialStep(
            "stop",
            "",
            decision.reason or "insufficient_evidence",
            0,
            min_impressions,
        )
    return {**step.as_dict(), "decision": decision.as_dict()}


__all__ = [
    "DEFAULT_CANARY_FRACTION",
    "DEFAULT_MIN_IMPRESSIONS",
    "DEFAULT_WINDOW",
    "ArmStats",
    "BanditDecision",
    "SequentialStep",
    "rank_arms",
    "sequential_plan",
    "ucb_score",
    "wilson_lower_bound",
]
