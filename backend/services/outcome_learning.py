"""Age-calibrated outcome learning for creator-centre notes.

The creator statistics surface reports cumulative counters, not the ten
interaction snapshots the free-mode analytics route keeps.  A note that is
only a few hours old is therefore *not comparable* with a mature note: early
feed impressions can inflate raw views while long-tail search collects have
not started yet.  This module turns the cumulative rows into an explicit,
deterministic signal:

* notes younger than ``MIN_NOTE_AGE_HOURS`` are reported but excluded;
* each mature note is scored by ``log1p(collects)`` relative to the account's
  recent median, i.e. a collect-first advantage rather than a raw view delta;
* the result states whether there is enough mature history to promote a
  learning signal at all (at least three mature notes and a positive mean
  advantage).

It is intentionally a pure function.  Persistence, Creator-Agent proposals
and UI copy stay in their existing layers; they can consume
:func:`evaluate_outcome_learning` without importing browser or storage code.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from statistics import median
from typing import Any

MIN_NOTE_AGE_HOURS = 48.0
DEFAULT_BASELINE_WINDOW = 10
MIN_MATURE_NOTES_FOR_PROMOTION = 3
# EGMF: a note with almost no credible exposure must not promote a learning
# signal, even when it has technically crossed the age gate.
MIN_CREDIBILITY_FOR_PROMOTION = 0.35


def _parse_datetime(value: str | datetime | None) -> datetime | None:
    """Parse the ISO-ish timestamps creator statistics persists.

    Naive values are interpreted as UTC.  Unknown/garbage values return
    ``None`` so a single bad row cannot poison the whole account analysis.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value.strip():
        text = value.strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _rank(values: list[float]) -> list[float]:
    """Average ranks for ties (1-based), the standard Spearman input."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman_rank_correlation(xs: list[float], ys: list[float]) -> float | None:
    """Spearman rho with tie-aware ranks; ``None`` when it is undefined."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rx, ry = _rank(xs), _rank(ys)
    n = len(rx)
    mean_x = sum(rx) / n
    mean_y = sum(ry) / n
    cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(rx, ry, strict=True))
    var_x = sum((a - mean_x) ** 2 for a in rx)
    var_y = sum((b - mean_y) ** 2 for b in ry)
    if var_x <= 0 or var_y <= 0:
        return None
    return round(cov / math.sqrt(var_x * var_y), 4)


@dataclass(frozen=True)
class NoteOutcome:
    """One note's maturity and collect-first advantage."""

    note_id: str
    views: int
    collects: int
    age_hours: float | None
    eligible: bool
    log_collects: float
    collect_rate: float
    collect_advantage: float
    credibility: float = 1.0
    suspected_throttle: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "note_id": self.note_id,
            "views": self.views,
            "collects": self.collects,
            "age_hours": None if self.age_hours is None else round(self.age_hours, 2),
            "eligible": self.eligible,
            "log_collects": round(self.log_collects, 4),
            "collect_rate": round(self.collect_rate, 4),
            "collect_advantage": round(self.collect_advantage, 4),
            "credibility": round(self.credibility, 4),
            "suspected_throttle": self.suspected_throttle,
        }


@dataclass
class OutcomeLearning:
    """Account-level outcome report consumed by analysis and Creator Agent."""

    mature: bool
    promotable: bool
    mature_count: int
    total_count: int
    baseline_log_collects: float
    mean_collect_advantage: float
    best_note_id: str
    min_age_hours: float
    notes: list[NoteOutcome] = field(default_factory=list)
    reason: str = ""
    suppressed_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "mature": self.mature,
            "promotable": self.promotable,
            "mature_count": self.mature_count,
            "total_count": self.total_count,
            "suppressed_count": self.suppressed_count,
            "baseline_log_collects": round(self.baseline_log_collects, 4),
            "mean_collect_advantage": round(self.mean_collect_advantage, 4),
            "best_note_id": self.best_note_id,
            "min_age_hours": self.min_age_hours,
            "reason": self.reason,
            "notes": [note.as_dict() for note in self.notes],
        }


