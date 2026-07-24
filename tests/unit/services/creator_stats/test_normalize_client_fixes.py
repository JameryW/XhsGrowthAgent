"""Cycle-3 fixes: note_infos extraction, metric clamps, fixture errors, performance merge."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.db.creator_stats import _reset_memory_store, list_note_stats
from backend.services.creator_stats.client import CreatorStatsClient, FixtureTransport
from backend.services.creator_stats.normalize import (
    extract_note_items,
    normalize_note,
    normalize_note_list,
)
from backend.services.creator_stats.pipeline import sync_from_fixture

from .conftest import grant_test_user


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


# ── note_infos / extract_note_items ─────────────────────────────────────────


def test_extract_note_items_supports_note_infos():
    items = extract_note_items(
        {
            "note_infos": [
                {"note_id": "a", "view_count": 1},
                {"note_id": "b", "view_count": 2},
            ]
        }
    )
    assert len(items) == 2
    assert items[0]["note_id"] == "a"


def test_normalize_note_list_note_infos_alias():
    notes = normalize_note_list(
        {
            "note_infos": [
                {
                    "note_id": "ni1",
                    "title": "note_infos 标题",
                    "view_count": 100,
                    "like_count": 10,
                    "comment_count": 1,
                    "collect_count": 2,
                    "share_count": 0,
                }
            ]
        },
        "acc",
    )
    assert len(notes) == 1
    assert notes[0].note_id == "ni1"
    assert notes[0].views == 100
    assert notes[0].likes == 10


@pytest.mark.asyncio
async def test_client_fetch_all_reads_note_infos_envelope():
    transport = FixtureTransport(
        account_payload={"view_count": 50, "like_count": 5},
        notes_payload={
            "note_infos": [
                {
                    "note_id": "from_client",
                    "title": "客户端分页",
                    "view_count": 200,
                    "like_count": 20,
                }
            ]
        },
    )
    client = CreatorStatsClient(cookie="c", transport=transport)
    bundle = await client.fetch_all("acc_ni")
    assert len(bundle.notes) == 1
    assert bundle.notes[0].note_id == "from_client"
    assert bundle.notes[0].views == 200
    assert bundle.account.views == 50


# ── metric / id hygiene ─────────────────────────────────────────────────────


def test_negative_metrics_clamped_to_zero():
    note = normalize_note(
        {"note_id": "neg", "view_count": -5, "like_count": -2, "comment_count": 3},
        "a",
    )
    assert note is not None
    assert note.views == 0
    assert note.likes == 0
    assert note.comments == 3
    assert note.engagement_rate == 0.0


def test_whitespace_note_id_rejected():
    assert normalize_note({"note_id": "   ", "view_count": 1}, "a") is None
    note = normalize_note({"note_id": "  id_ok  ", "view_count": 1}, "a")
    assert note is not None
    assert note.note_id == "id_ok"


def test_numeric_note_id_not_stringified_as_float():
    """JSON numbers often arrive as float 123.0 — must not become '123.0'."""
    from backend.services.creator_stats.normalize import _note_id_str

    assert _note_id_str(123.0) == "123"
    assert _note_id_str(123) == "123"
    assert _note_id_str(1e2) == "100"
    assert _note_id_str("456.0") == "456"
    assert _note_id_str(True) == ""
    assert _note_id_str(float("nan")) == ""

    note = normalize_note(
        {"note_id": 789.0, "title": "float id", "view_count": 10, "like_count": 1},
        "a",
    )
    assert note is not None
    assert note.note_id == "789"
    # Dedupe: float and int forms of same id collapse
    notes = normalize_note_list(
        [
            {"note_id": 42.0, "title": "first", "views": 1},
            {"note_id": 42, "title": "second", "views": 99},
        ],
        "a",
    )
    assert len(notes) == 1
    assert notes[0].note_id == "42"
    assert notes[0].title == "second"
    assert notes[0].views == 99


def test_metric_overflow_clamped_to_int4_max():
    """Huge floats must not blow Postgres INTEGER on upsert."""
    note = normalize_note(
        {
            "note_id": "huge",
            "view_count": 10**20,
            "like_count": -1,
            "title": "overflow",
        },
        "a",
    )
    assert note is not None
    assert note.views == 2_147_483_647
    assert note.likes == 0


def test_duplicate_tags_deduped_order_preserved():
    """API tag lists often repeat the same tag — must not inflate topic scoring."""
    note = normalize_note(
        {
            "note_id": "dup_tags",
            "title": "辅食清单",
            "tags": ["母婴", "母婴", "辅食", "母婴", "干货"],
        },
        "a",
    )
    assert note is not None
    assert note.tags == ["母婴", "辅食", "干货"]

    # CSV form
    note2 = normalize_note(
        {"note_id": "csv", "title": "t", "tags": "美妆, 美妆, 护肤, 美妆"},
        "a",
    )
    assert note2 is not None
    assert note2.tags == ["美妆", "护肤"]


def test_top_tags_counts_notes_not_tag_multiplicity():
    from backend.services.creator_stats.analyze import _top_tags
    from backend.services.creator_stats.types import NoteStats

    notes = [
        NoteStats(
            note_id="1",
            account_id="a",
            title="a",
            tags=["灌水", "灌水", "灌水", "稀有"],
        ),
        NoteStats(note_id="2", account_id="a", title="b", tags=["干货"]),
    ]
    top = dict(_top_tags(notes, limit=5))
    # One note carries 灌水 once after de-dupe — not 3
    assert top["灌水"] == 1
    assert top["稀有"] == 1
    assert top["干货"] == 1


def test_body_text_captured_and_truncated():
    note = normalize_note(
        {
            "note_id": "body1",
            "title": "今日分享",
            "body": "宝宝辅食添加清单，母婴育儿干货 " + ("x" * 5000),
            "views": 10,
        },
        "a",
    )
    assert note is not None
    assert "宝宝" in note.body_text
    assert "母婴" in note.body_text
    assert len(note.body_text) <= 4000


def test_body_html_stripped_for_niche_keywords():
    """HTML tags between characters must not break 育儿 / 母婴 keyword match."""
    from backend.services.creator_stats.normalize import _strip_html

    note = normalize_note(
        {
            "note_id": "html1",
            "title": "分享",
            "body": "育</b>儿干货 <p>宝<span>宝</span>辅食</p>",
            "views": 1,
        },
        "a",
    )
    assert note is not None
    assert "<" not in note.body_text
    assert "育儿" in note.body_text
    assert "宝宝辅食" in note.body_text.replace(" ", "")
    # Block/break tags become spaces so English tokens stay separable
    assert _strip_html("my<br/>OOTD<br>look") == "my OOTD look"
    assert _strip_html("美妆<br>护肤") == "美妆 护肤"


def test_tone_falls_back_to_body_when_title_has_no_signal():
    from backend.services.creator_stats.analyze import _infer_tone_from_note, analyze_notes
    from backend.services.creator_stats.types import NoteStats

    note = NoteStats(
        note_id="tb1",
        account_id="a",
        title="今天天气不错",  # no tone keyword
        body_text="避雷！别买这款，真实踩坑记录",
        views=1000,
        likes=100,
        engagement_rate=0.2,
    )
    tone, _ = _infer_tone_from_note(note)
    assert tone == "犀利"
    # Title 犀利 wins over body 治愈
    note2 = NoteStats(
        note_id="tb2",
        account_id="a",
        title="避雷别买踩坑",
        body_text="其实内容很治愈温暖陪伴",
        views=1000,
        likes=80,
        engagement_rate=0.15,
    )
    assert _infer_tone_from_note(note2)[0] == "犀利"
    an = analyze_notes([note], "a")
    tones = [f.label for f in an.findings if f.finding_type == "tone"]
    assert tones == ["犀利"]


def test_best_note_uses_body_when_title_empty():
    """best_note must not label as note_id or evidence 「」 when body exists."""
    from backend.services.creator_stats.analyze import analyze_notes
    from backend.services.creator_stats.types import NoteStats

    an = analyze_notes(
        [
            NoteStats(
                note_id="nid_hidden",
                account_id="a",
                title="",
                body_text="慢慢来也很好的治愈日常陪伴",
                views=500,
                likes=80,
                engagement_rate=0.2,
            )
        ],
        "a",
    )
    best = next(f for f in an.findings if f.finding_type == "best_note")
    assert best.label != "nid_hidden"
    assert "治愈" in best.label or "慢慢来" in best.label
    assert "「」" not in best.evidence
    assert "nid_hidden" not in best.evidence


@pytest.mark.asyncio
async def test_body_text_survives_import_for_niche_infer():
    """Regression: body-only niche keywords were dropped after persist."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from backend.db.creator_stats import list_note_stats
    from backend.services.creator_stats.pipeline import sync_from_payload
    from backend.services.niche_resolver import resolve_account_niche

    await sync_from_payload(
        "body_niche_acc",
        {},
        [
            {
                "note_id": "bn1",
                "title": "今日分享",
                "body": "宝宝夜醒急救 辅食添加 母婴育儿干货",
                "views": 100,
                "likes": 10,
            },
            {
                "note_id": "bn2",
                "title": "日常",
                "content": "婴儿睡袋推荐给宝妈",
                "views": 50,
                "likes": 5,
            },
        ],
    )
    notes = await list_note_stats("body_niche_acc")
    assert any(n.body_text for n in notes)
    with patch(
        "backend.db.accounts.get_account",
        new_callable=AsyncMock,
        return_value=MagicMock(niche="", niche_source=""),
    ):
        nr = await resolve_account_niche("body_niche_acc", manual_niche="", persist=False)
    assert nr.cold_start is False
    assert nr.niche == "母婴"
    assert nr.source == "inferred"


