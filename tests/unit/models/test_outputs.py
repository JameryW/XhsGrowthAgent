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
    AnalyticsOutput,
    BloggerScoutOutput,
    BriefAnalysisOutput,
    BriefClarificationOutput,
    ContentAnalysisOutput,
    ContentPlanOutput,
    ContentVersionsOutput,
    CopyContentOutput,
    EvaluationPanelOutput,
    HotTopicItemOutput,
    ShootingPlanOutput,
    StyleVariantsOutput,
    SuggestionItemOutput,
    TrendScoutOutput,
    ViralPostsOutput,
    VisualPlanOutput,
    normalize_analytics,
    normalize_blogger_candidates,
    normalize_brief_analysis,
    normalize_brief_clarification,
    normalize_content_plan,
    normalize_content_versions,
    normalize_copy_content,
    normalize_evaluation_panel,
    normalize_optimization_analysis,
    normalize_shooting_plan,
    normalize_style_variants,
    normalize_trend_data,
    normalize_viral_posts,
    normalize_visual_plan,
)
from backend.state.substates import (
    AnalyticsSnapshot,
    BloggerProfile,
    BriefContent,
    ContentVersion,
    CopyContent,
    DimensionScore,
    EvaluationResult,
    GapItem,
    OptimizationAnalysis,
    ShootingPlan,
    SuggestionItem,
    TrendData,
    ViralPost,
    VisualPlan,
)


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


# ── 商单 brief 解析（analyst / content_analyzer / viral_matcher 同批，P1d-S2b） ──


class TestBriefAnalysisOutput:
    """Two facts about a brief are not the model's to state: *what the client
    sent* (``raw_text``) and *how it arrived* (``source_type``). Letting a model
    declare a fact it does not hold is letting it lie about one."""

    def test_the_model_cannot_declare_where_the_text_came_from(self):
        declared = set(BriefAnalysisOutput.model_fields)
        assert "raw_text" not in declared
        assert "source_type" not in declared

    def test_every_key_matches_the_state_contract_shape(self):
        assert set(normalize_brief_analysis(BriefAnalysisOutput())) == set(
            BriefContent.__annotations__
        ) - {"raw_text", "source_type"}

    def test_a_missing_confidence_is_the_callers_old_default(self):
        """0.5 was what the caller substituted for a field the model omitted."""
        assert BriefAnalysisOutput().confidence == 0.5

    def test_an_unreadable_confidence_is_the_least_confident_answer(self):
        """``"高"`` is a judgment the model expressed and we cannot read. Treating
        it as "no opinion" (0.5) would leave a vague brief below the clarification
        threshold by accident; 0.0 sends it to the user, the only safe error."""
        assert BriefAnalysisOutput.model_validate({"confidence": "高"}).confidence == 0.0

    def test_a_confidence_written_as_a_percentage_is_not_rescaled(self):
        assert BriefAnalysisOutput.model_validate({"confidence": "80%"}).confidence == 80.0

    def test_a_single_string_is_one_selling_point_not_its_characters(self):
        output = BriefAnalysisOutput.model_validate({"selling_points": "静音、便携"})
        assert normalize_brief_analysis(output)["selling_points"] == ["静音、便携"]

    def test_blank_entries_are_dropped_from_every_text_list(self):
        output = BriefAnalysisOutput.model_validate(
            {"selling_points": ["静音", "  ", ""], "notes": ["  ", "都拍 live 图"]}
        )
        normalised = normalize_brief_analysis(output)
        assert normalised["selling_points"] == ["静音"]
        assert normalised["notes"] == ["都拍 live 图"]

    def test_client_hashtags_keep_the_brands_own_spelling(self):
        """必带/选带话题是品牌方原文，"带不带 #"是品牌的写法而不是模型的口误。

        Compare ``normalize_content_plan``'s ``hashtags``: those are labels the
        model invented for us, so the ``#`` is a format we asked for. Same edit,
        opposite verdicts — the judge is who wrote the text.
        """
        output = BriefAnalysisOutput.model_validate({"required_hashtags": ["几素", "#夏日出行"]})
        assert normalize_brief_analysis(output)["required_hashtags"] == ["几素", "#夏日出行"]


