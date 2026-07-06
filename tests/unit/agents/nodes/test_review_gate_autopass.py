"""Tests for review_gate low-risk auto-pass.

Covers:
- _classify_publish_risk: low / medium / high 各类输入
- _auto_approve_enabled: env 开关读取 + fail-safe
- _should_auto_approve: low+enabled → True; high/medium 永不
- review_gate_node: low+enabled → approved + auto_low_risk audit + PUBLISHING;
  disabled/medium/high → 调 interrupt() 等人工（不自动放行）
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agents.nodes.review_gate import (
    _auto_approve_enabled,
    _classify_publish_risk,
    _should_auto_approve,
)
from backend.state.enums import ContentStatus, WorkflowPhase

# ── _classify_publish_risk ──


def _low_risk_state() -> dict:
    """A clean low-risk draft: title ok, body ok, has images, no sensitive words."""
    return {
        "copy_content": {
            "selected_title": "夏日清爽穿搭分享",
            "body_text": "今天分享一套夏日清爽穿搭，简约又好看，适合日常通勤和约会。" * 2,
        },
        "visual_plan": {
            "image_paths": ["/tmp/img1.jpg", "/tmp/img2.jpg"],
        },
        "niche": "穿搭",
    }


class TestClassifyPublishRisk:
    def test_low_risk_clean_draft(self) -> None:
        """有图、标题正文合理、无敏感词、非敏感类目 → low。"""
        assert _classify_publish_risk(_low_risk_state()) == "low"

    def test_high_sensitive_word_in_title(self) -> None:
        """标题含敏感词 → high。"""
        state = _low_risk_state()
        state["copy_content"]["selected_title"] = "处方药代购渠道"
        assert _classify_publish_risk(state) == "high"

    def test_high_sensitive_word_in_body(self) -> None:
        """正文含敏感词 → high。"""
        state = _low_risk_state()
        state["copy_content"]["body_text"] = "加微信私聊获取更多优惠信息"
        assert _classify_publish_risk(state) == "high"

    def test_high_medical_niche_without_disclaimer(self) -> None:
        """医疗类目无免责声明 → high。"""
        state = _low_risk_state()
        state["niche"] = "医疗"
        assert _classify_publish_risk(state) == "high"

    def test_high_finance_niche_without_disclaimer(self) -> None:
        """金融类目无免责声明 → high。"""
        state = _low_risk_state()
        state["niche"] = "金融"
        assert _classify_publish_risk(state) == "high"

    def test_medium_missing_images(self) -> None:
        """缺图片 → medium。"""
        state = _low_risk_state()
        state["visual_plan"]["image_paths"] = []
        assert _classify_publish_risk(state) == "medium"

    def test_medium_short_title(self) -> None:
        """标题过短 (<5) → medium。"""
        state = _low_risk_state()
        state["copy_content"]["selected_title"] = "好物"
        assert _classify_publish_risk(state) == "medium"

    def test_medium_short_body(self) -> None:
        """正文过短 (<20) → medium。"""
        state = _low_risk_state()
        state["copy_content"]["body_text"] = "短正文"
        assert _classify_publish_risk(state) == "medium"

    def test_medium_sensitive_niche_muying(self) -> None:
        """母婴类目（偏敏感）→ medium。"""
        state = _low_risk_state()
        state["niche"] = "母婴"
        assert _classify_publish_risk(state) == "medium"

    def test_low_medical_niche_with_disclaimer(self) -> None:
        """医疗类目有免责声明 → 不升 high（仍需过 medium/low 判定，此处无其他风险 → low）。

        注：高风险类目有免责仅免 high，其他特征仍走 medium/low 链。此处其他特征均 low。
        """
        state = _low_risk_state()
        state["niche"] = "医疗"
        state["copy_content"]["body_text"] = (
            "免责声明：本文不构成医疗建议。" + "正文内容足够长以满足最低长度要求。" * 2
        )
        # 高风险类目有免责 → 不 high；其他特征 low → low
        assert _classify_publish_risk(state) == "low"

    def test_empty_state_defaults_to_medium(self) -> None:
        """空 state：无图、标题正文空 → medium（非 high，无敏感词）。"""
        assert _classify_publish_risk({}) == "medium"

    def test_high_sensitive_word_overrides_medium(self) -> None:
        """敏感词命中优先于 medium 特征（缺图+敏感词 → high）。"""
        state = _low_risk_state()
        state["visual_plan"]["image_paths"] = []
        state["copy_content"]["body_text"] = "保证收益高回报理财"
        assert _classify_publish_risk(state) == "high"


# ── _auto_approve_enabled ──


class TestAutoApproveEnabled:
    def test_default_false_when_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未设置 → False。"""
        monkeypatch.delenv("AUTO_APPROVE_LOW_RISK", raising=False)
        assert _auto_approve_enabled() is False

    def test_true_when_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "yes")
        assert _auto_approve_enabled() is True

    def test_true_when_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "1")
        assert _auto_approve_enabled() is True

    def test_false_when_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "no")
        assert _auto_approve_enabled() is False

    def test_false_when_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "false")
        assert _auto_approve_enabled() is False

    def test_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "TRUE")
        assert _auto_approve_enabled() is True

    def test_whitespace_tolerant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "  true  ")
        assert _auto_approve_enabled() is True


# ── _should_auto_approve ──


