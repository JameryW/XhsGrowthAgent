"""Action / artifact projections onto judger state (no duplicated rule tables)."""

from __future__ import annotations

from backend.services.compliance.projection import (
    project_action_plan_state,
    project_artifact_body_for_judgers,
)


def test_plan_projection_carries_account_level_flags() -> None:
    state = project_action_plan_state(
        account_id="acc-1",
        niche="医美",
        auto_publish=True,
        publish_eligibility={"allowed": False, "blocking_failures": ["lexicon"]},
    )
    assert state["account_id"] == "acc-1"
    assert state["niche"] == "医美"
    assert state["auto_publish"] is True
    assert state["content_plan"]["niche"] == "医美"
    assert state["evaluation_result"]["publish_eligibility"]["allowed"] is False
    assert state["copy_content"]["body_text"] == ""


def test_artifact_projection_prefers_parsed_title_body() -> None:
    state = project_artifact_body_for_judgers(
        {"title": "ignored", "body": "ignored", "niche": "旅游"},
        account_id="acc-1",
        title="周末散步",
        text="公园里很舒服",
    )
    assert state["copy_content"]["selected_title"] == "周末散步"
    assert state["copy_content"]["body_text"] == "公园里很舒服"
    assert state["niche"] == "旅游"
