"""Tests for the LLM-facing output model and its normaliser (P1d).

The design claim under test: the model is allowed to be *loose* (a human would
read "明天下午三点" or "#美食" without blinking), and the strictness lives in
``normalize_*``, so what leaves these modules satisfies the state contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from backend.models.outputs import (
    BloggerScoutOutput,
    ContentPlanOutput,
    HotTopicItemOutput,
    TrendScoutOutput,
    normalize_blogger_candidates,
    normalize_content_plan,
    normalize_trend_data,
)
from backend.state.substates import BloggerProfile, TrendData


class TestContentPlanOutput:
    def test_only_the_selected_topic_is_required(self):
        plan = ContentPlanOutput.model_validate({"selected_topic": "美食探店"})
        assert plan.selected_topic == "美食探店"
        assert plan.content_type == ""
        assert plan.key_points == []
        assert plan.hashtags == []
        assert plan.urgency == ""

    def test_a_payload_without_the_selected_topic_is_rejected(self):
        """The one field the node exists to produce, so the one worth a retry."""
        with pytest.raises(ValidationError):
            ContentPlanOutput.model_validate({"content_angle": "夜景"})

    def test_extra_keys_are_dropped_not_fatal(self):
        """A model that adds ``reasoning`` or echoes a prompt field has not
        made a mistake worth another request."""
        plan = ContentPlanOutput.model_validate(
            {"selected_topic": "美食探店", "reasoning": "因为热度高", "niche": "母婴"}
        )
        assert not hasattr(plan, "reasoning")
        assert set(plan.model_dump()) == set(ContentPlanOutput.model_fields)


class TestNormalizeContentPlan:
    def test_a_minimal_plan_gets_contract_shaped_defaults(self):
        plan = normalize_content_plan(ContentPlanOutput(selected_topic="美食探店"))
        assert plan["content_type"] == "note"
        assert plan["urgency"] == "medium"
        assert plan["hashtags"] == []
        assert plan["key_points"] == []

    def test_every_key_matches_the_state_contract_shape(self):
        plan = normalize_content_plan(ContentPlanOutput(selected_topic="x"))
        assert set(plan) == {
            "selected_topic",
            "content_angle",
            "content_type",
            "target_audience",
            "key_points",
            "suggested_timing",
            "hashtags",
            "urgency",
        }
        assert isinstance(plan["key_points"], list)
        assert isinstance(plan["hashtags"], list)
        assert isinstance(plan["suggested_timing"], str)

    @pytest.mark.parametrize(
        ("spoken", "expected"),
        [
            ("图文", "note"),
            ("图文笔记", "note"),
            ("图片", "note"),
            ("image", "note"),
            ("post", "note"),
            ("视频", "video"),
            ("short_video", "video"),
            ("reel", "video"),
            ("轮播图", "carousel"),
            ("多图", "carousel"),
            (" NOTE ", "note"),
        ],
    )
    def test_content_type_aliases_land_on_the_contract_value(self, spoken, expected):
        plan = normalize_content_plan(ContentPlanOutput(selected_topic="x", content_type=spoken))
        assert plan["content_type"] == expected

    def test_an_unknown_content_type_falls_back_conservatively(self):
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", content_type="vlog 混剪")
        )
        assert plan["content_type"] == "note"

    @pytest.mark.parametrize(
        ("spoken", "expected"),
        [
            ("紧急", "high"),
            ("urgent", "high"),
            ("热点", "trending"),
            ("hot", "trending"),
            ("热门", "trending"),
            ("中", "medium"),
            ("normal", "medium"),
            ("低", "low"),
            ("不急", "low"),
        ],
    )
    def test_urgency_aliases_land_on_the_contract_value(self, spoken, expected):
        plan = normalize_content_plan(ContentPlanOutput(selected_topic="x", urgency=spoken))
        assert plan["urgency"] == expected

    def test_an_unknown_urgency_falls_back_to_medium(self):
        plan = normalize_content_plan(ContentPlanOutput(selected_topic="x", urgency="有点急"))
        assert plan["urgency"] == "medium"

    def test_whitespace_is_stripped_from_the_text_fields(self):
        plan = normalize_content_plan(
            ContentPlanOutput(
                selected_topic="  美食探店  ",
                content_angle="\n夜景\n",
                target_audience=" 25-35 女性 ",
            )
        )
        assert plan["selected_topic"] == "美食探店"
        assert plan["content_angle"] == "夜景"
        assert plan["target_audience"] == "25-35 女性"

    def test_hashtags_get_exactly_one_leading_hash(self):
        plan = normalize_content_plan(
            ContentPlanOutput(
                selected_topic="x", hashtags=["美食", "#探店", "##夜宵", "  ", " 火锅 "]
            )
        )
        assert plan["hashtags"] == ["#美食", "#探店", "#夜宵", "#火锅"]

    def test_key_points_accept_strings_and_drop_blanks(self):
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", key_points=[" 要点一 ", "", "要点二"])
        )
        assert plan["key_points"] == ["要点一", "要点二"]

    def test_key_points_digest_a_nested_object(self):
        """A model that answers with ``[{"point": "…"}]`` stated a real point;
        dropping it would lose content over a shape disagreement."""
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", key_points=[{"point": " 先讲价格 "}, "直接讲"])
        )
        assert plan["key_points"] == ["先讲价格", "直接讲"]

    def test_key_points_stringify_scalars(self):
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", key_points=[3, "两段"])  # type: ignore[list-item]
        )
        assert plan["key_points"] == ["3", "两段"]

    def test_a_bare_string_is_one_key_point_not_its_characters(self):
        """The leniency that matters: a ``list[str]`` field would iterate the
        string and answer with a list of characters — a failure that looks like
        success and reaches state."""
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", key_points="要点一、要点二")  # type: ignore[arg-type]
        )
        assert plan["key_points"] == ["要点一、要点二"]

    def test_none_becomes_an_empty_list(self):
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", key_points=None, hashtags=None)  # type: ignore[arg-type]
        )
        assert plan["key_points"] == []
        assert plan["hashtags"] == []

    def test_a_bare_string_hashtag_is_not_split(self):
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", hashtags="#美食")  # type: ignore[arg-type]
        )
        assert plan["hashtags"] == ["#美食"]

    def test_key_points_stringify_non_string_hashtags(self):
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", hashtags=["美食", 2026])  # type: ignore[list-item]
        )
        assert plan["hashtags"] == ["#美食", "#2026"]

    def test_an_iso_timing_is_normalised(self):
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", suggested_timing="2026-09-16T19:00:00+08:00")
        )
        assert plan["suggested_timing"] == "2026-09-16T19:00:00+08:00"

    def test_a_datetime_instance_is_serialised(self):
        plan = normalize_content_plan(
            ContentPlanOutput(
                selected_topic="x",
                suggested_timing=datetime(2026, 9, 16, 19, 0),  # type: ignore[arg-type]
            )
        )
        assert plan["suggested_timing"] == "2026-09-16T19:00:00"

    def test_a_date_only_timing_becomes_midnight(self):
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", suggested_timing="2026-09-16")
        )
        assert plan["suggested_timing"] == "2026-09-16T00:00:00"

    def test_an_unparseable_timing_is_kept_verbatim(self):
        """Turning "本周五晚" into a wrong timestamp would be worse than
        keeping the model's own words — it stated a real intent."""
        plan = normalize_content_plan(
            ContentPlanOutput(selected_topic="x", suggested_timing=" 本周五晚 ")
        )
        assert plan["suggested_timing"] == "本周五晚"

    def test_an_empty_timing_stays_empty(self):
        plan = normalize_content_plan(ContentPlanOutput(selected_topic="x", suggested_timing="  "))
        assert plan["suggested_timing"] == ""


