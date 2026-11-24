"""Tests for phase-11 verification contracts."""

from __future__ import annotations

from backend.services.verification_contracts import (
    CardSample,
    MetricClaim,
    MosaicSessionScheduler,
    SessionProposal,
    SessionStats,
    SessionType,
    assert_typed_completion,
    audit_variant_claims,
    build_bounded_query_batches,
    detect_card_rewind,
    extract_numeric_claims,
    scoped_revision,
    verify_metric_claims,
)


def test_extract_numeric_claims_uses_context_keys() -> None:
    claims = extract_numeric_claims("押金3000元，租金每天500元。")
    values = {claim.key: claim.value for claim in claims}
    assert values["押金"] == "3000"
    assert values["租金每天"] == "500"


def test_audit_variant_claims_resolves_dispute_from_evidence() -> None:
    report = audit_variant_claims(
        ["押金3000元", "押金5000元"],
        evidence=["官方规则：押金5000元"],
    )
    assert len(report.disputed) == 1
    assert report.disputed[0].resolved is True
    assert report.disputed[0].resolution == "5000"
    assert report.blocked is False


def test_audit_consensus_claim_without_evidence_blocks() -> None:
    report = audit_variant_claims(["押金3000元", "押金3000元"])
    assert report.consensus_unsupported == ("押金",)
    assert report.blocked is True
    assert "押金" in report.unverified_claims


def test_audit_dispute_blocks_when_evidence_supports_both_values() -> None:
    report = audit_variant_claims(
        ["押金3000元", "押金5000元"],
        evidence=["活动期押金3000元，日常押金5000元"],
    )
    assert report.disputed[0].resolved is False
    assert report.blocked is True


def test_commercial_keyword_alias_satisfies_disclosure_effect() -> None:
    report = assert_typed_completion(
        title="合作款",
        body="这次蒲公英合作实测了三条路线。",
        effects=["蒲公英"],
    )
    assert all(
        issue.reason != "commercial_note_without_disclosure_effect" for issue in report.issues
    )


def test_typed_completion_blocks_decision_without_evidence() -> None:
    report = assert_typed_completion(
        title="t",
        body="b",
        decisions=[{"decision": "pick", "evidence_ids": []}],
        evidence_ids=["e1"],
    )
    assert report.blocked is True
    assert report.issues[0].edge == "grounding"


def test_typed_completion_blocks_missing_card_reference() -> None:
    report = assert_typed_completion(
        title="t",
        body="详见第 2 张图",
        carousel=["cover"],
    )
    assert any(issue.reason == "referenced_card_missing" for issue in report.issues)


def test_typed_completion_accepts_full_graph() -> None:
    report = assert_typed_completion(
        title="路线图",
        body="见图 2，左滑看对比，置顶评论领表。",
        carousel=["cover", "comparison", "save-list"],
        decisions=[
            {
                "decision": "pin",
                "evidence_ids": ["e1"],
                "effect": "pinned_comment",
            }
        ],
        effects=["pinned_comment"],
        evidence_ids=["e1"],
    )
    assert report.blocked is False
    assert report.issues == ()


def test_typed_completion_requires_commercial_disclosure_effect() -> None:
    report = assert_typed_completion(
        title="合作笔记",
        body="这次和品牌一起实测。",
        effects=[],
    )
    assert report.blocked is True
    assert any(
        issue.reason == "commercial_note_without_disclosure_effect" for issue in report.issues
    )


def test_mosaic_scheduler_normalizes_and_penalizes() -> None:
    scheduler = MosaicSessionScheduler({SessionType.POLISH: SessionStats(mean=10.0, stddev=2.0)})
    positive = scheduler.evaluate(
        SessionProposal(SessionType.POLISH, expected_reward=13.0),
        current_session_count=0,
    )
    negative = scheduler.evaluate(
        SessionProposal(SessionType.POLISH, expected_reward=9.0),
        current_session_count=0,
    )
    penalized = scheduler.evaluate(
        SessionProposal(SessionType.POLISH, expected_reward=13.0),
        current_session_count=2,
    )
    assert positive.spawn is True
    assert negative.spawn is False
    assert penalized.penalty < positive.penalty
    assert penalized.spawn is True


def test_scoped_revision_locks_sound_first_opinion() -> None:
    result = scoped_revision(
        {"tone": "warm", "format": "list"},
        {"tone": "cold", "format": "list", "hook": "story"},
        required_fields=("format",),
    )
    assert result.revision["tone"] == "warm"
    assert result.revision["hook"] == "story"
    assert set(result.locked_fields) == {"tone", "format"}
    assert result.rejected_fields == ("tone",)
    assert result.missing_required_fields == ()


def test_scoped_revision_fills_missing_required_from_memory() -> None:
    result = scoped_revision(
        {"tone": "warm"},
        {"audience": "students", "tone": "cold"},
        required_fields=("audience",),
    )
    assert result.revision["audience"] == "students"
    assert "audience" in result.revised_fields
    assert "tone" in result.rejected_fields


def test_detect_card_rewind_on_banned_card() -> None:
    plan = detect_card_rewind(
        [
            CardSample(1, 1.0),
            CardSample(2, 1.1, banned_hits=1),
            CardSample(3, 1.2),
        ],
        baseline_mean=1.0,
        baseline_std=0.1,
    )
    assert plan.action == "rewind"
    assert plan.rewind_to == 1
    assert plan.suspicious_cards == (2,)


def test_detect_card_rewind_on_entropy_spike() -> None:
    plan = detect_card_rewind(
        [CardSample(1, 1.0), CardSample(2, 9.0)],
        baseline_mean=1.0,
        baseline_std=0.5,
    )
    assert plan.action == "rewind"
    assert plan.reason == "card_2_uncertain_or_invalid"


def test_detect_card_rewind_accepts_stable_cards() -> None:
    plan = detect_card_rewind(
        [CardSample(1, 1.0), CardSample(2, 1.1)],
        baseline_mean=1.0,
        baseline_std=0.5,
    )
    assert plan.action == "accept"
    assert plan.rewind_to is None


def test_build_bounded_query_batches_caps_at_three() -> None:
    claims = [MetricClaim("reads", 100, note_id=f"n{index}") for index in range(5)]
    batches = build_bounded_query_batches(claims, max_batches=3)
    assert len(batches) == 3
    assert batches[-1].key == "merged"
    assert len(batches[-1].claim_ids) == 3


def test_verify_metric_claims_matches_ledger() -> None:
    claims = [MetricClaim("reads", 100, note_id="n1", claim_id="c1")]
    ok = verify_metric_claims(claims, {"n1:reads": 100})
    mismatch = verify_metric_claims(claims, {"n1:reads": 101})
    missing = verify_metric_claims(claims, {})
    assert ok.ok is True
    assert ok.batch_count == 1
    assert mismatch.mismatches == ("c1",)
    assert missing.missing == ("c1",)