class TestBriefClarificationOutput:
    def test_a_bare_array_is_the_question_list(self):
        """The pre-migration call site read both spellings
        (``parsed if isinstance(parsed, list) else parsed.get("questions", [])``)
        and ``_parse_json_response`` really returns a list for ``[{…}]`` — so a
        chain that refused lists would turn "accepted" into a hard failure."""
        output = BriefClarificationOutput.model_validate(
            [{"field": "target_audience", "question": "受众是谁？"}]
        )
        assert [question.field for question in output.questions] == ["target_audience"]

    def test_the_envelope_spelling_is_no_worse(self):
        output = BriefClarificationOutput.model_validate(
            {"questions": [{"field": "x", "question": "?"}]}
        )
        assert len(output.questions) == 1

    def test_a_key_the_model_invented_still_reaches_the_ui(self):
        """``BriefClarification.questions`` is ``list[dict[str, Any]]`` — no shape
        on purpose, because the questions go straight to the user. Dropping an
        unmodelled key on a shapeless contract is the one way this migration
        could quietly send fewer fields to the front end, so this model is the
        file's single ``extra="allow"``.
        """
        output = BriefClarificationOutput.model_validate(
            [{"field": "x", "question": "?", "hint": "选一个"}]
        )
        assert normalize_brief_clarification(output)[0]["hint"] == "选一个"

    def test_the_questions_normalise_to_plain_dicts_for_the_ui(self):
        output = BriefClarificationOutput.model_validate([{"field": "x", "question": "?"}])
        question = normalize_brief_clarification(output)[0]
        assert isinstance(question, dict)
        assert question["options"] == []
        assert question["inferred_value"] is None

    def test_options_written_as_one_string_are_not_split_into_characters(self):
        output = BriefClarificationOutput.model_validate(
            [{"field": "x", "question": "?", "options": "A、B"}]
        )
        assert normalize_brief_clarification(output)[0]["options"] == ["A、B"]

    def test_an_empty_envelope_asks_nothing_rather_than_failing(self):
        """A user is allowed to skip clarification, so "no questions" is a legal
        answer and not a failed node."""
        assert normalize_brief_clarification(BriefClarificationOutput()) == []


class TestAnalyticsOutput:
    def test_it_covers_the_contract_and_adds_the_three_prompt_only_keys(self):
        """The 5 counters are not in the prompt: the model copies them back out of
        the "帖子数据" block it was handed. Declaring them turns "may or may not
        exist" into a field with a default — and ``_extract_post_data`` reads
        every one of them into the report.

        The other three (表现最好的类型/时段/标签) are in the prompt but in no
        contract, and they still land in state. The gap has to be exactly those,
        or a field went missing on the way.
        """
        assert set(normalize_analytics(AnalyticsOutput())) == (
            set(AnalyticsSnapshot.__annotations__) - {"post_id", "timestamp"}
        ) | {"best_performing_type", "best_performing_time", "top_hashtags"}

    def test_the_model_cannot_declare_the_post_it_is_describing(self):
        declared = set(AnalyticsOutput.model_fields)
        assert "post_id" not in declared
        assert "timestamp" not in declared

    def test_a_missing_counter_is_a_zero_rather_than_a_missing_key(self):
        normalised = normalize_analytics(AnalyticsOutput())
        assert normalised["views"] == 0
        assert normalised["shares"] == 0

    def test_counts_written_in_units_are_read_as_numbers(self):
        output = AnalyticsOutput.model_validate({"views": "1.2万", "likes": "3k", "shares": "5万"})
        normalised = normalize_analytics(output)
        assert normalised["views"] == 12000
        assert normalised["likes"] == 3000
        assert normalised["shares"] == 50000

    def test_rates_written_with_a_percent_sign_are_not_rescaled(self):
        """Neither direction is guessable here — whether a rate is 0-1 or 0-100
        is a fact about the prompt, not about the string."""
        output = AnalyticsOutput.model_validate({"engagement_rate": "5%", "reach_rate": 0.05})
        normalised = normalize_analytics(output)
        assert normalised["engagement_rate"] == 5.0
        assert normalised["reach_rate"] == 0.05

    def test_a_single_string_of_insights_is_not_split_into_characters(self):
        output = AnalyticsOutput.model_validate({"insights": "互动率偏低"})
        assert normalize_analytics(output)["insights"] == ["互动率偏低"]

    def test_blank_insights_are_dropped_before_they_reach_memory(self):
        """``analyst.execute`` writes every insight to the memory store; a blank
        one is a stored record that says nothing."""
        output = AnalyticsOutput.model_validate({"insights": ["  ", "互动率偏低", ""]})
        assert normalize_analytics(output)["insights"] == ["互动率偏低"]