# ── fixture load errors ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_fixture_returns_error_not_raise():
    result = await sync_from_fixture(
        "acc_missing_fx",
        fixture_path="/tmp/grok-goal-6b5dc54ac2e1/implementer/does_not_exist.json",
    )
    assert result.error is not None
    assert "fixture" in result.error.lower()
    assert result.notes_imported == 0
    assert await list_note_stats("acc_missing_fx") == []


# ── performance API merges imported notes ───────────────────────────────────


@pytest.mark.asyncio
async def test_performance_endpoint_includes_imported_creator_notes():
    from datetime import UTC, datetime, timedelta

    from backend.services.creator_stats.pipeline import sync_from_payload

    # Seed a note with a recent publish time so period filter keeps it
    recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    await sync_from_payload(
        "perf_acc",
        {"view_count": 42000, "like_count": 3800},
        [
            {
                "note_id": "note_recent_001",
                "title": "最近表现笔记",
                "view_count": 42000,
                "like_count": 3800,
                "comment_count": 100,
                "collect_count": 200,
                "share_count": 50,
                "publish_time": recent,
            }
        ],
        source="fixture",
        run_creative_analysis=False,
    )

    app = FastAPI()
    app.include_router(analytics_routes.router, prefix="/api/analytics")
    app.state.graph = MagicMock()

    client = TestClient(app)

    with pytest.MonkeyPatch.context() as mp, grant_test_user(app):

        async def _empty(*_a, **_k):
            return []

        mp.setattr(analytics_routes, "_get_completed_workflows", _empty)
        resp = client.get("/api/analytics/performance/perf_acc?period=weekly&limit=20")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["total"] >= 1
    ids = {p["id"] for p in data["posts"]}
    assert "note_recent_001" in ids
    row = next(p for p in data["posts"] if p["id"] == "note_recent_001")
    assert row["views"] == 42000
    assert row["likes"] == 3800
    assert row.get("source") in ("fixture", "creator_statistics")
    # Analytics raw responses use the canonical fraction unit; UI adapters
    # convert it to percent only at the presentation boundary.
    assert data["engagement_rate_unit"] == "fraction"
    assert 0 <= row["engagement_rate"] <= 1
