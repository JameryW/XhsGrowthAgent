"""Unit tests for Phase-7 visibility contracts (ledger schemes 37-42)."""

from __future__ import annotations

import math

import pytest

from backend.services.visibility_contracts import (
    AccountBindingError,
    GoldenSuiteCase,
    MatrixFingerprintLedger,
    NoteFingerprint,
    StorageTier,
    account_binding_payload,
    assert_account_binding,
    build_golden_suite_manifest,
    build_semantic_id_path,
    build_shooting_plan,
    detect_cross_account_collisions,
    evaluate_golden_suite,
    fingerprint_similarity,
    geo_cite_score,
    plan_long_article,
    plan_storage_tier,
    rank_geo_keywords,
    semantic_id_coverage,
    semantic_id_missing_levels,
)


def test_geo_cite_score_matches_formula_and_prefers_low_supply() -> None:
    assert geo_cite_score(intent_specificity=1.0, search_demand=9.0) == round(math.log1p(9.0), 6)
    crowded = geo_cite_score(
        intent_specificity=1.0,
        search_demand=9.0,
        high_density_supply_count=3.0,
        evidence_dispersion_penalty=1.0,
    )
    assert crowded == round(math.log1p(9.0) / 5.0, 6)


def test_rank_geo_keywords_sorts_and_limits() -> None:
    ranked = rank_geo_keywords(
        [
            {"keyword": "泛词", "intent_specificity": 0.2, "search_demand": 100},
            {"keyword": "长尾词", "intent_specificity": 1.0, "search_demand": 9},
        ],
        limit=1,
    )
    assert [item.keyword for item in ranked] == ["长尾词"]
    assert ranked[0].as_dict()["score"] > 0


def test_semantic_id_path_coverage_and_missing_levels() -> None:
    path = build_semantic_id_path("出行", "川西自驾", "情侣", "坦克300", "冬季防滑链实测")
    text = "川西自驾 情侣 坦克300 冬季防滑链实测"
    assert semantic_id_coverage(text, path) == 0.8
    assert semantic_id_missing_levels(text, path) == ("L1",)
    with pytest.raises(ValueError):
        build_semantic_id_path("出行", "", "情侣", "坦克300", "结论")


def test_collision_detection_skips_same_account_and_flags_similarity() -> None:
    candidate = NoteFingerprint(
        note_id="n1",
        account_id="a1",
        title="川西自驾攻略",
        body="坦克300 冬季路况",
        visual_template="route-map",
        published_at="2026-11-20T10:00:00+08:00",
    )
    same_account = NoteFingerprint(note_id="n2", account_id="a1", title="川西自驾攻略")
    other = NoteFingerprint(
        note_id="n3",
        account_id="a2",
        title="川西自驾攻略",
        body="坦克300 冬季路况",
        visual_template="route-map",
        published_at="2026-11-20T12:00:00+08:00",
    )
    ledger = MatrixFingerprintLedger([same_account, other])
    findings = ledger.find(candidate)
    assert len(findings) == 1
    assert findings[0].other_note_id == "n3"
    assert "topic_similarity" in findings[0].reasons
    assert "schedule_too_close" in findings[0].reasons
    assert fingerprint_similarity(candidate, other) > 0.5


def test_collision_detection_respects_window() -> None:
    candidate = NoteFingerprint(
        note_id="n1",
        account_id="a1",
        title="同一个选题",
        published_at="2026-11-20T10:00:00+08:00",
    )
    old = NoteFingerprint(
        note_id="n2",
        account_id="a2",
        title="同一个选题",
        published_at="2026-11-10T10:00:00+08:00",
    )
    assert detect_cross_account_collisions(candidate, [old], window_hours=72) == []


def test_account_binding_error_and_payload() -> None:
    assert account_binding_payload("acct-a", "acct-a")["ok"] is True
    payload = account_binding_payload("acct-a", "acct-b")
    assert payload["ok"] is False
    assert payload["code"] == "account_binding_mismatch"
    with pytest.raises(AccountBindingError) as excinfo:
        assert_account_binding("acct-a", "acct-b")
    assert excinfo.value.status_code == 409
    assert excinfo.value.as_dict()["expected_account_id"] == "acct-a"
    assert_account_binding("", "anything")


def test_shooting_plan_and_long_article_boundary() -> None:
    plan = build_shooting_plan("travel", body="x" * 800, poi="成都东站")
    assert [segment.purpose for segment in plan.hook_segments] == [
        "visual_disruption",
        "focal_zoom",
    ]
    assert plan.long_article is True
    assert plan.poi == "成都东站"
    short = plan_long_article("x" * 799)
    assert short.mode == "standard"
    long = plan_long_article("x" * 800, section_chars=400)
    assert long.mode == "long_article"
    assert long.render_pages == 2


def test_storage_tier_boundaries_and_compaction() -> None:
    assert plan_storage_tier(age_hours=47.9).tier is StorageTier.HOT
    assert plan_storage_tier(age_hours=48, snapshots_collected=10).tier is StorageTier.WARM
    folded = plan_storage_tier(age_hours=48, snapshots_collected=10)
    assert folded.checkpoint_folding is True
    assert folded.retain_full_events is False
    assert plan_storage_tier(age_hours=24 * 91).tier is StorageTier.COLD
    assert plan_storage_tier(age_hours=100, status="running").tier is StorageTier.HOT


def test_golden_suite_manifest_and_gate() -> None:
    manifest = build_golden_suite_manifest()
    assert manifest["case_count"] == 50
    assert len(manifest["category_counts"]) == 8
    passed = evaluate_golden_suite(
        policy_compliance_recall=1.0,
        plad_human_pass_rate=0.9,
        cross_account_collision_leak=0,
        context_prefix_cache_hit_ratio=0.85,
    )
    assert passed["passed"] is True
    failed = evaluate_golden_suite(
        policy_compliance_recall=0.99,
        plad_human_pass_rate=0.89,
        cross_account_collision_leak=1,
        context_prefix_cache_hit_ratio=0.84,
    )
    assert failed["passed"] is False
    assert set(failed["failed_gates"]) == {
        "policy_compliance_recall",
        "plad_human_pass_rate",
        "cross_account_collision_leak",
        "context_prefix_cache_hit_ratio",
    }
    custom = build_golden_suite_manifest([GoldenSuiteCase("c1", "geo_gap")])
    assert custom["case_count"] == 1
