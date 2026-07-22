"""Focused backend contract tests for history/quality consistency."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.asyncio
async def test_snapshot_changes_when_metrics_are_overwritten_at_same_timestamp() -> None:
    note = _note(1)
    await creator_stats.upsert_notes([note])
    first = await creator_stats.get_creator_stats_snapshot("acc-a")

    note.likes = 99
    note.engagement_rate = 0.99
    await creator_stats.upsert_notes([note])
    second = await creator_stats.get_creator_stats_snapshot("acc-a")

    assert first["data_as_of"] == second["data_as_of"]
    assert first["snapshot_id"] != second["snapshot_id"]


@pytest.mark.asyncio
async def test_snapshot_without_account_row_uses_complete_note_population() -> None:
    await creator_stats.upsert_notes([_note(index) for index in range(3)])
    snapshot = await creator_stats.get_creator_stats_snapshot("acc-a")
    page = await creator_stats.list_note_stats_page("acc-a", limit=1)

    assert snapshot["note_count"] == 3
    assert snapshot["snapshot_id"] is not None
    assert page.snapshot_id == snapshot["snapshot_id"]


@pytest.mark.asyncio
async def test_snapshot_bundle_exposes_facts_and_metadata_from_same_population() -> None:
    await creator_stats.upsert_notes([_note(index) for index in range(3)])

    bundle = await creator_stats.get_creator_stats_snapshot_bundle("acc-a")
    snapshot = await creator_stats.get_creator_stats_snapshot("acc-a")

    assert bundle["account_id"] == "acc-a"
    assert bundle["account"] is None
    assert len(bundle["notes"]) == 3
    assert bundle["note_count"] == len(bundle["notes"])
    assert bundle["snapshot_id"] == snapshot["snapshot_id"]
    assert bundle["data_as_of"] == snapshot["data_as_of"]


@pytest.mark.asyncio
async def test_postgres_page_snapshot_reads_all_notes_without_account_row() -> None:
    """Legacy Postgres rows must share one full-population snapshot across pages."""

    all_rows = [
        (
            note.account_id,
            note.note_id,
            note.title,
            note.body_text,
            note.views,
            note.likes,
            note.comments,
            note.collects,
            note.shares,
            note.published_at,
            note.content_type,
            "[]",
            note.cover_url,
            note.engagement_rate,
            note.synced_at,
            note.source,
            "{}",
        )
        for note in (_note(index) for index in range(600))
    ]
    selected_rows = all_rows[:51]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(side_effect=[None, (600,), None])
    cursor.fetchall = AsyncMock(side_effect=[all_rows, selected_rows, all_rows])
    conn = MagicMock()
    transactions: list[None] = []

    @asynccontextmanager
    async def cursor_context():
        yield cursor

    @asynccontextmanager
    async def transaction_context():
        transactions.append(None)
        yield

    conn.cursor = cursor_context
    conn.transaction = transaction_context
    pool = MagicMock()

    @asynccontextmanager
    async def connection_context():
        yield conn

    pool.connection = connection_context
    with (
        patch("backend.db.creator_stats.is_pool_ready", return_value=True),
        patch("backend.db.creator_stats.get_pool", return_value=pool),
    ):
        snapshot = await creator_stats.get_creator_stats_snapshot("acc-a")
        page = await creator_stats.list_note_stats_page("acc-a", limit=50)

    assert snapshot["note_count"] == 600
    assert page.total == 600
    assert page.snapshot_id == snapshot["snapshot_id"]
    assert len(transactions) == 2
    assert (
        sum(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ" in str(call.args[0])
            for call in cursor.execute.call_args_list
        )
        == 2
    )


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


def test_snapshot_id_can_use_content_versions_when_legacy_timestamp_is_missing() -> None:
    snapshot = snapshot_id("acc-a", None, subject_versions=[("note-1", "digest")])

    assert snapshot is not None
    assert snapshot.startswith("snapshot:")


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
