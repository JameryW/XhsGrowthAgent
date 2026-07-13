"""Regression coverage for historical Creator Center quality reports."""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import analytics as analytics_routes
from backend.db.creator_stats import (
    _reset_memory_store,
    list_all_note_stats,
    list_note_stats,
    upsert_notes,
)
from backend.services.creator_stats.quality import analyze_historical_quality
from backend.services.creator_stats.types import NoteStats


@pytest.fixture(autouse=True)
def _clear_creator_stats() -> None:
    _reset_memory_store()
    yield
    _reset_memory_store()


def _app() -> FastAPI:
    app = FastAPI()
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
    assert data["scope"] == "all_imported_history"
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
        "consistency",
    ]
    assert "12.50%" in _dimension(data, "engagement")["evidence"]
    assert all("body_text" not in item["evidence"] for item in data["dimensions"])
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

    client = TestClient(_app())
    response = client.get("/api/analytics/creator-stats/quality_acc/quality")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["scope"] == "all_imported_history"
    assert data["total_notes"] == 101
    assert data["notes_analyzed"] == data["total_notes"]
    assert data["overall_score"] is not None
    assert data["grade"] in {"strong", "developing", "needs_attention"}
    assert len(data["dimensions"]) == 4
    assert data["recommendations"]

    after = {note.note_id: note.to_dict() for note in await list_all_note_stats("quality_acc")}
    assert after == before

    english_response = client.get(
        "/api/analytics/creator-stats/quality_acc/quality?locale=en"
    )
    assert english_response.status_code == 200
    english = english_response.json()["data"]
    assert "Based on all 101 imported historical notes" in english["summary"]
    assert "Across all 101 imported notes" in _dimension(english, "engagement")["evidence"]
    assert "全量" not in english["summary"]
