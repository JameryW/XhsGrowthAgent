"""Unit tests for Phase-8 interaction contracts (ledger schemes 43-48)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.services.interaction_contracts import (
    DmCandidate,
    DmStratum,
    EvergreenCandidate,
    SceneVisualMemoryBank,
    StaleReviewETagError,
    VisualDna,
    allocate_dm_quota,
    assert_review_etag,
    build_revival_plan,
    build_terminal_decision_card,
    build_two_hop_reply,
    build_visual_directive,
    classify_dm_candidate,
    compute_review_etag,
    contains_external_contact,
    evaluate_local_request,
    generate_boot_token,
    is_loopback_host,
    project_tool_output,
    scan_evergreen_notes,
    should_escalate,
)


def test_local_request_guard_blocks_rebinding_and_cswsh() -> None:
    assert is_loopback_host("127.0.0.1:8000") is True
    assert is_loopback_host("[::1]:8000") is True
    assert is_loopback_host("evil.example") is False
    assert evaluate_local_request(host="evil.example").status_code == 421
    missing_origin = evaluate_local_request(host="127.0.0.1:8000", is_websocket=True)
    assert missing_origin.status_code == 403
    assert missing_origin.reason == "websocket_origin_missing"
    bad_origin = evaluate_local_request(
        host="127.0.0.1:8000",
        origin="https://evil.example",
        method="POST",
    )
    assert bad_origin.status_code == 403
    bad_token = evaluate_local_request(
        host="127.0.0.1:8000",
        method="POST",
        boot_token="secret",
        presented_token="wrong",
    )
    assert bad_token.status_code == 403
    assert bad_token.reason == "boot_token_mismatch"
    ok = evaluate_local_request(
        host="127.0.0.1:8000",
        origin="http://localhost:5173",
        method="POST",
        boot_token="secret",
        presented_token="secret",
    )
    assert ok.allowed is True


def test_boot_token_is_ephemeral_and_long_enough() -> None:
    first = generate_boot_token()
    second = generate_boot_token()
    assert len(first) >= 16
    assert first != second


def test_dm_strata_classification() -> None:
    assert (
        classify_dm_candidate(DmCandidate("u1", base_conversion=0.30, intervention_conversion=0.55))
        is DmStratum.PERSUADABLE
    )
    assert (
        classify_dm_candidate(DmCandidate("u2", base_conversion=0.80, intervention_conversion=0.84))
        is DmStratum.SURE_THING
    )
    assert (
        classify_dm_candidate(DmCandidate("u3", base_conversion=0.20, intervention_conversion=0.21))
        is DmStratum.LOST_CAUSE
    )
    assert (
        classify_dm_candidate(DmCandidate("u4", base_conversion=0.20, intervention_conversion=0.10))
        is DmStratum.SLEEPING_DOG
    )


def test_dm_quota_prioritizes_persuadables_and_defers_sure_things() -> None:
    candidates = [
        DmCandidate("sure", base_conversion=0.80, intervention_conversion=0.84),
        DmCandidate("persuadable", base_conversion=0.30, intervention_conversion=0.60),
        DmCandidate("hostile", base_conversion=0.2, intervention_conversion=0.1, is_hostile=True),
    ]
    allocations = allocate_dm_quota(candidates, daily_quota=1)
    by_id = {item.user_id: item for item in allocations}
    assert by_id["persuadable"].action == "full_fsm"
    assert by_id["persuadable"].quota_cost == 1
    assert by_id["sure"].action == "defer_next_day"
    assert by_id["hostile"].action == "silent_block"
    assert allocate_dm_quota(candidates, daily_quota=0)[0].action in {
        "defer_next_day",
        "full_fsm",
    }


def test_two_hop_reply_strips_external_contacts() -> None:
    assert contains_external_contact("加微信 abc12345 聊")
    assert contains_external_contact("电话 13800138000")
    assert contains_external_contact("看 https://evil.example")
    assert not contains_external_contact("戳我头像发【档期】")
    reply = build_two_hop_reply("价格 399，加微信 abc12345", "川西")
    assert "abc12345" not in reply
    assert "微信" not in reply
    assert "【川西】" in reply


def test_visual_memory_bank_and_directive() -> None:
    bank = SceneVisualMemoryBank(
        dna_by_account={
            "acct": VisualDna(
                account_id="acct",
                primary_color="#123456",
                subject_tokens=("坦克300",),
                negative_tokens=("荧光绿",),
            )
        }
    )
    directive = build_visual_directive(bank, "acct", "travel")
    assert directive["palette"]["primary"] == "#123456"
    assert directive["scene"] == "travel"
    assert directive["subject_tokens"] == ["坦克300"]
    assert "路线地图" in " ".join(directive["preferred_layouts"])
    high = bank.adapt_scene("travel", feedback_score=100)
    assert high.weight == 2.0
    low = bank.adapt_scene("travel", feedback_score=-100)
    assert low.weight == 0.5


def test_tool_projection_and_escalation() -> None:
    projection = project_tool_output(
        "xhs_trending",
        {"notes": ["x" * 2000], "keywords": ["川西"], "captured_at": "now", "junk": "drop"},
    )
    assert "junk" not in projection.payload
    assert projection.projected_chars <= 6000
    assert projection.retention_ratio <= 1.0
    assert should_escalate(note_count=1, sample_credibility=0.1).tier == "tier1"
    assert should_escalate(note_count=5, sample_credibility=0.4).tier == "tier2"
    assert should_escalate(note_count=1, sample_credibility=0.1, is_commercial=True).tier == "tier2"


def test_evergreen_scan_and_revival_plan() -> None:
    notes = [
        {"note_id": "old", "age_days": 150, "collect_rate": 0.20, "search_traffic_delta": 0.0},
        {"note_id": "new", "age_days": 30, "collect_rate": 0.01, "search_traffic_delta": 0.0},
        {"note_id": "falling", "age_days": 40, "collect_rate": 0.20, "search_traffic_delta": -0.40},
    ]
    candidates = scan_evergreen_notes(notes)
    assert {item.note_id for item in candidates} == {"old", "falling"}
    plan = build_revival_plan(
        EvergreenCandidate("old", age_days=150, collect_rate=0.2, search_traffic_delta=0.0),
        now=datetime(2026, 11, 23, tzinfo=UTC),
    )
    assert "2026/2027" in plan.title_suffix
    assert plan.estimated_cost_ratio == 0.2
    assert "最新实测版" in plan.pinned_comment
    assert scan_evergreen_notes([]) == []


def test_review_etag_and_terminal_card() -> None:
    etag = compute_review_etag("thread", "checkpoint", "abc")
    assert len(etag) == 16
    assert etag == compute_review_etag("thread", "checkpoint", "abc")
    assert_review_etag("", etag)
    assert_review_etag(etag, etag)
    with pytest.raises(StaleReviewETagError):
        assert_review_etag("stale", etag)
    card = build_terminal_decision_card(
        account_id="acct",
        plad_score=0.9,
        rqgm_score=0.8,
        semantic_id_complete=True,
        max_cosine=0.4,
        review_etag=etag,
    )
    rendered = card.render()
    assert "[绑定账号: @acct]" in rendered
    assert "PLAD 人类语感: 0.9 PASS" in rendered
    assert "OneSearch 5-SID: PASS" in rendered
    assert "etag:" in rendered
