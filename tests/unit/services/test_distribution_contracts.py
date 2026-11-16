"""Tests for phase-6 distribution and replay contracts."""

from __future__ import annotations

from datetime import UTC, datetime

from backend.services.distribution_contracts import (
    FanProfile,
    FanRelationStore,
    audit_note_distribution,
    breakout_lift,
    build_icebreaker,
    compile_public_replay_bundle,
    diagnose_exposure,
    estimate_credibility,
    plan_carousel,
    rank_breakouts,
    score_scenario,
)


def test_credibility_is_zero_at_zero_exposure_and_full_at_maturity() -> None:
    assert estimate_credibility(0, 0) == 0.0
    assert estimate_credibility(1000, 48) == 1.0
    assert estimate_credibility(1000, 48, is_throttled=True) == 0.0


def test_exposure_diagnostic_flags_high_engagement_low_reads() -> None:
    result = diagnose_exposure(
        reads=120,
        age_hours=24,
        ctr=0.08,
        collect_rate=0.05,
        baseline_ctr=0.04,
        baseline_collect_rate=0.03,
        baseline_reads=1000,
    )
    assert result.suspected_throttle is True
    assert result.engagement_above_baseline is True
    assert "reads_below_exposure_floor" in result.reasons


def test_scenario_weights_change_with_mode() -> None:
    metrics = {"engagement": 80, "contract": 60, "visual": 90, "freshness": 70, "novelty": 50}
    assert score_scenario(metrics, "trend") != score_scenario(metrics, "brief")
    assert score_scenario(metrics, "brief") > 0


def test_carousel_plan_has_hook_conclusion_evidence_and_save_list() -> None:
    slides = plan_carousel(6, total_token_budget=1200)
    assert len(slides) == 6
    assert slides[0].role == "hook"
    assert slides[1].role == "conclusion"
    assert slides[-1].role == "save_list"
    assert any(slide.role == "evidence" for slide in slides[2:-1])


def test_breakout_lift_rewards_collects_and_filters_large_accounts() -> None:
    small = breakout_lift(collects=200, likes=80, comments=30, followers=500, age_days=2)
    large = breakout_lift(collects=200, likes=80, comments=30, followers=100000, age_days=2)
    assert small > large
    ranked = rank_breakouts(
        [
            {
                "note_id": "small",
                "collects": 100,
                "likes": 20,
                "comments": 10,
                "followers": 500,
                "age_days": 2,
            },
            {
                "note_id": "large",
                "collects": 100,
                "likes": 20,
                "comments": 10,
                "followers": 50000,
                "age_days": 2,
            },
        ]
    )
    assert [item.note_id for item in ranked] == ["small"]


def test_fan_relation_store_and_icebreaker() -> None:
    store = FanRelationStore()
    store.upsert(FanProfile("u1", "小鹿", ["通勤穿搭"], "returning", interaction_count=2))
    store.upsert(FanProfile("u1", "", ["半身裙"], "returning", interaction_count=1))
    profile = store.get("u1")
    assert profile is not None
    assert profile.interests == ["通勤穿搭", "半身裙"]
    assert "小鹿" in build_icebreaker(profile, "通勤穿搭")


def test_fan_relation_store_persists_across_instances(tmp_path) -> None:
    path = tmp_path / "fans.json"
    first = FanRelationStore(path)
    first.upsert(
        FanProfile(
            "u9",
            "阿岚",
            ["露营"],
            "vip",
            last_interaction=datetime(2026, 11, 16, 12, 0, tzinfo=UTC),
            interaction_count=4,
        )
    )

    second = FanRelationStore(path)
    profile = second.get("u9")
    assert profile is not None
    assert profile.nickname == "阿岚"
    assert profile.interests == ["露营"]
    assert profile.interaction_count == 4
    assert profile.last_interaction == datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


def test_public_replay_redacts_secrets_and_has_stable_hash() -> None:
    events = [
        {
            "seq": 1,
            "kind": "tool",
            "ts": "2026-11-16T00:00:00Z",
            "payload": {"token": "secret", "phone": "13800138000", "text": "hello@example.com"},
        }
    ]
    bundle = compile_public_replay_bundle(
        "thread-1", events, generated_at=datetime(2026, 11, 16, tzinfo=UTC)
    )
    assert bundle["frames"][0]["payload"]["token"] == "[redacted]"
    assert bundle["frames"][0]["payload"]["phone"] == "[phone]"
    assert bundle["frames"][0]["payload"]["text"] == "[email]"
    assert len(bundle["bundle_hash"]) == 16


def test_audit_note_distribution_flags_low_exposure_breakout() -> None:
    now = datetime(2026, 11, 16, tzinfo=UTC)
    rows = [
        {
            "note_id": f"normal-{index}",
            "views": 1000,
            "likes": 10,
            "collects": 5,
            "comments": 1,
            "published_at": "2026-11-14T00:00:00+00:00",
        }
        for index in range(10)
    ]
    rows.append(
        {
            "note_id": "breakout",
            "views": 100,
            "likes": 20,
            "collects": 10,
            "comments": 5,
            "published_at": "2026-11-14T00:00:00+00:00",
        }
    )
    report = audit_note_distribution(rows, followers=800, now=now)
    breakout = next(item for item in report["exposure"] if item["note_id"] == "breakout")
    assert breakout["suspected_throttle"] is True
    assert report["breakouts"][0]["note_id"] == "breakout"
    assert report["followers"] == 800


def test_audit_note_distribution_empty_is_stable() -> None:
    report = audit_note_distribution([], followers=0)
    assert report["note_count"] == 0
    assert report["exposure"] == []
    assert report["breakouts"] == []
