"""Tests for the LLM-facing output model and its normaliser (P1d).

The design claim under test: the model is allowed to be *loose* (a human would
read "明天下午三点" or "#美食" without blinking), and the strictness lives in
``normalize_*``, so what leaves these modules satisfies the state contract.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.models.outputs import ContentPlanOutput, normalize_content_plan


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