class TestContentAnalysisOutput:
    def test_the_envelope_is_kept_because_the_prompt_produces_it(self):
        """Rewriting the prompt to "answer with the inner object" would change the
        system prompt's bytes, which this package does not do."""
        output = ContentAnalysisOutput.model_validate(
            {"optimization_analysis": {"gaps": [{"dimension": "标题", "severity": "high"}]}}
        )
        assert output.optimization_analysis.gaps[0].dimension == "标题"

    def test_the_three_keys_are_present_even_when_everything_is_empty(self):
        """The old call site hand-wrote an identical empty structure when the key
        was missing, so "what an empty analysis looks like" had two sources."""
        assert set(normalize_optimization_analysis(ContentAnalysisOutput())) == set(
            OptimizationAnalysis.__annotations__
        )

    def test_the_items_match_their_state_contract_shapes(self):
        output = ContentAnalysisOutput.model_validate(
            {
                "optimization_analysis": {
                    "gaps": [{"dimension": "标题", "description": "太笼统", "severity": "high"}],
                    "suggestions": [{"dimension": "标题", "action": "加数字"}],
                    "viral_patterns": ["前 3 行给结论"],
                }
            }
        )
        normalised = normalize_optimization_analysis(output)
        assert set(normalised["gaps"][0]) == set(GapItem.__annotations__)
        assert set(normalised["suggestions"][0]) == set(SuggestionItem.__annotations__)

    def test_priority_defaults_to_the_number_the_consumer_already_used(self):
        """``version_generator`` reads ``s.get('priority', 3)`` in two places and
        the prompt's example says ``"priority": 1``. A field with a reader gets
        the reader's own fallback, not a new one invented here."""
        assert SuggestionItemOutput.model_validate({"dimension": "标题"}).priority == 3

    def test_priority_written_as_text_is_read_as_a_number(self):
        assert SuggestionItemOutput.model_validate({"priority": "2"}).priority == 2

    def test_a_suggestion_key_no_consumer_reads_is_dropped(self):
        """``SuggestionItem`` is a shapeless-less TypedDict: only declared keys go
        into state. Contrast ``ClarificationQuestionOutput``'s ``extra="allow"``
        — the judge is whether the contract has a shape."""
        output = ContentAnalysisOutput.model_validate(
            {"optimization_analysis": {"suggestions": [{"dimension": "x", "why": "...", "v": 3}]}}
        )
        assert "why" not in normalize_optimization_analysis(output)["suggestions"][0]


class TestViralPostsOutput:
    def test_a_bare_array_is_the_post_list(self):
        output = ViralPostsOutput.model_validate([{"note_id": "a"}, {"note_id": "b"}])
        assert [post["note_id"] for post in normalize_viral_posts(output)] == ["a", "b"]

    def test_the_envelope_spelling_also_works(self):
        output = ViralPostsOutput.model_validate({"viral_posts": [{"note_id": "a"}]})
        assert len(normalize_viral_posts(output)) == 1

    def test_the_search_keywords_the_prompt_also_produces_are_dropped(self):
        """Not modelled, and not a loss: the old call site took
        ``result.get("viral_posts", [])`` and nothing else."""
        output = ViralPostsOutput.model_validate(
            {"viral_posts": [], "search_keywords_used": ["美食"]}
        )
        assert normalize_viral_posts(output) == []

    def test_a_non_mapping_palette_does_not_take_the_batch_down(self):
        """``color_palette`` is one decorative line rendered into the *next*
        prompt, and the entry carrying it is a reference note we need. Trading a
        whole batch of notes for one colour card is a bad trade."""
        output = ViralPostsOutput.model_validate(
            {"viral_posts": [{"title": "a", "color_palette": "暖色"}, {"title": "b"}]}
        )
        posts = normalize_viral_posts(output)
        assert [post["title"] for post in posts] == ["a", "b"]
        assert posts[0]["color_palette"] == {}

    def test_counts_written_in_units_are_read_as_numbers(self):
        output = ViralPostsOutput.model_validate([{"likes": "1.5万", "collects": "2千"}])
        post = normalize_viral_posts(output)[0]
        assert post["likes"] == 15000
        assert post["collects"] == 2000

    def test_a_single_hashtag_string_is_not_split_into_characters(self):
        output = ViralPostsOutput.model_validate([{"hashtags": "#美食"}])
        assert normalize_viral_posts(output)[0]["hashtags"] == ["#美食"]

    def test_every_key_matches_the_state_contract_shape(self):
        output = ViralPostsOutput.model_validate([{"note_id": "a"}])
        assert set(normalize_viral_posts(output)[0]) == set(ViralPost.__annotations__)


