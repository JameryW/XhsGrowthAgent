"""``services.geo_signals`` — the four signals behind GEO-CiteScore (ledger #37).

The properties pinned here are the ones the score's credibility rests on:

- the switch alone decides whether ``topic_scorer`` sees a ``geo`` block;
- ``intent_specificity`` orders a head term below a real long-tail query;
- supply density and evidence dispersion are measured from the same likes the
  caller already has, and are *zero* (not a midpoint) when there is nothing to
  measure;
- the same inputs produce the same report twice, because this number is quoted
  in prompts and re-read in review.
"""

from __future__ import annotations

import pytest

from backend.services.geo_signals import (
    GEO_SCORING_ENV,
    build_geo_report,
    evidence_dispersion,
    geo_scoring_enabled,
    intent_specificity,
    maybe_geo_report,
    search_demand,
    supply_density,
)


class TestSwitch:
    def test_off_by_default(self, monkeypatch) -> None:
        monkeypatch.delenv(GEO_SCORING_ENV, raising=False)
        assert geo_scoring_enabled() is False
        assert maybe_geo_report(topic="露营") is None

    @pytest.mark.parametrize("value", ["1", "true", "yes", "on", " TRUE "])
    def test_truthy_values_enable(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv(GEO_SCORING_ENV, value)
        assert geo_scoring_enabled() is True
        report = maybe_geo_report(topic="露营", likes=[120.0, 80.0])
        assert report is not None
        assert report["enabled"] is True

    @pytest.mark.parametrize("value", ["0", "false", "off", "", "no"])
    def test_other_values_keep_it_off(self, monkeypatch, value: str) -> None:
        monkeypatch.setenv(GEO_SCORING_ENV, value)
        assert geo_scoring_enabled() is False


class TestIntentSpecificity:
    def test_empty_is_zero(self) -> None:
        assert intent_specificity("") == 0.0
        assert intent_specificity("   ") == 0.0

    def test_head_term_scores_below_long_tail(self) -> None:
        head = intent_specificity("露营")
        middle = intent_specificity("川西自驾攻略")
        tail = intent_specificity("国庆川西7天租车多少钱含押金")
        assert head < middle < tail

    def test_digit_and_question_markers_both_contribute(self) -> None:
        without_digit = intent_specificity("川西自驾攻略对比")
        with_digit = intent_specificity("川西7天自驾攻略对比")
        assert with_digit > without_digit

    def test_capped_at_one(self) -> None:
        assert intent_specificity("国庆川西7天租车多少钱含押金对比避坑清单推荐流程注意") <= 1.0


class TestSupplyDensity:
    def test_empty_and_zero_likes_are_zero(self) -> None:
        assert supply_density([]) == 0.0
        assert supply_density([0.0, 0.0, 0.0]) == 0.0

    def test_no_dominant_note_means_no_strong_supply(self) -> None:
        # Nothing reaches the 1k virality bar → no incumbent to outrank.
        assert supply_density([120.0, 80.0]) == 0.0

    def test_detects_incumbent_notes(self) -> None:
        # median 95 → threshold 1000 (absolute bar wins); only 1000 qualifies → 1/4.
        assert supply_density([1000.0, 100.0, 90.0, 80.0]) == 0.25

    def test_uniform_strong_supply_is_fully_dense(self) -> None:
        # Every note is already viral: saturated, even though none is above median.
        assert supply_density([5000.0] * 50) == 1.0

    def test_ignores_unparseable_values(self) -> None:
        # Two garbage entries must not be coerced into zeros: the four real
        # values decide, so the density is 1/4 rather than 1/6.
        assert (
            supply_density([1000.0, 100.0, 100.0, 100.0, "not-a-number", None])  # type: ignore[list-item]
            == 0.25
        )


class TestEvidenceDispersion:
    def test_single_or_empty_sample_has_no_dispersion(self) -> None:
        assert evidence_dispersion([]) == 0.0
        assert evidence_dispersion([500.0]) == 0.0
        assert evidence_dispersion([0.0, 0.0]) == 0.0

    def test_one_authority_is_not_dispersed(self) -> None:
        # top3 == total → 0.0
        assert evidence_dispersion([1000.0, 20.0, 10.0]) == 0.0

    def test_fragmented_supply_is_dispersed(self) -> None:
        # 10 equal notes: top3/total = 0.3 → 0.7
        assert evidence_dispersion([100.0] * 10) == pytest.approx(0.7)


class TestSearchDemand:
    def test_posts_dominate_likes(self) -> None:
        demand = search_demand(post_count=50, average_likes=100.0)
        assert demand == pytest.approx(55.0)

    def test_keyword_likes_override_the_batch_average(self) -> None:
        default = search_demand(post_count=10, average_likes=100.0)
        boosted = search_demand(post_count=10, average_likes=100.0, keyword_likes=900.0)
        assert boosted > default

    def test_negative_and_invalid_inputs_do_not_go_negative(self) -> None:
        assert search_demand(post_count=-5, average_likes=-100.0) == 0.0
        assert search_demand(post_count=3, average_likes=float("nan")) == 3.0


class TestBuildReport:
    def test_ranks_the_specific_keyword_first(self) -> None:
        report = build_geo_report(
            topic="露营",
            keywords=["川西7天自驾攻略", "露营"],
            likes=[100.0] * 8,
        )

        assert report["best_keyword"] == "川西7天自驾攻略"
        assert report["candidates"][0]["keyword"] == "川西7天自驾攻略"
        assert report["best_score"] > 0.0

    def test_same_inputs_same_report(self) -> None:
        kwargs = {
            "topic": "露营",
            "keywords": ["川西7天自驾攻略", "露营装备清单"],
            "likes": [900.0, 400.0, 120.0, 80.0, 40.0],
            "keyword_likes": {"川西7天自驾攻略": 320.0},
        }
        assert build_geo_report(**kwargs) == build_geo_report(**kwargs)

    def test_dedupes_and_caps_candidates(self) -> None:
        report = build_geo_report(
            topic="露营",
            keywords=["露营", "川西7天自驾攻略", "露营装备清单", "国庆租车多少钱"],
            likes=[100.0, 200.0],
            limit=3,
        )

        keywords = [item["keyword"] for item in report["candidates"]]
        assert len(keywords) == 3
        assert len(set(keywords)) == 3
        assert "露营" in keywords

    def test_ranks_candidates_by_score_not_input_order(self) -> None:
        report = build_geo_report(
            topic="露营",
            keywords=["露营"],
            likes=[100.0],
        )

        # The head term is the only candidate here, so ranking cannot reorder it.
        assert [item["keyword"] for item in report["candidates"]] == ["露营"]

    def test_no_candidates_keeps_the_shape(self) -> None:
        report = build_geo_report(topic="", keywords=[])

        assert report["best_keyword"] == ""
        assert report["best_score"] == 0.0
        assert report["candidates"] == []
        assert "跳过" in report["recommendation"]

    def test_no_hits_reports_zero_supply_not_a_midpoint(self) -> None:
        report = build_geo_report(topic="露营", likes=[])

        assert report["signals"]["post_count"] == 0
        assert report["signals"]["supply_density"] == 0.0
        assert report["signals"]["evidence_dispersion"] == 0.0
        assert report["best_keyword"] == "露营"

    def test_saturated_supply_downgrades_the_recommendation(self) -> None:
        # 50 hits, every one already viral → density 1.0 → saturated.
        report = build_geo_report(topic="露营", keywords=["露营"], likes=[1000.0] * 50)

        assert report["signals"]["supply_density"] == 1.0
        assert "竞争饱和" in report["recommendation"]
        assert "碎片化" in report["recommendation"]

    def test_a_specific_long_tail_on_thin_supply_reads_as_a_blank(self) -> None:
        report = build_geo_report(
            topic="国庆川西7天租车多少钱含押金",
            likes=[100.0] * 8,
        )

        assert report["signals"]["supply_density"] == 0.0
        assert "空白明显" in report["recommendation"]

    def test_low_demand_is_named_instead_of_called_saturated(self) -> None:
        report = build_geo_report(topic="露营", likes=[0.0])

        assert report["signals"]["post_count"] == 1
        assert "需求过低" in report["recommendation"]
        assert "竞争饱和" not in report["recommendation"]

    def test_fragmented_supply_adds_the_structuring_hint(self) -> None:
        report = build_geo_report(topic="露营", likes=[100.0] * 10)

        assert report["signals"]["evidence_dispersion"] == pytest.approx(0.7)
        assert "碎片化" in report["recommendation"]

    def test_keyword_likes_are_per_keyword(self) -> None:
        report = build_geo_report(
            topic="露营",
            keywords=["露营装备清单"],
            likes=[100.0],
            keyword_likes={"露营装备清单": 5000.0},
        )

        by_keyword = {item["keyword"]: item for item in report["candidates"]}
        assert by_keyword["露营装备清单"]["search_demand"] > by_keyword["露营"]["search_demand"]