class TestHotTopicItemOutput:
    def test_a_named_topic_and_nothing_else_is_usable_information(self):
        item = HotTopicItemOutput.model_validate({"topic": "美食探店"})
        assert item.topic == "美食探店"
        assert item.heat_score == 0.0
        assert item.related_keywords == []

    def test_a_bare_string_becomes_a_named_topic(self):
        assert HotTopicItemOutput.model_validate("美食探店").topic == "美食探店"

    def test_a_dict_that_names_the_topic_differently_is_still_named(self):
        """Every reader of ``hot_topics`` already accepts a bare string or a
        dict with ``title``/``topic``; which word the model picked is its
        choice of vocabulary, not a different piece of data."""
        assert HotTopicItemOutput.model_validate({"title": "夏日穿搭"}).topic == "夏日穿搭"
        assert HotTopicItemOutput.model_validate({"keyword": "防晒"}).topic == "防晒"

    @pytest.mark.parametrize(
        ("written", "expected"),
        [("90%", 90.0), ("90", 90.0), (90, 90.0), ("1,234", 1234.0), ("很高", 0.0)],
    )
    def test_a_score_is_read_loosely_and_never_rescaled(self, written, expected):
        """The percent sign is dropped, not converted: whether a score is 0-1
        or 0-100 is a question this function cannot answer, and guessing would
        turn a readable number into a wrong one."""
        item = HotTopicItemOutput.model_validate({"topic": "x", "heat_score": written})
        assert item.heat_score == expected


class TestTrendScoutOutput:
    @pytest.mark.parametrize("alias", ["trending_topics", "topics"])
    def test_the_older_field_names_are_the_same_field(self, alias):
        output = TrendScoutOutput.model_validate({alias: [{"topic": "美食探店"}]})
        assert [item.topic for item in output.hot_topics] == ["美食探店"]

    def test_the_current_name_wins_when_both_are_present(self):
        output = TrendScoutOutput.model_validate(
            {"hot_topics": [{"topic": "新名字"}], "trending_topics": [{"topic": "旧名字"}]}
        )
        assert [item.topic for item in output.hot_topics] == ["新名字"]

    def test_a_nameless_entry_is_dropped_rather_than_failing_the_report(self):
        """One nameless entry and "the model gave no trends" are two different
        things; the first must not escalate into the second."""
        output = TrendScoutOutput.model_validate({"hot_topics": [{"heat_score": 70}, "咖啡"]})
        assert [item.topic for item in output.hot_topics] == ["咖啡"]

    def test_the_model_cannot_declare_its_own_data_source(self):
        """``data_source`` is a runtime fact (platform readable, or degraded).
        A model able to state it is a model able to claim real data it never
        saw — which is exactly how the fake ``data_source="real"`` happened."""
        output = TrendScoutOutput.model_validate({"data_source": "real"})
        assert not hasattr(output, "data_source")
        assert "data_source" not in normalize_trend_data(output)


