"""Outcome-Verified Epistemic Gate for hy-memory working experiences.

A post-mortem insight is only allowed to become a long-lived ``verified_pattern``
when the note that produced it actually beat the account's recent baseline:
collect rate *or* views must be at least ``1.2x`` the median of the last ten
notes, or a human must have explicitly approved it as a learning signal.

Everything else is still recorded — but as a ``negative_pitfall`` (what not to
repeat), never as a positive pattern. This keeps the working store from turning
one lucky (or one bad) post into a durable rule, the failure mode documented by
MemCredit/DISCERN (most recalled memories have zero marginal utility).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import median
from typing import Any

__all__ = [
    "DEFAULT_BASELINE_SAMPLES",
    "DEFAULT_OUTPERFORM_RATIO",
    "NEGATIVE_PITFALL",
    "VERIFIED_PATTERN",
    "OutcomeGateResult",
    "evaluate_outcome_gate",
    "memory_metadata",
]

DEFAULT_BASELINE_SAMPLES = 10
DEFAULT_OUTPERFORM_RATIO = 1.2

VERIFIED_PATTERN = "verified_pattern"
NEGATIVE_PITFALL = "negative_pitfalls"


def _metric(record: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        value = record.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                continue
    return 0.0


def _collects(record: Mapping[str, Any]) -> float:
    return _metric(record, "collects", "bookmarks", "collect")


def _views(record: Mapping[str, Any]) -> float:
    return _metric(record, "views", "impressions", "reads", "read")


def _collect_rate(record: Mapping[str, Any]) -> float:
    views = _views(record)
    return _collects(record) / views if views > 0 else 0.0


def _median(values: Sequence[float]) -> float:
    return float(median(values)) if values else 0.0


def _ratio(value: float, baseline: float) -> float | None:
    if baseline <= 0:
        return None
    return round(value / baseline, 4)


def _usable_history(
    history: Sequence[Mapping[str, Any]], *, exclude_post_id: str = ""
) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for record in history:
        if not isinstance(record, Mapping):
            continue
        if exclude_post_id and str(record.get("post_id", "")) == exclude_post_id:
            continue
        # A row with neither views nor collects carries no outcome evidence.
        if _views(record) <= 0 and _collects(record) <= 0:
            continue
        rows.append(record)
    return rows


@dataclass(frozen=True)
class OutcomeGateResult:
    """The gate's verdict plus the evidence that produced it."""

    allowed: bool
    verdict: str
    reason: str
    sample_size: int
    collect_rate: float
    median_collect_rate: float
    collect_ratio: float | None
    views: float
    median_views: float
    view_ratio: float | None
    human_approved: bool = False

    @property
    def pool(self) -> str:
        return VERIFIED_PATTERN if self.allowed else NEGATIVE_PITFALL

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "verdict": self.verdict,
            "reason": self.reason,
            "sample_size": self.sample_size,
            "collect_rate": self.collect_rate,
            "median_collect_rate": self.median_collect_rate,
            "collect_ratio": self.collect_ratio,
            "views": self.views,
            "median_views": self.median_views,
            "view_ratio": self.view_ratio,
            "human_approved": self.human_approved,
        }


def evaluate_outcome_gate(
    current: Mapping[str, Any],
    history: Sequence[Mapping[str, Any]] = (),
    *,
    human_approved: bool = False,
    ratio: float = DEFAULT_OUTPERFORM_RATIO,
    baseline_samples: int = DEFAULT_BASELINE_SAMPLES,
) -> OutcomeGateResult:
    """Decide whether one note is strong enough to promote its lesson.

    ``history`` is the account's recent content-history rows (newest first or
    any order; the median is order-independent). ``human_approved`` bypasses
    the measured check for a reviewer's explicit "learn this" decision.
    """
    if ratio <= 0:
        raise ValueError("ratio must be positive")
    if baseline_samples <= 0:
        raise ValueError("baseline_samples must be positive")

    exclude_post_id = str(current.get("post_id", "") or "")
    usable = _usable_history(history, exclude_post_id=exclude_post_id)[:baseline_samples]
    view_values = [_views(row) for row in usable]
    rate_values = [_collect_rate(row) for row in usable if _views(row) > 0]
    median_views = _median(view_values)
    median_rate = _median(rate_values)

    views = _views(current)
    collect_rate = _collect_rate(current)
    collect_ratio = _ratio(collect_rate, median_rate)
    view_ratio = _ratio(views, median_views)

    if human_approved:
        return OutcomeGateResult(
            allowed=True,
            verdict=VERIFIED_PATTERN,
            reason="human_approved",
            sample_size=len(usable),
            collect_rate=round(collect_rate, 6),
            median_collect_rate=round(median_rate, 6),
            collect_ratio=collect_ratio,
            views=views,
            median_views=median_views,
            view_ratio=view_ratio,
            human_approved=True,
        )

    if not usable:
        return OutcomeGateResult(
            allowed=False,
            verdict=NEGATIVE_PITFALL,
            reason="insufficient_history",
            sample_size=0,
            collect_rate=round(collect_rate, 6),
            median_collect_rate=round(median_rate, 6),
            collect_ratio=None,
            views=views,
            median_views=0.0,
            view_ratio=None,
        )

    beats_collects = collect_ratio is not None and collect_ratio >= ratio
    beats_views = view_ratio is not None and view_ratio >= ratio
    if beats_collects or beats_views:
        reason = "collect_rate_outperforms" if beats_collects else "views_outperform"
        return OutcomeGateResult(
            allowed=True,
            verdict=VERIFIED_PATTERN,
            reason=reason,
            sample_size=len(usable),
            collect_rate=round(collect_rate, 6),
            median_collect_rate=round(median_rate, 6),
            collect_ratio=collect_ratio,
            views=views,
            median_views=median_views,
            view_ratio=view_ratio,
        )

    return OutcomeGateResult(
        allowed=False,
        verdict=NEGATIVE_PITFALL,
        reason="below_baseline",
        sample_size=len(usable),
        collect_rate=round(collect_rate, 6),
        median_collect_rate=round(median_rate, 6),
        collect_ratio=collect_ratio,
        views=views,
        median_views=median_views,
        view_ratio=view_ratio,
    )


def memory_metadata(result: OutcomeGateResult) -> dict[str, Any]:
    """Metadata to attach to a hy working write so the pool is auditable."""
    return {
        "verification": result.verdict,
        "memory_pool": result.pool,
        "outcome_gate": result.as_dict(),
    }
