"""Tests for phase-10 decision contracts."""

from __future__ import annotations

import math

from backend.services.decision_contracts import (
    PHASE10_ROLLOUT,
    ChecklistItem,
    PolicyQuestion,
    QuestionLogprob,
    SimCandidate,
    ToolReceipt,
    UITraceStep,
    UITraceTemplate,
    build_rollout_plan,
    evaluate_handoff_checklist,
    evaluate_polish_acceptance,
    evaluate_question_logprobs,
    evaluate_stage0_skip,
    extract_action_claims,
    filter_unusable_reply,
    jev_decision_gate,
    replay_ui_trace,
    risk_aware_polish_gate,
    sim_decision_sensitivity_gate,
)


def test_question_logprobs_normalize_and_flag_violation() -> None:
    scores = evaluate_question_logprobs(
        [{"question_id": "q1", "yes_logprob": 2.0, "no_logprob": -2.0}],
        [PolicyQuestion("q1", "does it promise a price?")],
    )
    assert len(scores) == 1
    score = scores[0]
    assert score.known is True
    assert score.yes_probability > 0.9
    assert score.blocked is True


def test_unknown_logprobs_are_reported_not_treated_as_safe() -> None:
    scores = evaluate_question_logprobs(
        [QuestionLogprob("q2", math.nan, math.nan)],
        [PolicyQuestion("q2", "unknown")],
    )
    report = jev_decision_gate(
        {"account_id": "a", "title": "t", "body": "b"},
        question_logprobs=[QuestionLogprob("q2", math.nan, math.nan)],
    )
    assert scores[0].known is False
    assert scores[0].blocked is False
    assert "policy_unknown:q2" in report.reasons
    assert report.blocked is False


def test_jev_gate_blocks_missing_field_and_high_violation() -> None:
    report = jev_decision_gate(
        {"account_id": "a", "title": "t"},
        required_fields=("account_id", "title", "body"),
        question_logprobs=[QuestionLogprob("q1", 3.0, -3.0)],
        policy_questions=[PolicyQuestion("q1", "price promise")],
    )
    assert report.blocked is True
    assert any(reason.startswith("required_field:body") for reason in report.reasons)
    assert "policy_violation:q1" in report.reasons


def test_handoff_checklist_requires_all_fields() -> None:
    checklist = evaluate_handoff_checklist(
        [ChecklistItem("date", settled=True), ChecklistItem("budget", settled=False)],
        required_names=("date", "budget", "pickup_region"),
    )
    names = {item.name: item for item in checklist}
    assert names["pickup_region"].settled is False
    report = jev_decision_gate(
        {"account_id": "a", "title": "t", "body": "b"},
        handoff=True,
        checklist=checklist,
    )
    assert report.blocked is True
    assert "handoff_unsettled:pickup_region" in report.reasons


def test_stage0_skip_boundaries() -> None:
    stage = {"title": "标题", "body": "这是一篇结构完整的正文。"}
    assert evaluate_stage0_skip(stage, plad_human_prob=0.82).action == "skip"
    assert evaluate_stage0_skip(stage, plad_human_prob=0.82, banned_word_count=1).action == "polish"
    assert (
        evaluate_stage0_skip(
            stage,
            plad_human_prob=0.82,
            required_sections=("结尾",),
        ).action
        == "polish"
    )
    assert evaluate_stage0_skip({}, plad_human_prob=0.99).action == "polish"


def test_polish_acceptance_requires_gain_and_no_lost_ids() -> None:
    stage0 = {"title": "a", "body": "b"}
    stage1 = {"title": "a2", "body": "b2"}
    too_small = evaluate_polish_acceptance(
        stage0,
        stage1,
        stage0_human_prob=0.60,
        stage1_human_prob=0.62,
    )
    lost = evaluate_polish_acceptance(
        stage0,
        stage1,
        stage0_human_prob=0.60,
        stage1_human_prob=0.70,
        stage0_semantic_ids=("L1", "L2"),
        stage1_semantic_ids=("L1",),
    )
    accepted = evaluate_polish_acceptance(
        stage0,
        stage1,
        stage0_human_prob=0.60,
        stage1_human_prob=0.70,
        stage0_semantic_ids=("L1",),
        stage1_semantic_ids=("L1",),
    )
    assert too_small.action == "revert"
    assert lost.action == "revert"
    assert lost.lost_semantic_ids == ("L2",)
    assert accepted.action == "accept"


