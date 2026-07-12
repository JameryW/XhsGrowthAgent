"""Cycle-6: pagination dedupe (last wins), timestamp parse, period/tags hygiene."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.api.routes.analytics import _filter_by_period
from backend.db.creator_stats import _reset_memory_store
from backend.services.creator_stats.client import CreatorStatsClient
from backend.services.creator_stats.normalize import (
    _publish_time,
    normalize_note,
    normalize_note_list,
)


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


# ── Dedupe last-wins ────────────────────────────────────────────────────────


def test_normalize_note_list_keeps_last_duplicate_metrics():
    notes = normalize_note_list(
        [
            {"note_id": "same", "title": "old", "view_count": 10, "like_count": 1},
            {"note_id": "other", "title": "o", "view_count": 1},
            {"note_id": "same", "title": "new", "view_count": 99, "like_count": 9},
        ],
        "acc",
    )
    by_id = {n.note_id: n for n in notes}
    assert set(by_id) == {"same", "other"}
    assert by_id["same"].views == 99
    assert by_id["same"].likes == 9
    assert by_id["same"].title == "new"
    # order: first-seen order preserved
    assert [n.note_id for n in notes] == ["same", "other"]


@pytest.mark.asyncio
async def test_client_pagination_last_page_wins_for_duplicate_note_id():
    class DupPages:
        async def get(self, url, *, headers, params=None):
            if "/note/" in url:
                page = int(params.get("page_num", 1))
                # full page so fetch continues
                return 200, {
                    "list": [
                        {
                            "note_id": "same",
                            "title": f"p{page}",
                            "view_count": page * 100,
                            "like_count": page,
                        },
                        {"note_id": f"uniq_{page}", "view_count": 1, "like_count": 0},
                    ]
                }
            return 200, {"view_count": 1}

    client = CreatorStatsClient(cookie="c", transport=DupPages())
    bundle = await client.fetch_all("pg", page_size=2, max_pages=3)
    same = next(n for n in bundle.notes if n.note_id == "same")
    # last page was 3 → views 300
    assert same.views == 300
    assert same.title == "p3"
    assert {n.note_id for n in bundle.notes} == {"same", "uniq_1", "uniq_2", "uniq_3"}


# ── Timestamps ──────────────────────────────────────────────────────────────


def test_publish_time_parses_numeric_string_ms_and_seconds():
    ms = _publish_time({"publish_time": "1717200000000"})
    assert ms.startswith("2024")
    assert "T" in ms
    sec = _publish_time({"publish_time": "1717200000"})
    assert sec.startswith("2024")
    iso = _publish_time({"publish_time": "2026-07-01T12:00:00+00:00"})
    assert iso.startswith("2026-07-01")


def test_bool_note_id_rejected():
    assert normalize_note({"note_id": True, "view_count": 1}, "a") is None
    assert normalize_note({"id": False, "view_count": 1}, "a") is None


def test_tags_skip_none_and_empty():
    note = normalize_note(
        {
            "note_id": "t1",
            "view_count": 1,
            "tags": ["", None, "母婴", {"name": "干货"}, {"name": ""}],
        },
        "a",
    )
    assert note is not None
    assert note.tags == ["母婴", "干货"]
    assert "None" not in note.tags


# ── Period filter ───────────────────────────────────────────────────────────


def test_period_filter_excludes_missing_and_unparseable_dates():
    recent = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    posts = [
        {"id": "empty", "published_at": ""},
        {"id": "none", "published_at": None},
        {"id": "bad", "published_at": "not-a-date"},
        {"id": "old", "published_at": old},
        {"id": "ok", "published_at": recent},
    ]
    filtered = _filter_by_period(posts, "weekly")
    ids = {p["id"] for p in filtered}
    assert ids == {"ok"}