class TestNormalizeTrendData:
    def test_an_empty_output_is_the_declared_empty_shape(self):
        """The degradation path builds its empty result from the model rather
        than from a hand-written parallel dict, so there is one source of truth
        for what "no trends" looks like."""
        empty = normalize_trend_data(TrendScoutOutput())
        assert empty["hot_topics"] == []
        assert empty["trending_keywords"] == []
        assert empty["competitor_posts"] == []
        assert empty["niche_opportunities"] == []

    def test_the_keys_are_exactly_the_ones_a_reader_reaches_for(self):
        assert set(normalize_trend_data(TrendScoutOutput())) == {
            "hot_topics",
            "trending_keywords",
            "trending_notes",
            "competitor_posts",
            "niche_opportunities",
            "market_saturation",
        }

    def test_the_known_gap_against_the_contract_is_still_exactly_two_keys(self):
        """Two of these are read without ``TrendData`` declaring them.

        ``trending_notes`` is read by ``blogger_scout._summarize_trend_data``
        and ``market_saturation`` is passed through to Ripple by
        ``content_strategist``. Both used to be populated only when the model
        happened to emit the key, which is a reader whose input is the model's
        mood. This test is here to make the gap *visible* — closing it means
        editing the state contract, not this module.
        """
        produced = set(normalize_trend_data(TrendScoutOutput()))
        declared = set(TrendData.__annotations__)
        assert produced - declared == {"trending_notes", "market_saturation"}
        assert declared - produced == {"timestamp"}

    def test_market_saturation_is_passed_through_untouched(self):
        """It goes to Ripple as-is; reshaping it here would be this module
        deciding what Ripple is allowed to see."""
        payload = {"level": "high", "notes": [1, 2]}
        output = TrendScoutOutput.model_validate({"market_saturation": payload})
        assert normalize_trend_data(output)["market_saturation"] == payload

    def test_trending_notes_survive_for_the_blogger_scout_reader(self):
        output = TrendScoutOutput.model_validate({"trending_notes": [{"title": "爆款笔记A"}]})
        assert normalize_trend_data(output)["trending_notes"] == [{"title": "爆款笔记A"}]


class TestBloggerScoutOutput:
    @pytest.mark.parametrize(
        ("written", "expected"),
        [("5万", 50000), ("1.2w", 12000), ("3k", 3000), ("2千", 2000), (7, 7), ("很多", 0)],
    )
    def test_counts_written_in_units_are_read_as_numbers(self, written, expected):
        """Chinese models answer follower counts in units far more often than
        in raw digits, and each unparsed suffix used to buy a whole retry."""
        output = BloggerScoutOutput.model_validate(
            {"candidates": [{"user_id": "1", "follower_count": written}]}
        )
        assert output.candidates[0].follower_count == expected

    def test_an_unreadable_count_becomes_zero_rather_than_a_retry(self):
        """These counts decorate a *generated* candidate: a zero is harmless
        where a failed batch is not."""
        output = BloggerScoutOutput.model_validate(
            {"candidates": [{"user_id": "1", "total_engagement": "很多"}]}
        )
        assert output.candidates[0].total_engagement == 0

    def test_no_candidates_is_an_empty_list_not_a_failure(self):
        assert BloggerScoutOutput.model_validate({}).candidates == []


class TestNormalizeBloggerCandidates:
    @staticmethod
    def _user_ids(*candidates: dict[str, Any]) -> list[str]:
        output = BloggerScoutOutput.model_validate({"candidates": list(candidates)})
        return [item["user_id"] for item in normalize_blogger_candidates(output, limit=5)]

    def test_a_missing_mock_prefix_is_added(self):
        assert self._user_ids({"user_id": "001"}) == ["mock_001"]

    def test_an_existing_prefix_is_not_doubled(self):
        assert self._user_ids({"user_id": "mock_001"}) == ["mock_001"]

    def test_an_absent_user_id_still_comes_back_marked(self):
        """The prefix is a contract, not decoration: these candidates are
        fabricated and must be recognisable as such at a glance."""
        assert self._user_ids({"nickname": "无名"}) == ["mock_unknown"]

    def test_the_limit_truncates(self):
        output = BloggerScoutOutput.model_validate(
            {"candidates": [{"user_id": str(index)} for index in range(10)]}
        )
        assert len(normalize_blogger_candidates(output, limit=3)) == 3

    def test_every_key_matches_the_state_contract_shape(self):
        output = BloggerScoutOutput.model_validate({"candidates": [{"user_id": "1"}]})
        assert set(normalize_blogger_candidates(output, limit=5)[0]) == set(
            BloggerProfile.__annotations__
        )
