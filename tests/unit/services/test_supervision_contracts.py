from __future__ import annotations

import pytest

from backend.services.supervision_contracts import (
    LAYER_SCHEMES,
    AoiInputs,
    Belief,
    ConsolidationAction,
    KnowledgeGap,
    PersistentFact,
    PreCoMemConsolidator,
    PreferenceQuestion,
    ProfileHypothesis,
    RelationalState,
    SourceCard,
    amortized_voi,
    build_gap_highlights,
    compile_reasoning_state,
    compute_aoi,
    detect_knowledge_gaps,
    effective_surprisal,
    evaluate_maturity,
    insert_source_card,
    promote_hypothesis,
    rehearsal_gate,
    select_questions,
)


def test_compute_aoi_balances_value_and_human_burden() -> None:
    report = compute_aoi(AoiInputs(delivered_value=300.0, api_cost=2.0, human_minutes=30.0))
    assert report.total_cost == 32.0
    assert report.aoi == pytest.approx(9.375)
    assert report.value_per_minute == pytest.approx(10.0)
    assert report.reasons == ("computed",)


def test_compute_aoi_zero_cost_and_validation() -> None:
    empty = compute_aoi(AoiInputs(delivered_value=0.0))
    assert empty.aoi == 0.0
    assert empty.value_per_minute == 0.0
    assert empty.reasons == ("no_cost", "no_human_minutes")
    weighted = compute_aoi(
        AoiInputs(delivered_value=100.0, api_cost=0.0, human_minutes=10.0, human_weight=2.0)
    )
    assert weighted.aoi == pytest.approx(5.0)
    with pytest.raises(ValueError):
        compute_aoi(AoiInputs(delivered_value=1.0, human_weight=-1.0))


def test_rehearsal_gate_promotes_on_full_agreement() -> None:
    result = rehearsal_gate([True] * 20, [True] * 20)
    assert result.promote is True
    assert result.agreement_rate == 1.0
    assert result.reasons == ("promote_auto_approve",)


def test_rehearsal_gate_blocks_thin_or_disagreeing_samples() -> None:
    thin = rehearsal_gate([True] * 5, [True] * 5)
    assert thin.promote is False
    assert thin.reasons == ("insufficient_samples",)
    disagreeing = rehearsal_gate([True] * 18 + [False] * 2, [True] * 20)
    assert disagreeing.promote is False
    assert disagreeing.agreement_rate == pytest.approx(0.9)
    assert disagreeing.reasons == ("agreement_below_threshold",)
    empty = rehearsal_gate([], [])
    assert empty.promote is False
    assert empty.samples == 0
    with pytest.raises(ValueError):
        rehearsal_gate([True], [])


def test_amortized_voi_uses_future_reuse() -> None:
    question = PreferenceQuestion("q1", "标题长度偏好", 0.8, 2.0, 0.5)
    assert amortized_voi(question) == pytest.approx(1.1)
    assert amortized_voi(question, future_tasks=4) == pytest.approx(5.9)
    one_off = PreferenceQuestion("q2", "本次拍摄地点", 0.9, 5.0, 0.5, reusable_across_weeks=False)
    assert amortized_voi(one_off, future_tasks=10) == pytest.approx(-0.5)


def test_select_questions_keeps_only_top_leverage_question() -> None:
    questions = [
        PreferenceQuestion("q1", "价格区间偏好", 0.9, 3.0, 0.2),
        PreferenceQuestion("q2", "语气偏好", 0.2, 1.0, 0.5),
        PreferenceQuestion("q3", "封面风格偏好", 0.5, 1.0, 0.1),
        PreferenceQuestion("q4", "一次性细节", 0.9, 9.0, 0.1, reusable_across_weeks=False),
    ]
    selected = select_questions(questions, max_questions=1)
    assert [item.question.question_id for item in selected if item.accepted] == ["q1"]
    assert selected[0].question.question_id == "q1"
    assert selected[0].amortized_voi == pytest.approx(2.5)
    assert len(selected) == 4
    with pytest.raises(ValueError):
        select_questions(questions, top_ratio=1.5)


def test_precomem_routes_observation_by_surprisal() -> None:
    consolidator = PreCoMemConsolidator()
    belief = Belief("b1", "旺季需提前7天订车")
    maintain = consolidator.decide("旺季需提前7天订车", belief)
    assert maintain.action is ConsolidationAction.MAINTAIN
    assert maintain.reason == "consistent_with_belief"
    profile = consolidator.decide("淡季免押金可随时提车", belief)
    assert profile.action is ConsolidationAction.PROFILE
    assert profile.reason == "ambiguous_signal_waiting_room"
    correct = consolidator.decide("完全无关的新政策说明", belief, contradiction=1.0)
    assert correct.action is ConsolidationAction.CORRECT
    assert correct.reason == "reliable_contradiction"
    assert 0.45 <= profile.surprisal < 0.75


def test_precomem_thresholds_and_hypothesis_promotion() -> None:
    with pytest.raises(ValueError):
        PreCoMemConsolidator(profile_threshold=0.8, correct_threshold=0.5)
    confirmed = promote_hypothesis(
        ProfileHypothesis("h1", "客户更在意免押金", corroborations=2, weeks_observed=2)
    )
    assert confirmed.action is ConsolidationAction.CORRECT
    assert confirmed.reason == "hypothesis_confirmed"
    assert confirmed.surprisal == pytest.approx(0.6)
    waiting = promote_hypothesis(
        ProfileHypothesis("h2", "客户更在意车龄", corroborations=1, weeks_observed=3)
    )
    assert waiting.action is ConsolidationAction.PROFILE
    assert waiting.reason == "awaiting_corroboration"


