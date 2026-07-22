"""Contract tests for explicit workflow/imported-note identity linking."""

from __future__ import annotations

import pytest

from backend.api.routes.analytics import _extract_post_data, _merge_imported_posts
from backend.db import creator_stats
from backend.services.creator_stats.types import NoteStats


@pytest.fixture(autouse=True)
def _clear_memory_notes():
    creator_stats._reset_memory_store()
    yield
    creator_stats._reset_memory_store()


def _workflow(thread_id: str, *, post_id: str = "") -> dict:
    return {
        "session_id": thread_id,
        "account_id": "acc-a",
        "copy_content": {"selected_title": f"工作流 {thread_id}"},
        "publish_result": {
            "post_id": post_id,
            "status": "published",
            "published_at": "2026-07-22T10:00:00Z",
        },
        "analytics": {"views": 10, "likes": 2},
    }


def _note(note_id: str) -> NoteStats:
    return NoteStats(
        account_id="acc-a",
        note_id=note_id,
        title=f"导入 {note_id}",
        published_at="2026-07-22T10:00:00Z",
        synced_at="2026-07-22T11:00:00Z",
        views=100,
        likes=20,
    )


@pytest.mark.asyncio
async def test_matching_platform_id_links_without_duplicate():
    await creator_stats.upsert_notes([_note("note-1")])
    workflow = _extract_post_data(_workflow("thread-1", post_id="note-1"), "acc-a")
    assert workflow is not None
    assert workflow["platform_post_id"] == "note-1"
    merged = await _merge_imported_posts("acc-a", [workflow])
    assert len(merged) == 1
    assert merged[0]["link_status"] == "linked"
    assert merged[0]["linked_note_id"] == "note-1"


@pytest.mark.asyncio
async def test_synthetic_workflow_id_never_links_imported_note():
    await creator_stats.upsert_notes([_note("thread-2")])
    workflow = _extract_post_data(_workflow("thread-2"), "acc-a")
    assert workflow is not None
    assert workflow["id"] == "workflow:thread-2"
    assert workflow["platform_post_id"] == ""
    merged = await _merge_imported_posts("acc-a", [workflow])
    assert len(merged) == 2
    assert {row["link_status"] for row in merged} == {"unmatched"}


@pytest.mark.asyncio
async def test_duplicate_workflow_claims_are_ambiguous_and_not_collapsed():
    await creator_stats.upsert_notes([_note("note-3")])
    first = _extract_post_data(_workflow("thread-3a", post_id="note-3"), "acc-a")
    second = _extract_post_data(_workflow("thread-3b", post_id="note-3"), "acc-a")
    assert first is not None and second is not None
    merged = await _merge_imported_posts("acc-a", [first, second])
    assert len(merged) == 3
    assert all(row["link_status"] == "ambiguous" for row in merged)
