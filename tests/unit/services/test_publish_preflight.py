from __future__ import annotations

import pytest

from backend.services import publish_preflight
from backend.services.publish_preflight import (
    PublishPreflightReport,
    build_preflight,
    collect_effects,
    issue_summary,
    preflight_enabled,
    run_preflight,
)

TITLE = "川西自驾 7 天实测"


def _state(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "copy_content": {"selected_title": TITLE, "body_text": "路线和花费都写在下面。"},
        "visual_plan": {"image_prompts": ["封面：折多山垭口", "路线表", "清单"]},
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(publish_preflight.PREFLIGHT_ENV, raising=False)


def test_preflight_flag_is_off_by_default() -> None:
    assert preflight_enabled() is False


def test_preflight_flag_accepts_truthy_values(monkeypatch: pytest.MonkeyPatch) -> None:
    for value in ("1", "true", "YES", "on"):
        monkeypatch.setenv(publish_preflight.PREFLIGHT_ENV, value)
        assert preflight_enabled() is True
    monkeypatch.setenv(publish_preflight.PREFLIGHT_ENV, "0")
    assert preflight_enabled() is False


def test_run_preflight_is_unchecked_and_does_no_work_when_off() -> None:
    report = run_preflight(_state(copy_content={"body_text": "见图 9"}))
    assert report == PublishPreflightReport(checked=False, blocked=False)
    assert report.as_dict() == {"checked": False, "blocked": False, "issues": [], "effects": []}


def test_consistent_note_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(publish_preflight.PREFLIGHT_ENV, "1")
    report = run_preflight(_state())
    assert report.checked is True
    assert report.blocked is False
    assert report.issues == ()


def test_empty_state_passes_without_crashing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(publish_preflight.PREFLIGHT_ENV, "1")
    report = run_preflight({})
    assert report.checked is True
    assert report.blocked is False


def test_referenced_card_missing_blocks_the_publish() -> None:
    state = _state(
        copy_content={"selected_title": TITLE, "body_text": "实测对比表见图 2。"},
        visual_plan={"image_prompts": ["封面"]},
    )
    report = build_preflight(state)
    assert report.blocked is True
    assert [issue.reason for issue in report.issues] == ["referenced_card_missing"]
    assert report.issues[0].edge == "coupling"
    assert report.issues[0].target == "carousel[2]"


def test_chinese_ordinal_card_reference_is_honoured() -> None:
    missing = build_preflight(
        _state(
            copy_content={"body_text": "第三张图是花费表。"},
            visual_plan={"image_prompts": ["封面", "路线"]},
        )
    )
    assert missing.blocked is True
    present = build_preflight(
        _state(
            copy_content={"body_text": "第三张图是花费表。"},
            visual_plan={"image_prompts": ["封面", "路线", "花费"]},
        )
    )
    assert present.blocked is False


def test_left_swipe_without_a_carousel_blocks_the_publish() -> None:
    report = build_preflight(
        _state(
            copy_content={"body_text": "左滑看完整清单。"},
            visual_plan={"image_prompts": ["封面"]},
        )
    )
    assert report.blocked is True
    assert [issue.reason for issue in report.issues] == ["left_swipe_without_carousel"]


def test_pinned_comment_promise_needs_a_scheduled_effect() -> None:
    body = {"body_text": "置顶评论里放了路书链接。"}
    blocked = build_preflight(_state(copy_content=body))
    assert blocked.blocked is True
    assert [issue.reason for issue in blocked.issues] == ["pinned_comment_not_scheduled"]

    scheduled = build_preflight(_state(copy_content={**body, "pinned_comment": "路书在这里"}))
    assert scheduled.blocked is False
    assert "pinned_comment" in scheduled.effects


def test_commercial_body_needs_a_disclosure_effect() -> None:
    body = {"body_text": "这次是蒲公英合作的实测。"}
    blocked = build_preflight(_state(copy_content=body))
    assert blocked.blocked is True
    assert [issue.reason for issue in blocked.issues] == [
        "commercial_note_without_disclosure_effect"
    ]

    declared = build_preflight(
        _state(copy_content=body, publish_options={"disclosure_confirmed": True})
    )
    assert declared.blocked is False
    assert "commercial_disclosure" in declared.effects


def test_collect_effects_derives_each_canonical_effect() -> None:
    effects = collect_effects(
        {
            "workflow_mode": "brief",
            "publish_options": {"schedule_time": "2026-01-01T20:00:00", "pinned_comment": True},
            "content_versions": [{"label": "a"}, {"label": "b"}],
        }
    )
    assert effects == ("commercial_disclosure", "pinned_comment", "ab_test", "schedule")


def test_collect_effects_reads_pinned_actions_and_defaults_to_empty() -> None:
    assert collect_effects({}) == ()
    assert collect_effects(
        {"engagement_actions": [{"action_type": "pin_comment", "target_id": "note-1"}]}
    ) == ("pinned_comment",)
    assert collect_effects(
        {"engagement_actions": [{"action_type": "reply_comment", "content": "已置顶"}]}
    ) == ("pinned_comment",)
    assert collect_effects({"engagement_actions": [{"action_type": "like"}]}) == ()


def test_issue_summary_is_bounded_and_readable() -> None:
    report = build_preflight(
        _state(
            copy_content={"body_text": "见图 2、左滑看清单、置顶评论领路书。"},
            visual_plan={"image_prompts": ["封面"]},
        )
    )
    assert len(report.issues) >= 3
    summary = issue_summary(report.issues, limit=2)
    assert summary.count("；") == 1
    assert "coupling:body->carousel[2]" in summary
    assert issue_summary(()) == ""


def test_wire_facts_are_stable_for_telemetry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(publish_preflight.PREFLIGHT_ENV, "1")
    report = run_preflight(
        _state(
            copy_content={"selected_title": TITLE, "body_text": "见图 2", "hashtags": ["川西"]},
            visual_plan={"image_paths": ["/tmp/a.png"]},
        )
    )
    payload = report.as_dict()
    assert payload["checked"] is True
    assert payload["blocked"] is True
    assert payload["effects"] == []
    assert payload["issues"][0]["target"] == "carousel[2]"
