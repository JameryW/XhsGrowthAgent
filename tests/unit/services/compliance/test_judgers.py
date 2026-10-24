"""Deterministic per-failure-mode publish judgers."""

from __future__ import annotations

import pytest

from backend.services.compliance.judgers import (
    JudgerId,
    JudgerThresholds,
    decide_publish_eligibility,
    judge_commercial_disclosure,
    judge_dual_auto,
    judge_high_risk_auto,
    judge_lexicon,
)


def test_lexicon_hit_blocks_with_audit() -> None:
    state = {
        "compliance_scan": {
            "is_blocking": True,
            "hits": [{"term": "包治百病", "category": "medical", "source": "base"}],
        }
    }
    report = decide_publish_eligibility(state)
    assert report.allowed is False
    lex = next(v for v in report.verdicts if v.judger_id == JudgerId.LEXICON)
    assert lex.passed is False and lex.blocking is True
    assert "lexicon" in report.to_audit_dict()["blocking_failures"]


def test_commercial_missing_markers_blocks() -> None:
    state = {
        "is_commercial": True,
        "copy_content": {"selected_title": "好物分享", "body_text": "今天试了这款面霜"},
    }
    v = judge_commercial_disclosure(state, JudgerThresholds())
    assert v.passed is False
    assert v.reason_code == "disclosure_markers_missing"


def test_commercial_with_markers_passes_pre_gate() -> None:
    state = {
        "is_commercial": True,
        "copy_content": {
            "selected_title": "品牌合作实测",
            "body_text": "本次为品牌合作内容",
        },
    }
    v = judge_commercial_disclosure(state, JudgerThresholds())
    assert v.passed is True


def test_dual_auto_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "1")
    v = judge_dual_auto({"auto_publish": True}, JudgerThresholds())
    assert v.passed is False
    assert v.reason_code == "dual_auto_forbidden"


def test_high_risk_auto_low_risk_forbidden() -> None:
    state = {
        "niche": "医美",
        "human_feedback": {"source": "auto_low_risk", "decision": "approved"},
    }
    v = judge_high_risk_auto(state, JudgerThresholds())
    assert v.passed is False
    assert v.blocking is True


def test_clean_state_allows_publish() -> None:
    state = {
        "compliance_scan": {"is_blocking": False, "hits": []},
        "copy_content": {"selected_title": "周末散步", "body_text": "公园里很舒服"},
        "evaluation_result": {"dimensions": [], "decision": "approved"},
    }
    report = decide_publish_eligibility(state)
    assert report.allowed is True
    assert report.to_audit_dict()["blocking_failures"] == []
    assert report.policy_version == "publish_judgers_v1"


def test_threshold_can_soften_lexicon(monkeypatch: pytest.MonkeyPatch) -> None:
    """Business-cost knob: operator may mark lexicon non-blocking (audit still fails)."""
    state = {
        "compliance_scan": {
            "is_blocking": True,
            "hits": [{"term": "包治百病", "category": "medical", "source": "base"}],
        }
    }
    soft = JudgerThresholds(lexicon_blocking=False)
    v = judge_lexicon(state, soft)
    assert v.passed is False
    assert v.blocking is False
    report = decide_publish_eligibility(state, thresholds=soft)
    # Other judgers may still pass; soft lexicon alone must not block.
    assert report.allowed is True
