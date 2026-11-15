"""Age-gated, collect-first outcome learning (Phase-2 proposal 8)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.services.outcome_learning import (
    MIN_NOTE_AGE_HOURS,
    evaluate_outcome_learning,
    spearman_rank_correlation,
)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def _note(note_id: str, *, age_hours: float, views: int, collects: int) -> dict[str, object]:
    return {
        "note_id": note_id,
        "views": views,
        "collects": collects,
        "published_at": (NOW - timedelta(hours=age_hours)).isoformat(),
    }


def test_immature_notes_are_reported_but_not_eligible() -> None:
    report = evaluate_outcome_learning(
        [_note("fresh", age_hours=6, views=10_000, collects=50)],
        now=NOW,
    )

    assert report.mature is False
    assert report.promotable is False
    assert report.reason == "no_mature_notes"
    assert report.notes[0].eligible is False
    assert report.notes[0].age_hours == 6.0


def test_positive_collect_advantage_is_promotable() -> None:
    rows = [
        _note(f"old-{index}", age_hours=24 * 20, views=1_000, collects=5) for index in range(10)
    ]
    rows.extend(
        _note(f"new-{index}", age_hours=24 * 3, views=2_000, collects=100) for index in range(3)
    )

    report = evaluate_outcome_learning(rows, now=NOW)

    assert report.mature is True
    assert report.mature_count == 13
    assert report.promotable is True
    assert report.reason == "positive_collect_advantage"
    assert report.mean_collect_advantage > 0
    assert report.best_note_id.startswith("new-")


def test_baseline_is_the_recent_window_not_the_oldest_notes() -> None:
    old = [_note(f"old-{i}", age_hours=24 * 30, views=1_000, collects=1) for i in range(10)]
    recent = [_note(f"recent-{i}", age_hours=24 * 4, views=1_000, collects=100) for i in range(10)]

    report = evaluate_outcome_learning(old + recent, now=NOW, baseline_window=10)

    assert report.baseline_log_collects > 4.0  # log1p(100), not log1p(1)
    assert report.best_note_id.startswith("recent-")


def test_unknown_publish_time_is_not_mature() -> None:
    report = evaluate_outcome_learning(
        [{"note_id": "no-date", "views": 100, "collects": 10}],
        now=NOW,
    )

    assert report.reason == "no_mature_notes"
    assert report.notes[0].age_hours is None
    assert report.min_age_hours == MIN_NOTE_AGE_HOURS


def test_spearman_handles_ties_and_direction() -> None:
    assert spearman_rank_correlation([1, 2, 3], [10, 20, 30]) == 1.0
    assert spearman_rank_correlation([1, 2, 3], [30, 20, 10]) == -1.0
    assert spearman_rank_correlation([1, 1, 2], [3, 3, 4]) == 1.0
    assert spearman_rank_correlation([1], [1]) is None
