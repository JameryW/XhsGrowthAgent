"""PLAD psychological-linguistic detector tests."""

from __future__ import annotations

from backend.tools.content.plad import (
    _FEATURE_COUNT,
    PladReport,
    inspect_text,
    plad_constraints,
)


def test_feature_count_is_31() -> None:
    report = inspect_text("今天去了一家小店，味道还不错。")
    assert _FEATURE_COUNT == 31
    assert len(report.features) == 31
    assert {item.group for item in report.features} == {
        "情感与社会锚定",
        "认知架构",
        "词汇身份与风格签名",
        "文本衔接流",
    }


def test_report_is_bounded_and_serialisable() -> None:
    report = inspect_text("总而言之，在这个快节奏的时代，我们不仅要努力，还要赋能自己。")
    assert isinstance(report, PladReport)
    assert 0.0 <= report.ai_likelihood <= 1.0
    assert 0.0 <= report.burstiness <= 1.5
    payload = report.as_dict()
    assert payload["feature_count"] == 31
    assert isinstance(payload["violations"], list)


def test_template_copy_gets_constraints() -> None:
    report = inspect_text(
        "在这个快节奏的时代，我们不仅要努力，还要赋能自己。综上所述，打造更好的生活。"
    )
    text = plad_constraints(report)
    assert "PLAD 去同质化约束" in text
    assert len(text) > 20


def test_human_scene_copy_has_low_ai_score() -> None:
    human = inspect_text(
        "昨天下午我去了巷口那家面包店，买了两个可颂。"
        "刚出炉的时候酥皮掉了一桌，我赶紧用手接着吃。老板娘说下午四点还有一炉。"
    )
    template = inspect_text(
        "在当今这个时代，烘焙不仅是一种生活方式，更是一种态度。"
        "总而言之，选择合适的面包店，能够帮助我们打造更加美好的生活。"
    )
    assert human.ai_likelihood < template.ai_likelihood


def test_empty_text_does_not_raise() -> None:
    report = inspect_text("")
    assert report.text_length == 0
    assert len(report.features) == 31
