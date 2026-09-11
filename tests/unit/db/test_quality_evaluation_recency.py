"""`latest` must be defined even when two runs share a timestamp.

`created_at` is a TEXT ISO timestamp, and two writes inside one clock tick get the
same string — routine on a ~15.6 ms Windows clock. Before the insertion sequence
existed, the memory fallback resolved that tie with `max()`, which keeps the first
maximal element, while Postgres used `ORDER BY created_at DESC` with no
tie-break, which returns whichever row the planner reaches first. The same
application state therefore had no single answer, and the two adapters could
disagree about it.
"""

from __future__ import annotations

import pytest

from backend.db import quality_evaluations as qe

SAME_TICK = "2026-09-11T00:00:00+00:00"

_IDENTITY = {
    "account_id": "acc-a",
    "subject_type": "imported_note",
    "subject_id": "note-1",
    "assessment_type": "rqgm_content_review",
    "source_content_hash": "sha256:source",
    "source_data_as_of": "2026-09-11",
    "context_hash": "sha256:context",
    "evaluator_fingerprint": "rqgm:fingerprint",
}


@pytest.fixture(autouse=True)
def _fresh_store():
    qe._reset_memory_store()
    yield
    qe._reset_memory_store()


async def _ready_run(score: int) -> qe.QualityEvaluationRun:
    run = qe.new_run(**_IDENTITY)
    run.created_at = SAME_TICK  # forced tie: no reliance on host clock resolution
    run.status = "ready"
    run.result_json = {"overall_score": score}
    return await qe.create_run(run)


@pytest.mark.asyncio
async def test_latest_wins_the_timestamp_tie_by_insertion_order() -> None:
    first = await _ready_run(82)
    second = await _ready_run(84)

    assert first.created_at == second.created_at
    assert second.seq > first.seq

    latest = await qe.get_latest_for_subject("acc-a", "imported_note", "note-1")

    assert latest is not None
    assert latest.evaluation_id == second.evaluation_id
    assert latest.result_json["overall_score"] == 84


@pytest.mark.asyncio
async def test_cached_lookup_is_deterministic_across_equal_timestamps() -> None:
    await _ready_run(82)
    newest = await _ready_run(84)

    cached = await qe.get_cached(**_IDENTITY)

    assert cached is not None
    assert cached.evaluation_id == newest.evaluation_id


@pytest.mark.asyncio
async def test_trend_orders_equal_timestamps_by_insertion_too() -> None:
    first = await _ready_run(82)
    second = await _ready_run(84)

    points = await qe.fetch_trend_points("acc-a", limit=10)

    assert [point["overall_score"] for point in points] == [82.0, 84.0]
    assert points[-1]["created_at"] == SAME_TICK
    assert second.seq > first.seq


@pytest.mark.asyncio
async def test_completion_time_outranks_creation_time_for_trend() -> None:
    """The memory branch must agree with COALESCE(completed_at, created_at)."""
    earlier_created_but_later_completed = qe.new_run(**_IDENTITY)
    earlier_created_but_later_completed.created_at = "2026-09-10T00:00:00+00:00"
    earlier_created_but_later_completed.completed_at = "2026-09-12T00:00:00+00:00"
    earlier_created_but_later_completed.status = "ready"
    earlier_created_but_later_completed.result_json = {"overall_score": 70}
    await qe.create_run(earlier_created_but_later_completed)

    newer_created_but_unfinished = qe.new_run(**_IDENTITY)
    newer_created_but_unfinished.created_at = "2026-09-11T00:00:00+00:00"
    newer_created_but_unfinished.completed_at = None
    newer_created_but_unfinished.status = "ready"
    newer_created_but_unfinished.result_json = {"overall_score": 90}
    await qe.create_run(newer_created_but_unfinished)

    points = await qe.fetch_trend_points("acc-a", limit=10)

    # Ascending by completion time, so the run that finished last is plotted last
    # even though it was created earlier — which is what the Postgres branch does.
    assert [point["overall_score"] for point in points] == [90.0, 70.0]