class TestEvaluationPanelOutput:
    """The judge panel's answer — the *input* to the evaluator's rebuild.

    Unlike every other model in this module, what leaves here is not state. It is
    the raw payload ``EvaluatorAgent._build_evaluation_result`` reads off, and
    that builder owns the recomputation of ``overall_score``/``decision`` from
    fixed rules (RQGM's verifiable metric + judge signal). So these tests are
    about the half a model may state, and about the two fields it may *not*.
    """

    def test_the_verdict_fields_are_not_modelled(self):
        """``overall_score``/``decision`` are recomputed, never taken from the
        panel. The prompt's example asks a model to write them anyway;
        ``extra="ignore"`` is what makes that harmless instead of authoritative."""
        panel = EvaluationPanelOutput.model_validate(
            {"overall_score": 99, "decision": "approved", "summary": "ok"}
        )
        assert set(panel.model_dump()) == {
            "dimensions",
            "revision_hints",
            "summary",
            "bias_warning",
        }

    def test_a_payload_with_no_panel_at_all_is_still_a_legal_dict(self):
        """The reachable shape of "the model answered prose".

        ``_parse_json_response`` does not fail on prose — it wraps it as
        ``{"raw_content": …}`` — and for a model whose every field has a default
        that is a perfectly valid dict. Shape checking can refuse nothing here,
        which is exactly why the evaluator carries a semantic check that reads an
        empty ``dimensions`` as a non-answer rather than as thin coverage.
        """
        panel = EvaluationPanelOutput.model_validate({"raw_content": "模型这次只说了段话"})
        assert panel.dimensions == []
        assert normalize_evaluation_panel(panel)["dimensions"] == []

    def test_a_partial_panel_keeps_what_it_has(self):
        """Not an error, and deliberately not treated as one: the builder has an
        explicit answer for missing dimensions (unavailable, never a neutral 70)."""
        panel = EvaluationPanelOutput.model_validate(
            {"dimensions": [{"dimension": "copywriting", "score": 80}]}
        )
        assert len(panel.dimensions) == 1
        assert normalize_evaluation_panel(panel)["dimensions"][0]["score"] == 80.0

    def test_an_unreadable_score_reads_as_absent_not_as_a_broken_payload(self):
        """The pre-migration reader was ``_to_float(score, nan)``, which made the
        dimension unavailable. Failing the whole payload instead would spend a
        retry on a mistake whose correct disposition already exists."""
        panel = EvaluationPanelOutput.model_validate(
            {"dimensions": [{"dimension": "x", "score": "abc"}]}
        )
        assert panel.dimensions[0].score is None

    def test_a_score_written_as_digits_is_read(self):
        panel = EvaluationPanelOutput.model_validate(
            {"dimensions": [{"dimension": "x", "score": "85"}]}
        )
        assert panel.dimensions[0].score == 85.0

    def test_a_bare_issue_string_is_not_split_into_characters(self):
        """``list(raw.get("issues") or [])`` turned ``"一条问题"`` into four
        one-character issues. Same family as the ``hashtags``/``viral_patterns``
        shape fixes: a string is one item, never an iterable of letters."""
        panel = EvaluationPanelOutput.model_validate(
            {"dimensions": [{"dimension": "x", "issues": "一条问题"}]}
        )
        assert panel.dimensions[0].issues == ["一条问题"]

    def test_a_bare_hint_string_is_not_split_into_characters(self):
        panel = EvaluationPanelOutput.model_validate({"revision_hints": "提示一"})
        assert normalize_evaluation_panel(panel)["revision_hints"] == ["提示一"]

    def test_null_reads_as_said_nothing_not_as_the_word_none(self):
        """``str(raw.get("summary"))`` on an explicit ``null`` produced the literal
        text ``None`` — four characters a human then reads as the summary."""
        panel = EvaluationPanelOutput.model_validate(
            {"summary": None, "dimensions": [{"dimension": "x", "rationale": None}]}
        )
        assert panel.summary == ""
        assert panel.dimensions[0].rationale == ""

    def test_blank_hints_are_dropped_and_kept_hints_are_text(self):
        panel = EvaluationPanelOutput.model_validate({"revision_hints": ["a", "", "  ", "b"]})
        assert normalize_evaluation_panel(panel)["revision_hints"] == ["a", "b"]

    def test_the_three_state_flag_survives_normalisation(self):
        """``available`` is internal — the prompt's example never mentions it — and
        the pre-migration reader was ``bool(raw.get(key, True))``: absent took the
        default, an explicit ``null`` fell to ``False``.

        The distinction is kept rather than flattened here because the flattening
        already has an owner: ``_build_evaluation_result`` ends with ``bool(...)``
        on this value.
        """
        missing = normalize_evaluation_panel(
            EvaluationPanelOutput.model_validate({"dimensions": [{"dimension": "x"}]})
        )
        explicit_null = normalize_evaluation_panel(
            EvaluationPanelOutput.model_validate(
                {"dimensions": [{"dimension": "x", "available": None}]}
            )
        )
        assert missing["dimensions"][0]["available"] is True
        assert explicit_null["dimensions"][0]["available"] is None

    def test_a_boolean_written_as_a_string_is_read_as_a_boolean(self):
        """``bool("false")`` is ``True``: a dimension the model explicitly marked
        unusable was scored anyway. Reading it as ``False`` is the fix, not a
        regression — the score is dropped instead of trusted."""
        panel = EvaluationPanelOutput.model_validate(
            {"dimensions": [{"dimension": "x", "score": 80, "available": "false"}]}
        )
        assert panel.dimensions[0].available is False

    def test_an_unreadable_flag_reads_as_not_stated(self):
        """Refusing the payload would let one odd adjective cost the whole panel."""
        panel = EvaluationPanelOutput.model_validate(
            {"dimensions": [{"dimension": "x", "is_blocking": "也许"}]}
        )
        assert panel.dimensions[0].is_blocking is None

    def test_the_dimension_keys_cover_the_state_contract(self):
        """Pinned against ``substates.DimensionScore``, not against this model's
        own fields — comparing a model to itself is true by construction.

        Containment rather than equality, and the difference is the point:
        ``available`` is carried because the *builder* reads it, and it is absent
        from the state contract because the builder consumes it rather than
        storing it.
        """
        panel = EvaluationPanelOutput.model_validate(
            {"dimensions": [{"dimension": "x", "score": 80}]}
        )
        item = normalize_evaluation_panel(panel)["dimensions"][0]
        assert set(DimensionScore.__annotations__) <= set(item)
        assert set(item) - set(DimensionScore.__annotations__) == {"available"}

    def test_the_envelope_keys_are_a_subset_of_the_state_contract(self):
        panel = EvaluationPanelOutput.model_validate({"summary": "ok"})
        normalized = normalize_evaluation_panel(panel)
        assert set(normalized) <= set(EvaluationResult.__annotations__)


