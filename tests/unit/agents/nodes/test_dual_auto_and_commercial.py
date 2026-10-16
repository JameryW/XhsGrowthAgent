"""P0-2 auto veto + P0-5 commercial publish disclosure."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.agents.nodes.publish_gate import (
    PUBLISH_CANCELLED,
    PUBLISH_CONFIRMED,
    publish_gate_node,
)
from backend.agents.nodes.review_gate import _should_auto_approve
from backend.state.enums import WorkflowPhase


def test_auto_approve_vetoed_for_commercial(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
    state = {
        "is_commercial": True,
        "copy_content": {"selected_title": "标题够长了", "body_text": "正文内容足够长足够长足够长"},
        "visual_plan": {"image_paths": ["a.jpg"]},
        "niche": "穿搭",
    }
    assert _should_auto_approve(state) is False


def test_auto_approve_vetoed_for_high_risk_niche(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
    state = {
        "copy_content": {"selected_title": "标题够长了", "body_text": "正文内容足够长足够长足够长"},
        "visual_plan": {"image_paths": ["a.jpg"]},
        "niche": "医疗",
    }
    assert _should_auto_approve(state) is False


def test_auto_approve_vetoed_for_blocking(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
    state = {
        "is_blocking": True,
        "copy_content": {"selected_title": "标题够长了", "body_text": "正文内容足够长足够长足够长"},
        "visual_plan": {"image_paths": ["a.jpg"]},
        "niche": "穿搭",
    }
    assert _should_auto_approve(state) is False


@pytest.mark.asyncio
async def test_publish_receipt_has_confirmer_source_time() -> None:
    state = {
        "session_id": "t1",
        "phase": WorkflowPhase.PUBLISHING,
        "auto_publish": True,
        "copy_content": {"selected_title": "t"},
        "visual_plan": {"image_paths": ["a.jpg"]},
    }
    result = await publish_gate_node(state, store=MagicMock())
    conf = result["publish_confirmation"]
    assert conf["decision"] == PUBLISH_CONFIRMED
    assert conf["source"] == "auto_publish"
    assert conf["confirmer"]
    assert conf["confirmed_at"]


@pytest.mark.asyncio
async def test_commercial_publish_requires_disclosure() -> None:
    state = {
        "session_id": "t1",
        "phase": WorkflowPhase.PUBLISHING,
        "is_commercial": True,
        "copy_content": {"selected_title": "日常", "body_text": "没有披露标记的正文"},
        "visual_plan": {"image_paths": ["a.jpg"]},
    }
    with patch(
        "backend.agents.nodes.publish_gate.interrupt",
        return_value={"decision": PUBLISH_CONFIRMED, "disclosure_confirmed": False},
    ):
        result = await publish_gate_node(state, store=MagicMock())
    assert result["phase"] == WorkflowPhase.CANCELLED
    assert result["publish_confirmation"]["decision"] == PUBLISH_CANCELLED
    assert result["publish_confirmation"].get("error_code") == "commercial_disclosure_required"


@pytest.mark.asyncio
async def test_commercial_publish_ok_with_disclosure() -> None:
    state = {
        "session_id": "t1",
        "phase": WorkflowPhase.PUBLISHING,
        "is_commercial": True,
        "copy_content": {"selected_title": "品牌合作", "body_text": "本条为广告合作内容"},
        "visual_plan": {"image_paths": ["a.jpg"]},
    }
    with patch(
        "backend.agents.nodes.publish_gate.interrupt",
        return_value={
            "decision": PUBLISH_CONFIRMED,
            "disclosure_confirmed": True,
            "confirmed_by": "alice",
        },
    ):
        result = await publish_gate_node(state, store=MagicMock())
    assert result["phase"] == WorkflowPhase.PUBLISHING
    conf = result["publish_confirmation"]
    assert conf["decision"] == PUBLISH_CONFIRMED
    assert conf["confirmer"] == "alice"
    assert conf["disclosure_confirmed"] is True


def test_publish_options_keeps_disclosure_confirmed() -> None:
    """Regression: Pydantic must not strip Review's disclosure checkbox."""
    from backend.api.routes.review import PublishOptions

    opts = PublishOptions(
        dry_run=True,
        auto_publish=False,
        account_id="acc-1",
        disclosure_confirmed=True,
    )
    dumped = opts.model_dump()
    assert dumped["disclosure_confirmed"] is True


def test_publish_options_keeps_ai_content_declared_default_true() -> None:
    """P1-4: AI declaration field must survive Pydantic and default ON."""
    from backend.api.routes.review import PublishOptions

    opts = PublishOptions(dry_run=True, auto_publish=False)
    assert opts.ai_content_declared is True
    dumped = opts.model_dump()
    assert dumped["ai_content_declared"] is True

    opts2 = PublishOptions(ai_content_declared=False)
    assert opts2.model_dump()["ai_content_declared"] is False


@pytest.mark.asyncio
async def test_publish_receipt_includes_ai_content_declared() -> None:
    state = {
        "session_id": "t1",
        "phase": WorkflowPhase.PUBLISHING,
        "dry_run": True,
        "copy_content": {"selected_title": "日常", "body_text": "正文"},
        "visual_plan": {"image_paths": ["a.jpg"]},
        "publish_options": {"dry_run": True, "ai_content_declared": True},
    }
    result = await publish_gate_node(state, store=MagicMock())
    conf = result["publish_confirmation"]
    assert conf["decision"] == PUBLISH_CONFIRMED
    assert conf.get("ai_content_declared") is True


@pytest.mark.asyncio
async def test_commercial_dry_run_reads_publish_options_disclosure() -> None:
    """Review checkbox lands in publish_options and authorises dry-run skip path."""
    state = {
        "session_id": "t1",
        "phase": WorkflowPhase.PUBLISHING,
        "is_commercial": True,
        "dry_run": True,
        "copy_content": {"selected_title": "品牌合作", "body_text": "本条为广告合作内容"},
        "visual_plan": {"image_paths": ["a.jpg"]},
        "publish_options": {"dry_run": True, "disclosure_confirmed": True},
    }
    result = await publish_gate_node(state, store=MagicMock())
    assert result["phase"] == WorkflowPhase.PUBLISHING
    assert result["publish_confirmation"]["decision"] == PUBLISH_CONFIRMED
    assert result["publish_confirmation"].get("disclosure_confirmed") is True


@pytest.mark.asyncio
async def test_commercial_dry_run_blocks_without_disclosure_in_options() -> None:
    state = {
        "session_id": "t1",
        "phase": WorkflowPhase.PUBLISHING,
        "is_commercial": True,
        "dry_run": True,
        "copy_content": {"selected_title": "品牌合作", "body_text": "本条为广告合作内容"},
        "visual_plan": {"image_paths": ["a.jpg"]},
        "publish_options": {"dry_run": True, "disclosure_confirmed": False},
    }
    result = await publish_gate_node(state, store=MagicMock())
    assert result["phase"] == WorkflowPhase.CANCELLED
    assert result["publish_confirmation"].get("error_code") == "commercial_disclosure_required"
