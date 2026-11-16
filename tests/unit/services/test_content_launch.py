"""Tests for phase-3 launch contracts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.services.content_launch import (
    AccountSessionCircuitBreaker,
    SessionState,
    build_risk_signal_strip,
    build_tag_plan,
    classify_root_cause,
    estimate_note_cost,
    evaluate_multimodal_synergy,
    sse_event_frame,
    tag_plan_errors,
)


def test_multimodal_synergy_passes_a_well_composed_plan() -> None:
    report = evaluate_multimodal_synergy(
        "小个子通勤穿搭",
        "三个比例技巧，照着穿就很利落",
        {
            "text_overlay": "3步搞定",
            "layout_style": "极简",
            "image_prompts": ["全身镜面站位", "细节对比"],
        },
        niche="穿搭",
    )
    assert report.passed is True
    assert report.overall >= 60
    assert [item.name for item in report.dimensions] == [
        "complementarity",
        "thumbnail_readability",
        "aesthetic_fit",
    ]


def test_multimodal_synergy_flags_a_pasted_text_plan() -> None:
    text = "这是一段非常长的正文，和图片里的文字完全一模一样，没有互补信息。" * 2
    report = evaluate_multimodal_synergy(
        "标题",
        text,
        {"text_overlay": text, "image_count": 1},
    )
    assert report.passed is False
    assert report.recommendations


def test_tag_plan_distills_three_layers_into_five_to_eight_tags() -> None:
    plan = build_tag_plan(
        ["通勤穿搭", "小个子", "ignore-extra"],
        ["针织衫", "半身裙", "乐福鞋", "extra"],
        ["早秋搭配", "显高技巧", "微胖友好", "extra"],
    )
    assert tag_plan_errors(plan) == []
    assert len(plan.tags) == 8
    assert plan.core.tags == ("通勤穿搭", "小个子")
    assert plan.entity.tags == ("针织衫", "半身裙", "乐福鞋")


def test_tag_plan_reports_missing_entity_layer() -> None:
    plan = build_tag_plan(["通勤穿搭"], [], ["早秋搭配", "显高技巧"])
    assert "entity_tag_count_must_be_2_to_3" in tag_plan_errors(plan)


def test_risk_signal_strip_blocks_on_eligibility_and_novelty() -> None:
    strip = build_risk_signal_strip(
        publish_eligibility={"eligible": False, "reasons": ["违禁词"]},
        evaluation={"decision": "REJECTED", "quality_gate": {"blocked_dimensions": ["compliance"]}},
        novelty={"max_similarity": 0.91, "is_duplicate_risk": True},
        plad={"ai_likelihood": 0.72},
    )
    assert strip.overall == "red"
    assert strip.blocking is True
    assert {signal.code for signal in strip.signals} >= {
        "publish_eligibility",
        "quality_gate",
        "novelty",
        "plad",
    }


def test_risk_signal_strip_is_green_for_clean_signals() -> None:
    strip = build_risk_signal_strip(
        publish_eligibility={"eligible": True},
        evaluation={"decision": "APPROVED", "quality_gate": {"blocked_dimensions": []}},
        novelty={"max_similarity": 0.2, "is_duplicate_risk": False},
        plad={"ai_likelihood": 0.1},
    )
    assert strip.overall == "green"
    assert strip.blocking is False


def test_session_breaker_trips_immediately_on_signature_failure() -> None:
    breaker = AccountSessionCircuitBreaker("acc-1", cooldown_seconds=60)
    breaker.record_failure("signature_unavailable", "signature unavailable")
    assert breaker.snapshot().state is SessionState.OPEN_COOLDOWN
    assert breaker.allow_attempt() is False


def test_session_breaker_recovers_after_cooldown() -> None:
    start = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
    breaker = AccountSessionCircuitBreaker("acc-1", cooldown_seconds=60)
    breaker.record_failure("login_required", "login required", now=start)
    assert breaker.allow_attempt(now=start + timedelta(seconds=59)) is False
    assert breaker.allow_attempt(now=start + timedelta(seconds=61)) is True


def test_session_breaker_degrades_after_three_transient_failures() -> None:
    breaker = AccountSessionCircuitBreaker("acc-1", degraded_threshold=3)
    for _ in range(3):
        breaker.record_failure("timeout", "network timeout")
    assert breaker.snapshot().state is SessionState.DEGRADED
    assert breaker.allow_attempt() is True


def test_root_cause_and_note_cost() -> None:
    assert classify_root_cause(error_code="banned_word", message="违禁词")["bucket"] == (
        "deterministic_compliance_block"
    )
    assert classify_root_cause(error_code="timeout")["retryable"] is True
    cost = estimate_note_cost(
        [
            {"payload": {"prompt_tokens": 1000, "completion_tokens": 500}},
            {"payload": {"prompt_tokens": 2000, "completion_tokens": 500}},
        ]
    )
    assert cost["total_tokens"] == 4000
    assert cost["cost_usd"] == 0.014


def test_sse_event_frame_has_id_event_and_data() -> None:
    frame = sse_event_frame(7, "stage", {"phase": "creating"})
    assert frame.startswith("id: 7\nevent: stage\ndata: ")
    assert frame.endswith("\n\n")
    assert '"phase":"creating"' in frame
