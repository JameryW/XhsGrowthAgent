"""Tests for evaluator node content snapshot construction."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.agents.nodes.evaluator import _build_content_snapshot, _collect_sample


def test_build_content_snapshot_captures_copy_and_visual_fields() -> None:
    """Snapshot holds the fields the finetune input needs."""
    state = {
        "copy_content": {
            "selected_title": "标题",
            "body_text": "正文" * 50,
            "hashtags": ["tag1", "tag2"],
            "cta": "点关注",
            "tone": "治愈",
        },
        "visual_plan": {
            "cover_prompt": "封面",
            "image_prompts": ["p1", "p2", "p3"],
            "image_count": 3,
            "layout_style": "grid",
        },
    }
    snap = _build_content_snapshot(state)
    assert snap["title"] == "标题"
    assert snap["body"] == "正文" * 50
    assert snap["hashtags"] == ["tag1", "tag2"]
    assert snap["cta"] == "点关注"
    assert snap["cover_prompt"] == "封面"
    assert snap["image_prompts"] == ["p1", "p2", "p3"]
    assert snap["image_count"] == 3
    assert snap["layout_style"] == "grid"


def test_build_content_snapshot_truncates_long_body() -> None:
    """Body is capped to bound sample row volume."""
    long_body = "字" * 5000
    snap = _build_content_snapshot({"copy_content": {"body_text": long_body}})
    assert len(snap["body"]) == 2000  # _BODY_TRUNCATE


def test_build_content_snapshot_caps_image_prompts() -> None:
    """Only the first N image prompts are kept."""
    prompts = [f"p{i}" for i in range(20)]
    snap = _build_content_snapshot({"visual_plan": {"image_prompts": prompts}})
    assert len(snap["image_prompts"]) == 6  # _MAX_IMAGE_PROMPTS
    assert snap["image_prompts"][0] == "p0"


def test_build_content_snapshot_handles_missing_fields() -> None:
    """Empty/missing state yields safe defaults, not crashes."""
    snap = _build_content_snapshot({})
    assert snap["title"] == ""
    assert snap["body"] == ""
    assert snap["hashtags"] == []
    assert snap["image_prompts"] == []
    assert snap["image_count"] == 0


@pytest.mark.asyncio
async def test_collect_sample_skips_degraded_or_scoreless_results(monkeypatch) -> None:
    """Evaluator outages must not become 0-point training/trend samples."""
    insert = AsyncMock()
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)
    monkeypatch.setattr("backend.db.evaluator_config.insert_sample", insert)

    await _collect_sample(
        {"account_id": "acct1"},
        "thread-1",
        {"status": "degraded", "degraded": True, "overall_score": None},
    )
    await _collect_sample(
        {"account_id": "acct1"},
        "thread-2",
        {"status": "partial", "overall_score": None},
    )

    insert.assert_not_awaited()
