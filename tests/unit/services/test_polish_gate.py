from __future__ import annotations

import pytest

from backend.services import polish_gate
from backend.services.polish_gate import (
    StageAssessment,
    assess_stage,
    decide_after_polish,
    decide_before_polish,
    polish_decision_fields,
    polish_gate_enabled,
)

HUMAN_TITLE = "川西自驾回来，说点实话"
HUMAN_BODY = (
    "本来以为国庆去川西会很堵。结果10月3号出发，折多山垭口排队不到20分钟。"
    "我们开的是1.5T的老车，爬坡确实肉，但没熄火。"
    "住宿提前订的雅江县城，260一晚，干净。"
)
AI_BODY = (
    "首先，川西自驾游是一次非常难忘的体验。其次，我们需要做好充分准备。"
    "此外，建议大家注意高原反应问题。综上所述，川西自驾值得体验。"
    "总而言之，希望这篇攻略对大家有所帮助。"
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(polish_gate.POLISH_GATE_ENV, raising=False)


def test_polish_gate_flag_is_off_by_default() -> None:
    assert polish_gate_enabled() is False


def test_polish_gate_flag_accepts_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv(polish_gate.POLISH_GATE_ENV, value)
        assert polish_gate_enabled() is True
    monkeypatch.setenv(polish_gate.POLISH_GATE_ENV, "0")
    assert polish_gate_enabled() is False


def test_assess_stage_scores_human_text_higher_than_template_text() -> None:
    human = assess_stage(HUMAN_TITLE, HUMAN_BODY)
    ai = assess_stage(HUMAN_TITLE, AI_BODY)
    assert human.ai_likelihood < ai.ai_likelihood
    assert human.human_prob > ai.human_prob
    assert human.human_prob == pytest.approx(1.0 - human.ai_likelihood)
    assert 0.0 <= human.human_prob <= 1.0
    assert human.as_stage() == {"title": HUMAN_TITLE, "body": HUMAN_BODY}


def test_assess_stage_records_banned_words() -> None:
    stage = assess_stage(HUMAN_TITLE, HUMAN_BODY, banned_word_count=2)
    assert stage.banned_word_count == 2
    assert stage.as_dict()["banned_word_count"] == 2
    clamped = assess_stage(HUMAN_TITLE, HUMAN_BODY, banned_word_count=-3)
    assert clamped.banned_word_count == 0


def test_assess_stage_handles_empty_draft() -> None:
    stage = assess_stage("", "")
    assert stage.human_prob == pytest.approx(1.0 - stage.ai_likelihood)
    assert stage.as_dict()["title_chars"] == 0


def test_stage0_with_missing_body_must_be_polished() -> None:
    decision = decide_before_polish(StageAssessment("标题", "", 0.95, 0.05))
    assert decision.action == "polish"
    assert decision.reason == "polish_required:stage0_missing_content"


def test_stage0_with_banned_words_must_be_polished() -> None:
    stage = assess_stage(HUMAN_TITLE, HUMAN_BODY, banned_word_count=1)
    decision = decide_before_polish(stage)
    assert decision.action == "polish"
    assert decision.reason == "polish_required:stage0_banned_words"


def test_stage0_with_missing_sections_must_be_polished() -> None:
    decision = decide_before_polish(
        StageAssessment("标题", "正文内容", 0.95, 0.05),
        required_sections=("费用清单",),
    )
    assert decision.action == "polish"
    assert decision.reason == "polish_required:stage0_missing_sections:费用清单"


def test_stage0_low_human_prob_must_be_polished() -> None:
    decision = decide_before_polish(StageAssessment("标题", "正文内容", 0.5, 0.5))
    assert decision.action == "polish"
    assert decision.reason == "polish_required:stage0_plad_below_skip_threshold"


def test_stage0_human_like_draft_skips_polish() -> None:
    decision = decide_before_polish(StageAssessment("标题", "正文内容", 0.9, 0.1))
    assert decision.action == "skip"
    assert decision.reason == "stage0_already_human_like"


def test_polish_accepted_when_pareto_improvement() -> None:
    stage0 = StageAssessment("标题", "初稿正文", 0.6, 0.4)
    stage1 = StageAssessment("标题", "润色正文", 0.7, 0.3)
    decision = decide_after_polish(stage0, stage1)
    assert decision.action == "accept"
    assert decision.reason == "stage1_pareto_improvement"
    assert decision.human_prob_delta == pytest.approx(0.1)
    assert polish_decision_fields(decision)["de_ai_polish_gate"]["action"] == "accept"


def test_polish_reverted_when_gain_is_too_small() -> None:
    stage0 = StageAssessment("标题", "初稿正文", 0.6, 0.4)
    stage1 = StageAssessment("标题", "润色正文", 0.61, 0.39)
    decision = decide_after_polish(stage0, stage1)
    assert decision.action == "revert"
    assert decision.reason == "stage1_no_significant_human_gain"


def test_polish_reverted_when_semantic_ids_are_lost() -> None:
    stage0 = StageAssessment("标题", "初稿正文", 0.6, 0.4)
    stage1 = StageAssessment("标题", "润色正文", 0.9, 0.1)
    decision = decide_after_polish(
        stage0,
        stage1,
        stage0_semantic_ids=("L4:459元", "L5:防滑链"),
        stage1_semantic_ids=("L4:459元",),
    )
    assert decision.action == "revert"
    assert decision.reason == "stage1_lost_semantic_ids"
    assert decision.lost_semantic_ids == ("L5:防滑链",)


def test_polish_reverted_when_polished_draft_is_empty() -> None:
    stage0 = StageAssessment("标题", "初稿正文", 0.6, 0.4)
    stage1 = StageAssessment("标题", "", 0.9, 0.1)
    decision = decide_after_polish(stage0, stage1)
    assert decision.action == "revert"
    assert decision.reason == "stage1_missing_content"


def test_min_gain_boundary_is_configurable() -> None:
    stage0 = StageAssessment("标题", "初稿正文", 0.6, 0.4)
    stage1 = StageAssessment("标题", "润色正文", 0.65, 0.35)
    assert decide_after_polish(stage0, stage1).action == "accept"
    assert decide_after_polish(stage0, stage1, min_gain=0.06).action == "revert"