class TestCopyContentOutput:
    """``copywriter`` 的正文产物 —— 键集与 ``substates.CopyContent`` 逐一对齐。"""

    def test_the_keys_are_the_state_contract(self):
        """Equality, and against the state contract rather than this model's own
        fields: comparing a model to itself is true by construction."""
        payload = normalize_copy_content(CopyContentOutput.model_validate({}))
        assert set(payload) == set(CopyContent.__annotations__)

    def test_prose_is_a_legal_payload_which_is_why_the_agent_has_a_validator(self):
        """The reachable shape of "the model answered prose": ``{"raw_content": …}``
        validates against an all-defaults model, so the schema refuses nothing.
        Shape checking cannot tell "answered, with nothing" from "answered
        nothing at all" — that is the semantic validator's job."""
        copy = CopyContentOutput.model_validate({"raw_content": "模型这次只说了段话"})
        assert copy.selected_title == ""
        assert copy.body_text == ""
        assert copy.title_candidates == []

    def test_the_sibling_prompts_field_names_are_read(self):
        """``title``/``body`` are what the variant prompt in the same module asks
        for, and the model crosses the two prompts over often enough that
        ``_apply_de_ai_taste`` grew a manual ``.get("selected_title") or
        .get("title")`` fallback. A retry spent on a field the model *did*
        answer would buy nothing, so the tolerance is stated once, here."""
        copy = CopyContentOutput.model_validate({"title": "标题A", "body": "正文A"})
        assert normalize_copy_content(copy)["selected_title"] == "标题A"
        assert normalize_copy_content(copy)["body_text"] == "正文A"

    def test_the_canonical_name_wins_when_both_are_written(self):
        copy = CopyContentOutput.model_validate({"selected_title": "正名", "title": "别名"})
        assert copy.selected_title == "正名"

    def test_hashtags_keep_the_hash_characters_the_model_wrote(self):
        """``_normalize_hashtags`` forces exactly one leading ``#``; that is the
        wrong tool here. The reader is ``publisher._as_str_list``, which passes
        tags through untouched — retagging them would change what a reader that
        never looks at the ``#`` now sees."""
        copy = CopyContentOutput.model_validate({"hashtags": ["#美食", "探店"]})
        assert normalize_copy_content(copy)["hashtags"] == ["#美食", "探店"]

    def test_a_bare_string_is_one_item_not_its_characters(self):
        copy = CopyContentOutput.model_validate({"title_candidates": "标题一、标题二"})
        assert normalize_copy_content(copy)["title_candidates"] == ["标题一、标题二"]

    def test_null_reads_as_said_nothing_not_as_the_word_none(self):
        copy = CopyContentOutput.model_validate({"cta": None, "tone": None})
        assert (copy.cta, copy.tone) == ("", "")


