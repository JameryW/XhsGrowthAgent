"""P2-1: learning topic recommendations from performing notes (no invented metrics)."""

from __future__ import annotations

from backend.services.creator_stats.types import NoteStats
from backend.services.learning_recommendations import (
    OUTCOME_LEARNING_DOC,
    build_topic_recommendations,
)


def _note(**kwargs: object) -> NoteStats:
    base = {
        "note_id": "n1",
        "account_id": "acc1",
        "title": "春季穿搭分享",
        "views": 1000,
        "likes": 50,
        "comments": 10,
        "collects": 20,
        "shares": 5,
        "engagement_rate": 0.085,
        "tags": ["春季穿搭", "OOTD"],
    }
    base.update(kwargs)
    return NoteStats.from_dict(base)


def test_empty_when_no_performing_samples() -> None:
    payload = build_topic_recommendations([], account_id="acc1", limit=5)
    assert payload["empty"] is True
    assert payload["recommendations"] == []
    assert payload["empty_reason"] == "insufficient_performing_samples"
    assert payload["outcome_learning_doc"] == OUTCOME_LEARNING_DOC


def test_skips_zero_engagement_stubs() -> None:
    stubs = [
        _note(note_id="z1", engagement_rate=0, likes=0, comments=0, collects=0, shares=0),
        _note(note_id="z2", engagement_rate=0, likes=0, comments=0, collects=0, shares=0, title=""),
    ]
    payload = build_topic_recommendations(stubs, account_id="acc1")
    assert payload["empty"] is True
    assert payload["sample_count"] == 0


def test_ranks_top_n_by_engagement_and_uses_tags() -> None:
    notes = [
        _note(note_id="a", engagement_rate=0.02, tags=["低互动"], title="低"),
        _note(note_id="b", engagement_rate=0.2, tags=["高互动话题"], title="高"),
        _note(
            note_id="c",
            engagement_rate=0.1,
            tags=[],
            title="标题选题也很长所以需要截断一下才行对吧",
        ),
    ]
    payload = build_topic_recommendations(notes, account_id="acc1", limit=2)
    assert payload["empty"] is False
    assert payload["sample_count"] == 2
    assert payload["limit"] == 2
    recs = payload["recommendations"]
    assert recs[0]["topic"] == "高互动话题"
    assert recs[0]["related_note_id"] == "b"
    assert "note=b" in recs[0]["evidence_href"]
    assert recs[0]["evidence_doc"] == OUTCOME_LEARNING_DOC
    assert recs[1]["related_note_id"] == "c"
    assert "…" in recs[1]["topic"] or len(recs[1]["topic"]) <= 40


def test_never_fabricates_topics_without_title_or_tags() -> None:
    notes = [
        _note(
            note_id="blank",
            title="",
            tags=[],
            engagement_rate=0.5,
            likes=10,
        )
    ]
    payload = build_topic_recommendations(notes, account_id="acc1")
    assert payload["empty"] is True
