"""Regression coverage for historical Creator Center quality reports."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.middleware import error_handler_middleware
from backend.api.routes import analytics as analytics_routes
from backend.db.creator_stats import (
    _reset_memory_store,
    get_note_stats,
    list_all_note_stats,
    list_note_stats,
    upsert_notes,
)
from backend.services.creator_stats.quality import analyze_historical_quality, analyze_note_quality
from backend.services.creator_stats.types import NoteStats

from .conftest import grant_test_user


@pytest.fixture(autouse=True)
def _clear_creator_stats() -> None:
    _reset_memory_store()
    yield
    _reset_memory_store()


def _app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(error_handler_middleware)
    app.include_router(analytics_routes.router, prefix="/api/analytics")
    app.state.graph = MagicMock()
    app.state.graph.store = None
    return app


def _dimension(data: dict[str, object], key: str) -> dict[str, object]:
    dimensions = data["dimensions"]
    assert isinstance(dimensions, list)
    return next(item for item in dimensions if item["key"] == key)


def _note(
    note_id: str,
    *,
    engagement_rate: float,
    likes: int,
    collects: int = 12,
    title: str = "5个提高效率的方法清单",
    body_text: str = "",
) -> NoteStats:
    return NoteStats(
        note_id=note_id,
        account_id="quality_acc",
        title=title,
        body_text=body_text,
        views=1000,
        likes=likes,
        comments=0,
        collects=collects,
        shares=0,
        engagement_rate=engagement_rate,
    )


def test_quality_report_normalizes_percent_rates_and_does_not_mutate_notes():
    """Legacy percent values and empty optional bodies remain safe and pure."""
    notes = [
        _note("percent", engagement_rate=12.5, likes=125, body_text=""),
        _note("fraction_1", engagement_rate=0.125, likes=125, body_text=""),
        _note("fraction_2", engagement_rate=0.125, likes=125, body_text=""),
    ]
    before = deepcopy([note.to_dict() for note in notes])

    report = analyze_historical_quality(notes, " quality_acc ")
    data = report.to_dict()

    assert data["account_id"] == "quality_acc"
    assert data["scope"] == "account_history"
    assert data["total_notes"] == 3
    assert data["notes_analyzed"] == 3
    assert data["overall_score"] is not None
    assert data["grade"] in {"strong", "developing", "needs_attention"}
    assert data["confidence"] == "medium"
    assert data["cold_start"] is False
    assert data["insufficient_data"] is False
    assert [item["key"] for item in data["dimensions"]] == [
        "engagement",
        "save_value",
        "title_craft",
        "body_craft",
        "consistency",
    ]
    assert "12.50%" in _dimension(data, "engagement")["evidence"]
    # Empty optional bodies → body_craft unavailable, not a negative score.
    assert _dimension(data, "body_craft")["available"] is False
    assert "未导入可分析正文" in _dimension(data, "body_craft")["evidence"]
    assert data["recommendations"]
    assert [note.to_dict() for note in notes] == before
    assert analyze_historical_quality(list(reversed(notes)), "quality_acc").to_dict() == data


def test_quality_report_returns_honest_cold_and_sparse_responses():
    cold = analyze_historical_quality([], "quality_acc").to_dict()
    assert cold["overall_score"] is None
    assert cold["grade"] == "insufficient_data"
    assert cold["confidence"] == "low"
    assert cold["cold_start"] is True
    assert cold["insufficient_data"] is True
    assert cold["strengths"] == []
    assert cold["weaknesses"] == []
    assert cold["recommendations"][0]["dimension"] == "data_collection"

    # Missing title/body fields are incomplete import signals, not evidence of
    # bad writing.  With two rows the product remains explicitly low-data.
    sparse = analyze_historical_quality(
        [
            _note("s1", engagement_rate=0.08, likes=80, title="", body_text=""),
            _note("s2", engagement_rate=0.06, likes=60, title="", body_text=""),
        ],
        "quality_acc",
    ).to_dict()
    assert sparse["overall_score"] is None
    assert sparse["grade"] == "insufficient_data"
    assert sparse["cold_start"] is False
    assert sparse["insufficient_data"] is True
    assert sparse["strengths"] == []
    assert sparse["weaknesses"] == []
    assert sparse["recommendations"][0]["dimension"] == "data_collection"
    assert "未导入可分析标题" in _dimension(sparse, "title_craft")["evidence"]
    assert _dimension(sparse, "body_craft")["available"] is False
    assert "未导入可分析正文" in _dimension(sparse, "body_craft")["evidence"]


def test_quality_report_scores_imported_body_craft():
    """Imported body_text contributes a transparent body_craft dimension."""
    notes = [
        _note(
            "rich",
            engagement_rate=0.15,
            likes=150,
            body_text=(
                "第一步：整理资料。\n第二步：对比实测结果。\n"
                "个人使用下来的感受：效率明显提升，建议收藏这份清单。"
            ),
        ),
        _note(
            "thin",
            engagement_rate=0.10,
            likes=100,
            body_text="太给力了 #AI #大模型",
        ),
        _note(
            "missing",
            engagement_rate=0.08,
            likes=80,
            body_text="",
        ),
    ]

    report = analyze_historical_quality(notes, "quality_acc")
    data = report.to_dict()
    body = _dimension(data, "body_craft")
    assert body["available"] is True
    assert body["score"] is not None
    assert body["score"] > 0
    assert "已导入正文覆盖 2/3 篇" in body["evidence"]
    assert "结构/干货/体验信号" in body["evidence"]

    # A corpus of rich structured bodies should outscore thin hashtag blurbs.
    rich_only = analyze_historical_quality(
        [
            _note(
                f"r{i}",
                engagement_rate=0.12,
                likes=120,
                body_text="第一步：整理。\n第二步：实测。个人使用下来的感受：效率提升，建议收藏。",
            )
            for i in range(3)
        ],
        "quality_acc",
    ).to_dict()
    thin_only = analyze_historical_quality(
        [
            _note(f"t{i}", engagement_rate=0.12, likes=120, body_text="太给力了 #AI")
            for i in range(3)
        ],
        "quality_acc",
    ).to_dict()
    rich_score = _dimension(rich_only, "body_craft")["score"]
    thin_score = _dimension(thin_only, "body_craft")["score"]
    assert rich_score > thin_score


def test_single_note_quality_reuses_historical_dimensions_without_fake_consistency():
    note = _note(
        "single",
        engagement_rate=0.2,
        likes=200,
        collects=50,
        title="5个提高效率的方法清单",
        body_text="第一步：整理资料。\n第二步：实测对比，个人使用下来的感受很稳。",
    )
    before = note.to_dict()

    report = analyze_note_quality(note, " quality_acc ")
    data = report.to_dict()

    assert data["account_id"] == "quality_acc"
    assert data["note_id"] == "single"
    assert data["scope"] == "single_note"
    assert data["total_notes"] == 1
    assert data["notes_analyzed"] == 1
    assert data["overall_score"] is not None
    assert data["confidence"] == "low"
    assert data["insufficient_data"] is False
    dimensions = {item["key"]: item for item in data["dimensions"]}
    assert dimensions["engagement"]["available"] is True
    assert dimensions["save_value"]["available"] is True
    assert dimensions["title_craft"]["available"] is True
    assert dimensions["body_craft"]["available"] is True
    assert dimensions["body_craft"]["score"] > 0
    assert dimensions["consistency"]["available"] is False
    assert data["recommendations"]
    assert note.to_dict() == before


def test_single_note_quality_reports_missing_signals_honestly():
    report = analyze_note_quality(
        NoteStats(note_id="empty", account_id="quality_acc"),
        "quality_acc",
        locale="en",
    ).to_dict()

    assert report["overall_score"] is None
    assert report["grade"] == "insufficient_data"
    assert report["confidence"] == "low"
    assert report["insufficient_data"] is True
    assert report["recommendations"][0]["dimension"] == "data_collection"
    assert "no usable imported signals" in report["summary"]


@pytest.mark.asyncio
async def test_quality_endpoint_uses_all_history_over_display_limit_and_is_read_only():
    """101 durable rows must all reach the report, not the normal 100-row reader."""
    notes = [
        _note(
            f"note_{index:03}",
            engagement_rate=0.02 if index < 100 else 0.20,
            likes=20 if index < 100 else 200,
            collects=3 if index < 100 else 50,
            title="5个效率方法清单" if index % 2 else "效率提升实测",
            body_text="",  # optional body is intentionally absent from all rows
        )
        for index in range(101)
    ]
    imported, updated = await upsert_notes(notes)
    assert (imported, updated) == (101, 0)

    # Existing display reader stays capped; the new dedicated reader does not.
    assert len(await list_note_stats("quality_acc")) == 100
    before = {note.note_id: note.to_dict() for note in await list_all_note_stats("quality_acc")}
    assert len(before) == 101

    app = _app()
    client = TestClient(app)
    with grant_test_user(app):
        response = client.get("/api/analytics/creator-stats/quality_acc/quality")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["scope"] == "account_history"
    assert data["total_notes"] == 101
    assert data["notes_analyzed"] == data["total_notes"]
    assert data["overall_score"] is not None
    assert data["grade"] in {"strong", "developing", "needs_attention"}
    assert len(data["dimensions"]) == 5
    assert {item["key"] for item in data["dimensions"]} >= {
        "engagement",
        "save_value",
        "title_craft",
        "body_craft",
        "consistency",
    }
    assert _dimension(data, "body_craft")["available"] is False
    assert data["recommendations"]

    after = {note.note_id: note.to_dict() for note in await list_all_note_stats("quality_acc")}
    assert after == before

    with grant_test_user(app):
        english_response = client.get("/api/analytics/creator-stats/quality_acc/quality?locale=en")
    assert english_response.status_code == 200
    english = english_response.json()["data"]
    assert "Based on all 101 imported historical notes" in english["summary"]
    assert "Across all 101 imported notes" in _dimension(english, "engagement")["evidence"]
    assert "全量" not in english["summary"]


@pytest.mark.asyncio
async def test_quality_endpoint_uses_one_snapshot_bundle_for_notes_and_metadata():
    note = _note("bundle_note", engagement_rate=0.12, likes=120, collects=30)
    bundle = {
        "account_id": "quality_acc",
        "account": None,
        "notes": [note],
        "note_count": 1,
        "data_as_of": "2026-07-22T10:00:00Z",
        "snapshot_id": "snapshot:bundle",
    }
    app = _app()
    client = TestClient(app)

    with (
        grant_test_user(app),
        pytest.MonkeyPatch.context() as mp,
    ):

        async def _bundle(_account_id: str) -> dict[str, object]:
            return bundle

        async def _unexpected_metadata(_account_id: str) -> dict[str, object]:
            raise AssertionError("quality route must not read a second snapshot")

        mp.setattr(analytics_routes, "_creator_snapshot_bundle", _bundle)
        mp.setattr(analytics_routes, "_creator_snapshot_metadata", _unexpected_metadata)
        response = client.get("/api/analytics/creator-stats/quality_acc/quality")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_notes"] == 1
    assert data["notes_analyzed"] == 1
    assert data["snapshot_id"] == "snapshot:bundle"
    assert data["data_as_of"] == "2026-07-22T10:00:00Z"


@pytest.mark.asyncio
async def test_single_note_detail_and_quality_endpoints_are_read_only():
    note = _note(
        "detail_001",
        engagement_rate=0.12,
        likes=120,
        title="5个提高效率的方法清单",
        body_text="第一步：整理资料。",
    )
    await upsert_notes([note])
    before = (await get_note_stats("quality_acc", "detail_001")).to_dict()  # type: ignore[union-attr]

    app = _app()
    client = TestClient(app)
    with grant_test_user(app):
        detail = client.get("/api/analytics/creator-stats/quality_acc/notes/detail_001")
        assert detail.status_code == 200
        detail_data = detail.json()["data"]
        assert detail_data["note"]["note_id"] == "detail_001"
        assert detail_data["note"]["body_text"] == "第一步：整理资料。"

        quality = client.get(
            "/api/analytics/creator-stats/quality_acc/notes/detail_001/quality?locale=en"
        )
        assert quality.status_code == 200
        quality_data = quality.json()["data"]
        assert quality_data["note_id"] == "detail_001"
        assert quality_data["quality"]["scope"] == "single_note"
        assert quality_data["quality"]["overall_score"] is not None
        assert "single imported note" in quality_data["quality"]["summary"]

        after = (await get_note_stats("quality_acc", "detail_001")).to_dict()  # type: ignore[union-attr]
        assert after == before

        missing = client.get("/api/analytics/creator-stats/quality_acc/notes/missing")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "ERROR_CREATOR_NOTE_NOT_FOUND"