class TestVersionOutputs:
    """两个来源的 ``content_versions`` 元素。

    ``copywriter`` 的风格变体与 ``version_generator`` 的 A/B/C 版本写进**同一个**
    state 键，下游读者（``choice_gate``/``artifacts``/OMP/前端）不区分来源 ——
    这里钉的就是"字段集必须同构"这条不变量。
    """

    def test_both_sources_emit_the_same_keys_apart_from_the_discriminator(self):
        variant = normalize_style_variants(
            StyleVariantsOutput.model_validate({"variants": [{"style_name": "A"}]})
        )[0]
        version = normalize_content_versions(
            ContentVersionsOutput.model_validate({"versions": [{"version_type": "a"}]})
        )[0]
        assert set(variant) - {"style_name"} == set(version) - {"version_type"}

    def test_a_missing_version_id_is_minted_here(self):
        """Both pre-migration call sites minted ``uuid4()[:8]`` *after* parsing and
        before returning, so the id belongs to what leaves — one owner."""
        variant = normalize_style_variants(StyleVariantsOutput.model_validate({"variants": [{}]}))[
            0
        ]
        assert len(variant["version_id"]) == 8

    def test_a_written_version_id_is_kept(self):
        variant = normalize_style_variants(
            StyleVariantsOutput.model_validate({"variants": [{"version_id": "style_a"}]})
        )[0]
        assert variant["version_id"] == "style_a"

    def test_the_contract_only_keys_leave_only_when_the_model_wrote_them(self):
        """Absent / empty / set are three different things to downstream.

        ``image_prompts``/``changes_summary``/``predicted_score`` are members of
        ``substates.ContentVersion`` but appear in neither prompt, so a model
        normally omits them — and the omission is *read*: ``omp_bridge`` does
        ``v.get("changes_summary", "draft")`` and ``artifacts`` does
        ``version.get("predicted_score", 0.0)``. Emitting a default for an
        unwritten key would delete the placeholder every existing version falls
        back to, turning "said nothing" into "said it is empty".
        """
        silent = normalize_content_versions(
            ContentVersionsOutput.model_validate({"versions": [{"title": "t"}]})
        )[0]
        assert "changes_summary" not in silent
        assert "predicted_score" not in silent
        assert "image_prompts" not in silent

        explicit = normalize_content_versions(
            ContentVersionsOutput.model_validate(
                {
                    "versions": [
                        {
                            "title": "t",
                            "changes_summary": "",
                            "predicted_score": 0,
                            "image_prompts": [],
                        }
                    ]
                }
            )
        )[0]
        assert explicit["changes_summary"] == ""
        assert explicit["predicted_score"] == 0.0
        assert explicit["image_prompts"] == []

    def test_the_prompt_keys_always_leave(self):
        version = normalize_content_versions(
            ContentVersionsOutput.model_validate({"versions": [{}]})
        )[0]
        assert {"version_id", "version_type", "title", "body", "hashtags", "tone"} <= set(version)

    def test_every_contract_key_with_a_reader_is_reachable(self):
        """``substates.ContentVersion`` and the two prompts disagree in **both**
        directions: the contract lists ``image_prompts``/``changes_summary``/
        ``predicted_score`` that no prompt asks for, while both prompts write
        ``version_type``/``tone``/``visual_style``/``color_palette`` the contract
        never declared. The drift predates this migration, whose payload
        reproduced it; reconciling it here would change what existing readers
        see.

        So the assertion is the reachability that matters — every contract key
        except the one the model has to volunteer is produced — rather than a
        containment that was never true.
        """
        version = normalize_content_versions(
            ContentVersionsOutput.model_validate(
                {"versions": [{"title": "t", "changes_summary": "c", "predicted_score": 1}]}
            )
        )[0]
        assert set(ContentVersion.__annotations__) - {"image_prompts"} <= set(version)
        assert {"version_type", "tone", "visual_style", "color_palette"} <= set(version)

    def test_a_bare_array_is_refused(self):
        """``ViralPostsOutput`` accepts one because both of *its* call sites did.
        These two read ``parsed.get("variants"/"versions")``, which crashes on a
        list — declaring ``accepts_bare_list`` would widen the contract under
        cover of a migration. A bare array instead takes the correction path,
        which beats the ``AttributeError`` it used to get."""
        with pytest.raises(ValidationError):
            StyleVariantsOutput.model_validate([{"style_name": "A"}])
        with pytest.raises(ValidationError):
            ContentVersionsOutput.model_validate([{"version_type": "a"}])

    def test_a_non_mapping_palette_becomes_empty_rather_than_failing_the_batch(self):
        variant = normalize_style_variants(
            StyleVariantsOutput.model_validate({"variants": [{"color_palette": "primary=#fff"}]})
        )[0]
        assert variant["color_palette"] == {}