def evaluate_outcome_learning(
    notes: Iterable[Any] | None,
    *,
    now: datetime | None = None,
    min_age_hours: float = MIN_NOTE_AGE_HOURS,
    baseline_window: int = DEFAULT_BASELINE_WINDOW,
    credibility_by_note: Mapping[str, float] | None = None,
    suspected_throttle_notes: Iterable[str] = (),
) -> OutcomeLearning:
    """Build an age-gated, collect-first outcome report.

    ``notes`` accepts :class:`backend.services.creator_stats.types.NoteStats`
    objects or plain mappings, so callers at the storage seam do not need to
    import the DTO.  The most recent ``baseline_window`` mature notes define
    the baseline; including older notes would let a historical viral post
    hide this week's regression.
    """
    rows = list(notes or ())
    current = now or datetime.now(UTC)
    credibility_map = {
        str(note_id): max(0.0, min(1.0, float(value)))
        for note_id, value in (credibility_by_note or {}).items()
    }
    throttled_ids = {str(note_id) for note_id in suspected_throttle_notes}
    parsed: list[tuple[str, int, int, float | None]] = []
    for row in rows:
        if isinstance(row, dict):
            note_id = str(row.get("note_id") or row.get("id") or "")
            views = int(row.get("views") or 0)
            collects = int(row.get("collects") or 0)
            published = row.get("published_at") or row.get("publish_time")
        else:
            note_id = str(getattr(row, "note_id", "") or "")
            views = int(getattr(row, "views", 0) or 0)
            collects = int(getattr(row, "collects", 0) or 0)
            published = getattr(row, "published_at", None)
        if not note_id:
            continue
        published_dt = _parse_datetime(published)
        age_hours = (
            None
            if published_dt is None
            else max(0.0, (current - published_dt).total_seconds() / 3600.0)
        )
        parsed.append((note_id, views, collects, age_hours))

    if not parsed:
        return OutcomeLearning(
            mature=False,
            promotable=False,
            mature_count=0,
            total_count=0,
            baseline_log_collects=0.0,
            mean_collect_advantage=0.0,
            best_note_id="",
            min_age_hours=min_age_hours,
            reason="no_notes",
        )

    mature_rows = [row for row in parsed if row[3] is not None and row[3] >= min_age_hours]
    # Immature rows are kept in the report as explicit *not yet* evidence.
    if not mature_rows:
        outcomes = [
            NoteOutcome(
                note_id=note_id,
                views=views,
                collects=collects,
                age_hours=age,
                eligible=False,
                log_collects=math.log1p(max(0, collects)),
                collect_rate=(collects / views) if views > 0 else 0.0,
                collect_advantage=0.0,
            )
            for note_id, views, collects, age in parsed
        ]
        return OutcomeLearning(
            mature=False,
            promotable=False,
            mature_count=0,
            total_count=len(parsed),
            baseline_log_collects=0.0,
            mean_collect_advantage=0.0,
            best_note_id="",
            min_age_hours=min_age_hours,
            notes=outcomes,
            reason="no_mature_notes",
        )

    # Newest mature notes first; the baseline is the recent window, not the
    # oldest posts in the account's history.
    mature_rows.sort(key=lambda row: row[3] or 0.0)
    eligible_rows = [
        row
        for row in mature_rows
        if row[0] not in throttled_ids
        and credibility_map.get(row[0], 1.0) >= MIN_CREDIBILITY_FOR_PROMOTION
    ]
    suppressed_count = len(mature_rows) - len(eligible_rows)

    def _outcome(note_id: str, views: int, collects: int, age: float | None) -> NoteOutcome:
        return NoteOutcome(
            note_id=note_id,
            views=views,
            collects=collects,
            age_hours=age,
            eligible=False,
            log_collects=math.log1p(max(0, collects)),
            collect_rate=(collects / views) if views > 0 else 0.0,
            collect_advantage=0.0,
            credibility=credibility_map.get(note_id, 1.0),
            suspected_throttle=note_id in throttled_ids,
        )

    if not eligible_rows:
        return OutcomeLearning(
            mature=False,
            promotable=False,
            mature_count=0,
            total_count=len(parsed),
            baseline_log_collects=0.0,
            mean_collect_advantage=0.0,
            best_note_id="",
            min_age_hours=min_age_hours,
            notes=[_outcome(*row) for row in parsed],
            reason="no_credible_mature_notes",
            suppressed_count=suppressed_count,
        )

    baseline_rows = eligible_rows[: max(1, baseline_window)]
    baseline = median([math.log1p(max(0, row[2])) for row in baseline_rows])
    eligible_ids = {row[0] for row in eligible_rows}

    outcomes = []
    for note_id, views, collects, age in parsed:
        outcome = _outcome(note_id, views, collects, age)
        if note_id in eligible_ids:
            log_collects = math.log1p(max(0, collects))
            outcome = NoteOutcome(
                note_id=note_id,
                views=views,
                collects=collects,
                age_hours=age,
                eligible=True,
                log_collects=log_collects,
                collect_rate=(collects / views) if views > 0 else 0.0,
                collect_advantage=log_collects - baseline,
                credibility=credibility_map.get(note_id, 1.0),
                suspected_throttle=note_id in throttled_ids,
            )
        outcomes.append(outcome)

    qualified = [o for o in outcomes if o.eligible]
    mean_advantage = sum(o.collect_advantage for o in qualified) / len(qualified)
    best = max(qualified, key=lambda o: (o.collect_advantage, o.collects))
    mature = len(qualified) >= MIN_MATURE_NOTES_FOR_PROMOTION
    promotable = mature and mean_advantage > 0.0
    if not mature:
        reason = "insufficient_mature_notes"
    elif promotable:
        reason = "positive_collect_advantage"
    else:
        reason = "below_baseline"
    return OutcomeLearning(
        mature=mature,
        promotable=promotable,
        mature_count=len(qualified),
        total_count=len(parsed),
        baseline_log_collects=baseline,
        mean_collect_advantage=mean_advantage,
        best_note_id=best.note_id,
        min_age_hours=min_age_hours,
        notes=outcomes,
        reason=reason,
        suppressed_count=suppressed_count,
    )


__all__ = [
    "DEFAULT_BASELINE_WINDOW",
    "MIN_CREDIBILITY_FOR_PROMOTION",
    "MIN_MATURE_NOTES_FOR_PROMOTION",
    "MIN_NOTE_AGE_HOURS",
    "NoteOutcome",
    "OutcomeLearning",
    "evaluate_outcome_learning",
    "spearman_rank_correlation",
]