def test_effective_surprisal_blends_divergence_and_contradiction() -> None:
    belief = Belief("b1", "旺季需提前7天订车")
    identical = effective_surprisal("旺季需提前7天订车", belief)
    assert identical == 0.0
    contradiction = effective_surprisal("旺季需提前7天订车", belief, contradiction=1.0)
    assert contradiction == pytest.approx(0.35)
    mixed = effective_surprisal("淡季免押金", belief, contradiction=0.5)
    assert 0.0 < mixed < 1.0


def test_compile_reasoning_state_activates_and_masks() -> None:
    facts = [
        PersistentFact("f_off", "11月淡季免押金", scope=("淡季",)),
        PersistentFact("f_nat", "国庆旺季涨价20%", scope=("国庆",)),
        PersistentFact("f_old", "2025年日均499", superseded_by="f_new"),
        PersistentFact("f_new", "2026年日均459"),
    ]
    relations = [
        RelationalState("f_new", "supersedes", "f_old"),
        RelationalState("f_off", "applies_with", "f_new"),
    ]
    reasoning = compile_reasoning_state(
        facts,
        relations,
        request_context=("淡季", "11月"),
        current_date="2026-11-20",
    )
    assert reasoning.activated == ("f_off", "f_new")
    assert reasoning.masked == ("f_nat", "f_old")
    assert reasoning.instructions[0] == "激活：11月淡季免押金；2026年日均459"
    assert reasoning.instructions[1] == "屏蔽：f_nat；f_old"
    assert reasoning.instructions[2] == "关联：f_off-applies_with->f_new"
    assert reasoning.render().count("\n") == 2


def test_compile_reasoning_state_handles_empty_inputs() -> None:
    reasoning = compile_reasoning_state([])
    assert reasoning.instructions == ("激活：无", "屏蔽：无", "关联：无")
    assert reasoning.activated == ()
    expired = compile_reasoning_state(
        [PersistentFact("f1", "旧档期", valid_until="2026-01-01")],
        current_date="2026-11-20",
    )
    assert expired.masked == ("f1",)


def test_detect_knowledge_gaps_flags_topics_and_metrics() -> None:
    draft = "折多山垭口需要防滑链，日均租金459元"
    gaps = detect_knowledge_gaps(draft, required_topics=("防滑链", "高反药"))
    assert [(gap.span, gap.reason) for gap in gaps] == [
        ("高反药", "missing_required_topic"),
        ("459元", "unsupported_metric"),
    ]
    assert gaps[0].severity == "high"
    supported = detect_knowledge_gaps(
        draft,
        required_topics=("防滑链",),
        supported_metrics=("459元",),
    )
    assert supported == ()


def test_gap_highlights_and_source_card_insertion() -> None:
    gaps = (KnowledgeGap("高反药", "missing_required_topic", "high"),)
    cards = [
        SourceCard("c1", "川西高反应对", "11月折多山建议备高反药与氧气瓶", "https://x"),
        SourceCard("c2", "秋季穿搭", "奶油色针织衫"),
    ]
    highlights = build_gap_highlights(gaps, cards)
    assert len(highlights) == 1
    assert [card.card_id for card in highlights[0].cards] == ["c1"]
    draft = "折多山需要高反药"
    enriched = insert_source_card(draft, gaps[0], cards[0])
    assert enriched.startswith("折多山需要高反药（补充：")
    assert "来源：川西高反应对" in enriched
    missing_span = insert_source_card("折多山垭口", gaps[0], cards[0])
    assert missing_span.startswith("折多山垭口")
    assert missing_span.endswith("）")


def test_maturity_scorecard_reports_gaps_for_empty_rollout() -> None:
    scorecard = evaluate_maturity({})
    assert scorecard.overall_ratio == 0.0
    assert scorecard.gates_passed is False
    assert len(scorecard.gaps) > 0
    assert scorecard.next_actions == scorecard.gaps[:3]
    assert [layer.layer for layer in scorecard.layers] == list(LAYER_SCHEMES)


def test_maturity_scorecard_passes_with_full_rollout_and_metrics() -> None:
    landed = {layer: schemes for layer, schemes in LAYER_SCHEMES.items()}
    metrics = {
        "layer1": {"db_size_reduction": -0.8, "privacy_residual": 0.0},
        "layer2": {"cache_hit_ratio": 0.9, "compaction_violation_rate": 0.0},
        "layer3": {"gui_token_saving": 0.85, "pass_power_k": 0.96},
        "layer4": {"detection_delay": 1.0},
        "layer5": {"human_minutes": 30.0, "aoi_trend": 0.1},
    }
    scorecard = evaluate_maturity(landed, metrics=metrics)
    assert scorecard.overall_ratio == 1.0
    assert scorecard.gates_passed is True
    assert scorecard.gaps == ()
    assert scorecard.next_actions == ()


def test_maturity_scorecard_counts_partial_rollout() -> None:
    scorecard = evaluate_maturity({"layer1": ("19", "#19"), "layer5": ("#3",)})
    assert scorecard.layers[0].landed == ("#19",)
    assert scorecard.layers[0].ratio == pytest.approx(0.25)
    assert scorecard.overall_ratio == pytest.approx(2 / 33, abs=1e-3)
    assert scorecard.gates_passed is False
    assert "layer1:metric:db_size_reduction" in scorecard.gaps