class TestVisualPlanOutput:
    """``visual_designer`` 的视觉计划 —— 键集刻意与提示词一致。"""

    def test_the_keys_are_the_prompt_shape_not_a_superset(self):
        """``layout_style`` is read by ``evaluator``/``public_showcase``/``review``
        and has *never* been in this payload — the prompt writes
        ``layout_preference``. Emitting it here would change what a reader that
        was never fed the key now sees. ``style_id`` is absent for the opposite
        reason: the call site writes it back after ``deposit_style``."""
        payload = normalize_visual_plan(VisualPlanOutput.model_validate({}))
        assert set(payload) == {
            "cover_prompt",
            "image_count",
            "image_prompts",
            "visual_style",
            "layout_preference",
            "color_palette",
            "font_suggestion",
            "brand_elements",
        }

    def test_the_drift_between_the_prompt_and_the_state_contract_is_pinned(self):
        """``substates.VisualPlan`` declares ``layout_style``, which no prompt has
        ever written, and omits ``visual_style``/``layout_preference``, which the
        prompt does write. That drift predates this migration, which reproduces
        the prompt's shape; reconciling the two here would change what
        ``evaluator``/``public_showcase``/``review`` see, and a migration is not
        the place for it.

        Pinned as a two-way difference rather than containment, so either half
        of the drift going away turns this red instead of silently passing.
        """
        payload = normalize_visual_plan(VisualPlanOutput.model_validate({}))
        assert set(payload) - set(VisualPlan.__annotations__) == {
            "visual_style",
            "layout_preference",
        }
        assert set(VisualPlan.__annotations__) - set(payload) == {"layout_style", "image_paths"}

    def test_the_palette_is_a_list_not_the_mapping_viral_posts_carry(self):
        """Same word, different shape. ``StyleDNA.color_palette`` and
        ``publisher._as_str_list`` read a list; copying ``ViralPostOutput``'s
        mapping fallback (``{}``) over would drop that object into an
        ``f"{a}{b}"`` and render ``"{}{}"`` into the next prompt."""
        payload = normalize_visual_plan(
            VisualPlanOutput.model_validate({"color_palette": ["#fff", "#000"]})
        )
        assert payload["color_palette"] == ["#fff", "#000"]
        assert normalize_visual_plan(VisualPlanOutput.model_validate({"color_palette": "abc"}))[
            "color_palette"
        ] == ["abc"]

    def test_an_image_count_written_as_digits_is_read(self):
        assert VisualPlanOutput.model_validate({"image_count": 3}).image_count == 3
        assert VisualPlanOutput.model_validate({"image_count": "3"}).image_count == 3

    def test_prose_is_a_legal_payload_which_is_why_the_agent_has_a_validator(self):
        plan = VisualPlanOutput.model_validate({"raw_content": "只说了段话"})
        assert plan.cover_prompt == ""
        assert plan.image_prompts == []


