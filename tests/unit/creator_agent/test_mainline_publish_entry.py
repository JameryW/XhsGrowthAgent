"""P3b-2 (票 5bg): the mainline's single execution entry.

Every in-repo mainline real publish goes through
``creator_agent.mainline_publish.execute_mainline_publish``.  These pin the one
job the entry has that the private attempt cannot do: resolving *whose decision*
this publish executes, without rewriting an existing approval and without
inventing one for a deployment or an unreviewed path.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.creator_agent.mainline_publish import (
    FREE_PUBLISH_OPERATOR_SOURCE,
    execute_mainline_publish,
)

_ATTEMPT = "backend.agents.publisher._run_publish_attempt"


def _state(**overrides):
    base = {
        "account_id": "workflow-label",
        "session_id": "thread-entry-1",
        "copy_content": {"selected_title": "标题", "body_text": "正文", "hashtags": ["x"]},
        "visual_plan": {"image_paths": ["/tmp/a.png"]},
        "publish_options": {"dry_run": False, "account_id": "account-a"},
    }
    base.update(overrides)
    return base


@pytest.fixture
def attempt(monkeypatch):
    recorded = AsyncMock(
        return_value={"publish_result": {"status": "published"}, "phase": "publishing"}
    )
    monkeypatch.setattr(_ATTEMPT, recorded)
    return recorded


async def test_an_existing_decision_is_passed_through_untouched(attempt):
    decision = {
        "decision_id": "mainline:review-1",
        "source": "mainline_review",
        "thread_id": "thread-entry-1",
        "account_id": "account-a",
        "content_hash": "a" * 64,
        "approved_by": "user-1",
        "approved_at": "2026-11-01T00:00:00+00:00",
    }
    state = _state(publish_decision=decision)

    result = await execute_mainline_publish(state, store=object(), operator_id="user-1")

    assert result["publish_result"]["status"] == "published"
    attempt.assert_awaited_once()
    forwarded = attempt.await_args.args[0]
    assert forwarded["publish_decision"] is decision
    assert state["publish_decision"] is decision  # the caller's dict still owns it


async def test_a_free_publish_gets_an_operator_decision(attempt):
    state = _state()

    await execute_mainline_publish(state, store=object(), operator_id="user-1")

    forwarded = attempt.await_args.args[0]
    decision = forwarded["publish_decision"]
    assert decision["source"] == FREE_PUBLISH_OPERATOR_SOURCE
    assert decision["decision_id"].startswith("mainline:operator:")
    assert decision["account_id"] == "account-a"
    assert decision["thread_id"] == "thread-entry-1"
    assert decision["approved_by"] == "user-1"
    assert decision["approved_at"]
    assert len(decision["content_hash"]) == 64
    assert "publish_decision" not in state


async def test_without_an_operator_nothing_is_invented(attempt):
    state = _state()

    await execute_mainline_publish(state, store=object())

    forwarded = attempt.await_args.args[0]
    assert "publish_decision" not in forwarded


async def test_an_operator_identity_needs_an_account(attempt):
    state = _state(publish_options={})

    await execute_mainline_publish(state, store=object(), operator_id="user-1")

    forwarded = attempt.await_args.args[0]
    assert "publish_decision" not in forwarded


async def test_an_existing_decision_is_never_replaced_by_the_operator(attempt):
    decision = {
        "decision_id": "mainline:review-1",
        "source": "mainline_review",
        "thread_id": "thread-entry-1",
        "account_id": "account-a",
        "content_hash": "a" * 64,
        "approved_by": "reviewer-9",
        "approved_at": "2026-11-01T00:00:00+00:00",
    }
    state = _state(publish_decision=decision)

    await execute_mainline_publish(state, store=object(), operator_id="retrier-1")

    forwarded = attempt.await_args.args[0]
    assert forwarded["publish_decision"] is decision
    assert forwarded["publish_decision"]["approved_by"] == "reviewer-9"