class TestShouldAutoApprove:
    def test_low_and_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
        assert _should_auto_approve(_low_risk_state()) is True

    def test_low_but_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AUTO_APPROVE_LOW_RISK", raising=False)
        assert _should_auto_approve(_low_risk_state()) is False

    def test_high_never_auto_approve_even_if_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """high 风险永不自动放行（即使配置开）。"""
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
        state = _low_risk_state()
        state["copy_content"]["selected_title"] = "处方药推荐"
        assert _should_auto_approve(state) is False

    def test_medium_never_auto_approve_even_if_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """medium 风险永不自动放行（即使配置开）。"""
        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
        state = _low_risk_state()
        state["visual_plan"]["image_paths"] = []
        assert _should_auto_approve(state) is False


# ── review_gate_node ──


def _interruption_raised(*_args: object, **_kwargs: object) -> None:
    """Sentinel: interrupt() should NOT be called on the auto-pass path."""
    raise AssertionError("interrupt() must not be called on auto-pass path")


class TestReviewGateNodeAutoPass:
    @pytest.mark.asyncio
    async def test_auto_pass_when_low_and_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """low + 配置开 → approved + auto_low_risk audit + PUBLISHING，不调 interrupt。"""
        from backend.agents.nodes import review_gate as rg

        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
        with patch.object(rg, "interrupt", _interruption_raised):
            result = await rg.review_gate_node(_low_risk_state(), store=None)  # type: ignore[arg-type]
        assert result["human_feedback"]["decision"] == ContentStatus.APPROVED
        assert result["human_feedback"]["source"] == "auto_low_risk"
        assert result["phase"] == WorkflowPhase.PUBLISHING

    @pytest.mark.asyncio
    async def test_no_auto_pass_calls_interrupt_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """配置关 → 不自动放行，调 interrupt() 等人工。"""
        from backend.agents.nodes import review_gate as rg

        monkeypatch.delenv("AUTO_APPROVE_LOW_RISK", raising=False)
        called = {"v": False}

        def _fake_interrupt(payload: dict) -> dict:
            called["v"] = True
            assert payload["gate"] == "review"
            return {"decision": "approved", "comments": ""}

        with patch.object(rg, "interrupt", _fake_interrupt):
            result = await rg.review_gate_node(_low_risk_state(), store=None)  # type: ignore[arg-type]
        assert called["v"] is True
        # On resume with approved → PUBLISHING + human_feedback written by node
        assert result["phase"] == WorkflowPhase.PUBLISHING
        assert result["human_feedback"]["decision"] == "approved"

    @pytest.mark.asyncio
    async def test_no_auto_pass_for_high_even_if_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """high 风险 + 配置开 → 仍调 interrupt 等审（永不自动放行）。"""
        from backend.agents.nodes import review_gate as rg

        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
        state = _low_risk_state()
        state["copy_content"]["selected_title"] = "处方药代购"
        called = {"v": False}

        def _fake_interrupt(payload: dict) -> dict:
            called["v"] = True
            return {"decision": "needs_revision"}

        with patch.object(rg, "interrupt", _fake_interrupt):
            result = await rg.review_gate_node(state, store=None)  # type: ignore[arg-type]
        assert called["v"] is True
        assert result["phase"] == WorkflowPhase.CREATING
        assert result["human_feedback"]["decision"] == "needs_revision"

    @pytest.mark.asyncio
    async def test_no_auto_pass_for_medium_even_if_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """medium 风险 + 配置开 → 仍调 interrupt 等审。"""
        from backend.agents.nodes import review_gate as rg

        monkeypatch.setenv("AUTO_APPROVE_LOW_RISK", "true")
        state = _low_risk_state()
        state["visual_plan"]["image_paths"] = []
        called = {"v": False}

        def _fake_interrupt(payload: dict) -> dict:
            called["v"] = True
            assert payload["review_summary"]["risk"] == "medium"
            return {"decision": "approved"}

        with patch.object(rg, "interrupt", _fake_interrupt):
            result = await rg.review_gate_node(state, store=None)  # type: ignore[arg-type]
        assert called["v"] is True
        assert result["phase"] == WorkflowPhase.PUBLISHING

    @pytest.mark.asyncio
    async def test_rejected_decision_routes_to_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """rejected → phase=ERROR（terminal）。"""
        from backend.agents.nodes import review_gate as rg

        monkeypatch.delenv("AUTO_APPROVE_LOW_RISK", raising=False)

        def _fake_interrupt(payload: dict) -> dict:
            return {"decision": "rejected"}

        with patch.object(rg, "interrupt", _fake_interrupt):
            result = await rg.review_gate_node(_low_risk_state(), store=None)  # type: ignore[arg-type]
        assert result["phase"] == WorkflowPhase.ERROR
        assert result["human_feedback"]["decision"] == "rejected"

    @pytest.mark.asyncio
    async def test_interrupt_payload_has_gate_review(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """interrupt payload 带 gate='review' 供 derive_status 识别 awaiting_review。"""
        from backend.agents.nodes import review_gate as rg

        monkeypatch.delenv("AUTO_APPROVE_LOW_RISK", raising=False)
        captured: dict = {}

        def _fake_interrupt(payload: dict) -> dict:
            captured.update(payload)
            return {"decision": "approved"}

        with patch.object(rg, "interrupt", _fake_interrupt):
            await rg.review_gate_node(_low_risk_state(), store=None)  # type: ignore[arg-type]
        assert captured["gate"] == "review"
        assert "review_summary" in captured
