"""P0-2 / P0-5 compliance policy unit tests."""

from __future__ import annotations

import pytest

from backend.services.compliance_policy import (
    DualAutoPublishError,
    assert_not_dual_auto,
    commercial_disclosure_ok,
    is_high_risk_niche,
    state_is_blocking,
    state_is_commercial,
    text_has_disclosure,
)


def test_dual_auto_hard_reject(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
    with pytest.raises(DualAutoPublishError) as exc:
        assert_not_dual_auto(auto_publish=True)
    assert exc.value.error_code == "dual_auto_publish_forbidden"


def test_dual_auto_ok_when_only_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
    assert_not_dual_auto(auto_publish=False)
    monkeypatch.delenv("AUTO_APPROVE_LOW_RISK", raising=False)
    assert_not_dual_auto(auto_publish=True)


def test_high_risk_niche() -> None:
    assert is_high_risk_niche("医疗") is True
    assert is_high_risk_niche("医美") is True
    assert is_high_risk_niche("穿搭") is False


def test_state_is_commercial_brief() -> None:
    assert state_is_commercial({"workflow_mode": "brief"}) is True
    assert state_is_commercial({"is_commercial": True}) is True
    assert state_is_commercial({"workflow_mode": "trend"}) is False


def test_state_is_blocking_from_lexicon() -> None:
    assert state_is_blocking({"compliance_scan": {"is_blocking": True}}) is True
    assert (
        state_is_blocking(
            {
                "evaluation_result": {
                    "dimensions": [{"dimension": "compliance", "is_blocking": True}]
                }
            }
        )
        is True
    )


def test_disclosure_markers() -> None:
    assert text_has_disclosure("本条为品牌合作内容") is True
    assert text_has_disclosure("日常穿搭分享") is False


def test_commercial_disclosure_ok() -> None:
    state = {
        "is_commercial": True,
        "copy_content": {"selected_title": "合作测评", "body_text": "品牌合作笔记"},
        "publish_confirmation": {"disclosure_confirmed": True},
    }
    assert commercial_disclosure_ok(state) is True
    state["publish_confirmation"] = {"disclosure_confirmed": False}
    assert commercial_disclosure_ok(state) is False