class TestShootingPlanOutput:
    """``shooting_planner`` 的拍摄计划 —— 16 个键与 state 契约逐一对齐。"""

    def test_the_keys_are_the_state_contract(self):
        payload = normalize_shooting_plan(ShootingPlanOutput.model_validate({}))
        assert set(payload) == set(ShootingPlan.__annotations__)

    def test_prose_is_a_legal_payload_and_looks_like_the_early_return(self):
        """``shooting_planner`` returns ``{"shooting_plan": {}}`` when there is
        genuinely nothing to plan from, so an empty *answer* must not be allowed
        to look the same. That collision is what the agent's semantic validator
        exists to prevent — the schema cannot, because this payload validates."""
        plan = ShootingPlanOutput.model_validate({"raw_content": "只说了段话"})
        assert plan.body_copy == ""
        assert plan.title_candidates == []

    def test_a_non_mapping_outfits_becomes_empty(self):
        """A model that answers ``[{角色, 服装}]`` answered a different question.
        Guessing which field is the role would invent a costume for a person
        nobody named."""
        plan = ShootingPlanOutput.model_validate({"outfits": [{"role": "妈妈"}]})
        assert normalize_shooting_plan(plan)["outfits"] == {}

    def test_outfit_values_that_are_bare_strings_are_one_item_each(self):
        plan = ShootingPlanOutput.model_validate({"outfits": {"妈妈": "红裙子"}})
        assert normalize_shooting_plan(plan)["outfits"] == {"妈妈": ["红裙子"]}

    def test_a_bare_angle_sentence_becomes_one_angle(self):
        """The prompt asks for ``[{description: …}]``; one sentence is one angle,
        and ``_as_list`` is what keeps it whole instead of iterating letters.
        Letting Pydantic reject it would spend a retry on a field the model did
        answer."""
        plan = ShootingPlanOutput.model_validate({"shooting_angles": "低角度仰拍"})
        assert normalize_shooting_plan(plan)["shooting_angles"] == [
            {"description": "低角度仰拍", "reference_image": ""}
        ]

    def test_angles_that_are_mappings_keep_their_own_fields(self):
        plan = ShootingPlanOutput.model_validate(
            {"shooting_angles": [{"description": "俯拍", "reference_image": "a.png"}]}
        )
        assert normalize_shooting_plan(plan)["shooting_angles"] == [
            {"description": "俯拍", "reference_image": "a.png"}
        ]
