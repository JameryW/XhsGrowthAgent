"""Trend points from durable quality evaluation runs (historical-note RQGM)."""

from __future__ import annotations

import pytest

from backend.db import quality_evaluations as qe


@pytest.fixture(autouse=True)
def _reset_mem() -> None:
    qe._reset_memory_store()
    yield
    qe._reset_memory_store()


@pytest.mark.asyncio
async def test_fetch_trend_points_includes_scored_partial_runs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(qe, "is_pool_ready", lambda: False)

    good = qe.new_run(
        account_id="acc-a",
        subject_type="imported_note",
        subject_id="n1",
        assessment_type="rqgm_content_review",
        source_content_hash="h1",
        source_data_as_of="2026-07-24T00:00:00Z",
        context_hash="c1",
        evaluator_fingerprint="fp",
    )
    good.status = "partial"
    good.completed_at = "2026-07-24T03:50:00+00:00"
    good.result_json = {
        "overall_score": 52.6,
        "decision": "needs_revision",
        "status": "partial",
        "degraded": False,
        "dimensions": [{"dimension": "copywriting", "score": 50}],
    }
    await qe.create_run(good)

    degraded = qe.new_run(
        account_id="acc-a",
        subject_type="imported_note",
        subject_id="n2",
        assessment_type="rqgm_content_review",
        source_content_hash="h2",
        source_data_as_of="2026-07-24T00:00:00Z",
        context_hash="c2",
        evaluator_fingerprint="fp",
    )
    degraded.status = "degraded"
    degraded.completed_at = "2026-07-24T04:00:00+00:00"
    degraded.result_json = {
        "overall_score": None,
        "decision": None,
        "status": "degraded",
        "degraded": True,
        "dimensions": [],
    }
    await qe.create_run(degraded)

    other = qe.new_run(
        account_id="acc-b",
        subject_type="imported_note",
        subject_id="n3",
        assessment_type="rqgm_content_review",
        source_content_hash="h3",
        source_data_as_of="2026-07-24T00:00:00Z",
        context_hash="c3",
        evaluator_fingerprint="fp",
    )
    other.status = "partial"
    other.completed_at = "2026-07-24T05:00:00+00:00"
    other.result_json = {
        "overall_score": 80.0,
        "decision": "approved",
        "status": "partial",
        "dimensions": [],
    }
    await qe.create_run(other)

    points = await qe.fetch_trend_points("acc-a", limit=50)
    assert len(points) == 1
    assert points[0]["overall_score"] == 52.6
    assert points[0]["decision"] == "needs_revision"
    assert points[0]["source"] == "quality_evaluation_run"
    assert points[0]["created_at"] == "2026-07-24T03:50:00+00:00"
