"""Focused backend contract tests for history/quality consistency."""

from __future__ import annotations

import pytest

from backend.api.routes.evaluation import _sanitize_historical_evaluation
from backend.db import creator_stats, quality_evaluations
from backend.services.creator_stats.types import NoteStats
from backend.services.quality_consistency import snapshot_id


@pytest.fixture(autouse=True)
def _clear_memory_stores() -> None:
    creator_stats._reset_memory_store()
    quality_evaluations._reset_memory_store()
    yield
    creator_stats._reset_memory_store()
    quality_evaluations._reset_memory_store()


def _note(index: int, account_id: str = "acc-a") -> NoteStats:
    return NoteStats(
        account_id=account_id,
        note_id=f"note-{index:04d}",
        title=f"标题 {index}",
        published_at=f"2026-07-{(index % 28) + 1:02d}T12:00:00Z",
        synced_at="2026-07-22T10:00:00Z",
        views=100,
        likes=index,
        engagement_rate=index / 1000,
    )


@pytest.mark.asyncio
async def test_canonical_history_cursor_walks_more_than_500_without_duplicates() -> None:
    await creator_stats.upsert_notes([_note(index) for index in range(601)])
    cursor: str | None = None
    seen: list[str] = []
    first_page = None
    while True:
        page = await creator_stats.list_note_stats_page("acc-a", cursor=cursor, limit=50)
        if first_page is None:
            first_page = page
        seen.extend(item.note_id for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert first_page is not None
    assert first_page.total == 601
    assert len(seen) == 601
    assert len(set(seen)) == 601
    assert first_page.data_as_of == "2026-07-22T10:00:00Z"
    assert first_page.snapshot_id is not None
    # Cursor batches are one canonical snapshot, so a consumer can safely
    # append pages without silently mixing two imports.
    second_page = await creator_stats.list_note_stats_page(
        "acc-a", cursor=first_page.next_cursor, limit=50
    )
    assert second_page.snapshot_id == first_page.snapshot_id
    assert all(0 <= item.engagement_rate <= 1 for item in first_page.items)


def test_snapshot_id_changes_with_subject_version_but_not_order() -> None:
    first = snapshot_id(
        "acc-a",
        "2026-07-22T10:00:00Z",
        subject_versions=[("note-1", "2026-07-22T09:00:00Z"), ("note-2", "2026-07-22T08:00:00Z")],
    )
    reordered = snapshot_id(
        "acc-a",
        "2026-07-22T10:00:00Z",
        subject_versions=[("note-2", "2026-07-22T08:00:00Z"), ("note-1", "2026-07-22T09:00:00Z")],
    )
    changed = snapshot_id(
        "acc-a",
        "2026-07-22T10:00:00Z",
        subject_versions=[("note-1", "2026-07-22T09:30:00Z"), ("note-2", "2026-07-22T08:00:00Z")],
    )
    assert first == reordered
    assert first != changed


def test_historical_degraded_result_never_exposes_legacy_pass() -> None:
    result = _sanitize_historical_evaluation(
        {
            "overall_score": 100,
            "decision": "approved",
            "degraded": True,
            "dimensions": [],
        },
        niche_available=False,
        evaluator_fingerprint="rqgm:test",
    )
    assert result["status"] == "degraded"
    assert result["overall_score"] is None
    assert result["decision"] is None


def test_empty_historical_panel_cannot_keep_legacy_score() -> None:
    result = _sanitize_historical_evaluation(
        {"overall_score": 100, "decision": "approved", "dimensions": []},
        niche_available=True,
        evaluator_fingerprint="rqgm:test",
    )
    assert result["status"] == "partial"
    assert result["overall_score"] is None
    assert result["decision"] is None


def test_missing_historical_dimensions_are_unavailable_not_neutral_70() -> None:
    result = _sanitize_historical_evaluation(
        {
            "overall_score": 90,
            "decision": "approved",
            "dimensions": [
                {
                    "dimension": "copywriting",
                    "score": 90,
                    "rationale": "ok",
                }
            ],
        },
        niche_available=False,
        evaluator_fingerprint="rqgm:test",
    )
    dims = {item["dimension"]: item for item in result["dimensions"]}
    assert dims["compliance"]["available"] is False
    assert dims["compliance"]["score"] is None
    assert result["status"] == "partial"
    assert result["overall_score"] is None


def test_historical_sanitizer_uses_effective_thresholds() -> None:
    dimensions = [
        {
            "dimension": name,
            "score": 80,
            "available": True,
            "rationale": "ok",
            "issues": [],
            "is_blocking": False,
        }
        for name in (
            "copywriting",
            "compliance",
            "ai_taste",
            "commercial_tone",
            "altruism",
            "reach",
            "audience",
        )
    ]
    result = _sanitize_historical_evaluation(
        {"dimensions": dimensions},
        niche_available=True,
        evaluator_fingerprint="rqgm:test",
        pass_threshold=85,
        reject_threshold=45,
    )
    assert result["status"] == "partial"
    assert result["overall_score"] == 80.0
    assert result["decision"] == "needs_revision"


@pytest.mark.asyncio
async def test_quality_run_cache_is_idempotent_and_force_keeps_versions() -> None:
    common = dict(
        account_id="acc-a",
        subject_type="imported_note",
        subject_id="note-1",
        assessment_type="rqgm_content_review",
        source_content_hash="sha256:content",
        source_data_as_of="2026-07-22T10:00:00Z",
        context_hash="sha256:context",
        evaluator_fingerprint="rqgm:fingerprint",
    )
    first = quality_evaluations.new_run(**common)
    first.status = "ready"
    first.result_json = {"overall_score": 82}
    await quality_evaluations.create_run(first)
    cached = await quality_evaluations.get_cached(**common)
    assert cached is not None
    assert cached.evaluation_id == first.evaluation_id

    second = quality_evaluations.new_run(**common)
    second.status = "ready"
    second.result_json = {"overall_score": 84}
    await quality_evaluations.create_run(second)
    latest = await quality_evaluations.get_latest_for_subject("acc-a", "imported_note", "note-1")
    assert latest is not None
    assert latest.evaluation_id == second.evaluation_id
    assert latest.result_json["overall_score"] == 84
