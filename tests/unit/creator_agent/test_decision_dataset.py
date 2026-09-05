from __future__ import annotations

import pytest

from backend.creator_agent import (
    DecisionDatasetPage,
    DecisionRecord,
    DecisionStatus,
    FeedbackOutcome,
    LearningSignal,
    build_decision_dataset_page,
    decode_decision_dataset_cursor,
    encode_decision_dataset_cursor,
)
from backend.creator_agent.models import UserFeedback
from backend.db import creator_agent as creator_agent_db


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


def _decision(
    decision_id: str,
    *,
    account_id: str = "account-a",
    audience_id: str = "audience-a",
    created_at: str = "2026-09-05T10:00:00+00:00",
    status: DecisionStatus = DecisionStatus.RECOMMENDED,
    feedback: list[UserFeedback] | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        decision_id=decision_id,
        account_id=account_id,
        audience_id=audience_id,
        creator_id="creator-a",
        model_revision=3,
        goal="选择一件耐用品",
        status=status,
        feedback=feedback or [],
        created_at=created_at,
        updated_at=created_at,
    )


def _feedback(feedback_id: str, outcome: FeedbackOutcome) -> UserFeedback:
    return UserFeedback(
        feedback_id=feedback_id,
        audience_id="audience-a",
        outcome=outcome,
        created_at="2026-09-05T11:00:00+00:00",
    )


def _signal(signal_id: str, decision_id: str, *, account_id: str = "account-a") -> LearningSignal:
    return LearningSignal(
        signal_id=signal_id,
        account_id=account_id,
        creator_id="creator-a",
        audience_id="audience-a",
        decision_id=decision_id,
        feedback_id=f"feedback-{signal_id}",
        summary="需要复核",
        created_at="2026-09-05T11:00:00+00:00",
        updated_at="2026-09-05T11:00:00+00:00",
    )


def test_cursor_is_versioned_and_rejects_malformed_tokens() -> None:
    cursor = encode_decision_dataset_cursor("2026-09-05T10:00:00+00:00", "decision-1")
    assert decode_decision_dataset_cursor(cursor) == (
        "2026-09-05T10:00:00+00:00",
        "decision-1",
    )
    with pytest.raises(ValueError, match="invalid decision dataset cursor"):
        decode_decision_dataset_cursor("not-a-cursor")


def test_projection_preserves_snapshot_filters_and_signal_links() -> None:
    first = _decision(
        "decision-1",
        created_at="2026-09-05T10:00:00+00:00",
        feedback=[_feedback("feedback-1", FeedbackOutcome.PURCHASED)],
    )
    second = _decision(
        "decision-2",
        created_at="2026-09-05T10:00:00+00:00",
        audience_id="audience-b",
        status=DecisionStatus.INSUFFICIENT_EVIDENCE,
    )
    original = first.model_dump(mode="json")
    page = build_decision_dataset_page(
        [second, first],
        [_signal("signal-z", first.decision_id), _signal("signal-a", first.decision_id)],
        status=DecisionStatus.RECOMMENDED,
        feedback_outcome=FeedbackOutcome.PURCHASED,
        has_feedback=True,
        limit=20,
    )
    assert isinstance(page, DecisionDatasetPage)
    assert page.total == 1
    assert page.items[0].decision.model_dump(mode="json") == original
    assert page.items[0].learning_signal_ids == ["signal-a", "signal-z"]
    assert page.next_cursor is None


@pytest.mark.asyncio
async def test_memory_repository_paginates_with_complete_total_and_isolation() -> None:
    repository = creator_agent_db.get_repository()
    decisions = [
        _decision("decision-a", created_at="2026-09-05T10:02:00+00:00"),
        _decision("decision-b", created_at="2026-09-05T10:01:00+00:00"),
        _decision("decision-c", created_at="2026-09-05T10:00:00+00:00"),
        _decision("foreign", account_id="account-b", created_at="2026-09-05T10:03:00+00:00"),
    ]
    for decision in decisions:
        await repository.create_decision(decision)

    first = await repository.list_decision_dataset("account-a", limit=2)
    assert [item.decision.decision_id for item in first.items] == ["decision-a", "decision-b"]
    assert first.total == 3
    assert first.next_cursor is not None
    second = await repository.list_decision_dataset("account-a", cursor=first.next_cursor, limit=2)
    assert [item.decision.decision_id for item in second.items] == ["decision-c"]
    assert second.total == 3
    assert second.next_cursor is None
    assert (await repository.list_decision_dataset("account-b")).items[0].decision.decision_id == (
        "foreign"
    )


def test_projection_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError, match="limit"):
        build_decision_dataset_page([], [], limit=0)
