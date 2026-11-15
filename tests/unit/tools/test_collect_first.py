"""Collect-First / Hawkes forecast tests (OranSim-style deterministic core)."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from backend.tools.analysis.collect_first import (
    HawkesParams,
    PostFeatures,
    diffusion_curve,
    fit_calibration,
    fit_hawkes,
    forecast_payload,
    paired_feature_substitution,
    predict_engagement,
    rank_candidates,
    response_mass,
    text_signature,
)


def _features(**overrides: object) -> PostFeatures:
    payload: dict[str, object] = {
        "title": "新手化妆步骤清单",
        "body": "第一步先保湿，第二步上底妆。保姆级教程，收藏起来慢慢看。",
        "tags": ("化妆", "新手教程", "干货"),
        "media_type": "image",
        "follower_count": 1200,
        "age_days": 1.0,
        "posted_hour": 20,
    }
    payload.update(overrides)
    return PostFeatures(**payload)  # type: ignore[arg-type]


def test_text_signature_is_64d_and_normalised() -> None:
    signature = text_signature("小红书笔记内容")
    assert len(signature) == 64
    assert math.isclose(sum(value * value for value in signature), 1.0, rel_tol=1e-6)
    assert signature != text_signature("完全不同的内容")


def test_predict_engagement_returns_four_heads() -> None:
    forecast = predict_engagement(_features())
    assert forecast.read > 0
    assert forecast.like >= 0
    assert forecast.collect >= 0
    assert forecast.comment >= 0
    assert set(forecast.log_scores) == {"read", "like", "collect", "comment"}
    assert len(forecast.representation) == 64


def test_utility_rich_copy_wins_on_collect() -> None:
    rich = predict_engagement(_features())
    bland = predict_engagement(_features(title="今天", body="就这样吧", tags=(), follower_count=0))
    assert rich.collect > bland.collect
    assert response_mass(rich) > response_mass(bland)


def test_rank_candidates_collect_first() -> None:
    ranked = rank_candidates(
        [
            {"id": "bland", "title": "今天", "body": "随便写", "tags": ()},
            {
                "id": "rich",
                "title": "保姆级教程",
                "body": "步骤清单 收藏 干货 推荐",
                "tags": ("教程",),
            },
        ]
    )
    assert [item["variant"] for item in ranked][0] == "rich"
    assert [item["rank"] for item in ranked] == [1, 2]


def test_fit_hawkes_and_diffusion_curve() -> None:
    start = datetime(2026, 11, 1, tzinfo=UTC)
    snapshots = [
        {
            "fetched_at": (start + timedelta(days=index)).isoformat(),
            "views": 100 * index + index * index * 10,
            "likes": 5 * index,
            "collects": 2 * index,
            "comments": index,
        }
        for index in range(1, 11)
    ]
    params = fit_hawkes(snapshots)
    assert isinstance(params, HawkesParams)
    assert params.mu >= 0
    assert params.beta > 0
    assert params.horizon_days == 14
    curve = diffusion_curve(params)
    assert len(curve) == 14
    assert all(row["daily_events"] >= 0 for row in curve)
    assert curve[-1]["cumulative"] >= curve[0]["cumulative"]


def test_paired_feature_substitution_is_deterministic() -> None:
    base = _features()
    variants = [
        {"variant": "title-a", "title": "通勤妆 5 分钟"},
        {"variant": "title-b", "title": "新手化妆总翻车？"},
    ]
    first = paired_feature_substitution(base, variants, seed=7)
    second = paired_feature_substitution(base, variants, seed=7)
    assert [item.variant for item in first] == [item.variant for item in second]
    assert [round(item.delta_collect, 6) for item in first] == [
        round(item.delta_collect, 6) for item in second
    ]
    assert [item.rank for item in first] == [1, 2]


def _calibration_records(count: int = 12) -> list[dict[str, object]]:
    """Build outcomes whose true log score is exactly ``2 * prior + 1``."""
    records: list[dict[str, object]] = []
    for index in range(count):
        title = f"历史笔记 {index}：露营装备清单"
        prior = predict_engagement(PostFeatures(title=title))
        records.append(
            {
                "title": title,
                "views": math.expm1(2 * prior.log_scores["read"] + 1),
                "likes": math.expm1(2 * prior.log_scores["like"] + 1),
                "collects": math.expm1(2 * prior.log_scores["collect"] + 1),
                "comments": math.expm1(2 * prior.log_scores["comment"] + 1),
            }
        )
    return records


def test_fit_calibration_recovers_account_scale() -> None:
    calibration = fit_calibration(_calibration_records())
    assert calibration is not None
    assert calibration.sample_size == 12
    assert set(calibration.heads) == {"read", "like", "collect", "comment"}
    for head in calibration.heads.values():
        assert math.isclose(head.slope, 2.0, abs_tol=0.01)
        assert math.isclose(head.intercept, 1.0, abs_tol=0.01)
        assert head.r2_log > 0.99

    title = "历史笔记 0：露营装备清单"
    prior = predict_engagement(PostFeatures(title=title))
    calibrated = predict_engagement(PostFeatures(title=title), calibration=calibration)
    assert math.isclose(
        calibrated.log_scores["collect"],
        2 * prior.log_scores["collect"] + 1,
        abs_tol=0.01,
    )


def test_fit_calibration_needs_enough_history() -> None:
    assert fit_calibration(_calibration_records(6)) is None


def test_calibration_fits_only_heads_with_counters() -> None:
    records = [{"title": f"只有阅读 {index}", "views": 100 + index * 10} for index in range(10)]
    calibration = fit_calibration(records)
    assert calibration is not None
    assert set(calibration.heads) == {"read"}
    assert calibration.apply({"read": 1.0, "like": 2.0})["like"] == 2.0


def test_forecast_payload_reports_calibration() -> None:
    calibration = fit_calibration(_calibration_records())
    payload = forecast_payload(_features(), calibration=calibration)
    assert payload["calibration"]["sample_size"] == 12
    assert "collect" in payload["calibration"]["heads"]