def test_risk_aware_gate_skips_stage1_when_stage0_is_good() -> None:
    stage0 = {"title": "标题", "body": "这是一篇结构完整的正文。"}
    assert risk_aware_polish_gate(stage0, plad_human_prob=0.9).action == "skip"
    assert risk_aware_polish_gate(stage0, plad_human_prob=0.5).action == "polish"


def _trace_template() -> UITraceTemplate:
    return UITraceTemplate(
        name="publish",
        steps=(
            UITraceStep("upload", "click", selector="#upload"),
            UITraceStep("title", "fill", selector="#title", slot="title"),
            UITraceStep("submit", "click", selector="#submit"),
        ),
    )


def test_ui_trace_reuses_rewrites_and_rejects_unknown_selector() -> None:
    plan = replay_ui_trace(
        _trace_template(),
        {"selectors": {"#upload": True, "#title": True}},
        {"title": "hello"},
    )
    assert [decision.action for decision in plan.decisions] == ["reuse", "rewrite", "reject"]
    assert plan.blocked_step == "submit"
    assert plan.needs_vlm is True
    assert plan.reuse_ratio > 0.6


def test_ui_trace_missing_slot_rejects_before_writing() -> None:
    plan = replay_ui_trace(
        _trace_template(),
        {"selectors": {"#upload": True, "#title": True}},
        {},
    )
    assert plan.decisions[-1].reason == "missing_slot_value"
    assert plan.blocked_step == "title"


def test_ui_trace_unknown_modal_rejects() -> None:
    plan = replay_ui_trace(
        _trace_template(),
        {"selectors": {"#upload": True}, "modal": "activity"},
        {"title": "hello"},
        unknown_modal=True,
    )
    assert plan.decisions[0].action == "reject"
    assert plan.decisions[0].needs_vlm is True


def test_sim_sensitivity_locks_order_preserving_pair() -> None:
    report = sim_decision_sensitivity_gate(
        SimCandidate("a", 10.0, {"freshness": 0.2}),
        SimCandidate("b", 7.0, {"freshness": 0.2}),
    )
    assert report.order_preserving is True
    assert report.decision == "lock_a"


def test_sim_sensitivity_escalates_rank_flip() -> None:
    report = sim_decision_sensitivity_gate(
        SimCandidate("a", 10.0, {"freshness": 0.0}),
        SimCandidate("b", 9.95, {"freshness": 1.0}),
        epsilon=0.1,
    )
    assert report.rank_flip_rate >= 0.5
    assert report.decision == "escalate"


def test_unusable_reply_blocks_claim_without_receipt() -> None:
    report = filter_unusable_reply(
        "已帮您查好档期，已锁定车辆。",
        receipts=[ToolReceipt("查好", "succeeded", "slot-1")],
    )
    assert report.blocked is True
    assert report.missing_receipts == ("claim-2",)


def test_unusable_reply_passes_when_all_receipts_exist() -> None:
    report = filter_unusable_reply(
        "已帮您查好档期，已锁定车辆。",
        receipts=[
            ToolReceipt("查好", "succeeded", "slot-1"),
            ToolReceipt("锁定", "succeeded", "order-1"),
        ],
    )
    assert report.blocked is False


def test_hollow_reply_is_blocked_for_concrete_question() -> None:
    report = filter_unusable_reply(
        "亲亲稍等，私信您啦～",
        customer_question="押金多少",
    )
    assert report.hollow is True
    assert report.blocked is True


def test_hollow_reply_is_blocked_without_question() -> None:
    report = filter_unusable_reply("亲亲稍等～")
    assert report.hollow is True
    assert report.blocked is True


def test_action_claim_does_not_match_empty_receipt_action() -> None:
    report = filter_unusable_reply(
        "已帮您查好档期。",
        receipts=[ToolReceipt("", "succeeded", "slot-1")],
    )
    assert report.blocked is True
    assert report.missing_receipts == ("claim-1",)


def test_extract_action_claims_empty_and_multiple() -> None:
    assert extract_action_claims("") == ()
    claims = extract_action_claims("已经登记好了。清单已发送。")
    assert len(claims) == 2


def test_extract_action_claims_ignores_future_and_first_person() -> None:
    assert extract_action_claims("我想预约下周的档期。") == ()
    assert extract_action_claims("您自己确认一下价格。") == ()


def test_rollout_plan_is_four_weeks_and_contains_decision_gate() -> None:
    assert len(PHASE10_ROLLOUT) == 4
    assert build_rollout_plan() is PHASE10_ROLLOUT
    assert "#55" in PHASE10_ROLLOUT[1].plan_ids
