from __future__ import annotations

import pytest

from backend.creator_agent import (
    CreatorAdvisor,
    CreatorModelDefinition,
    CreatorReviewDisposition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    Evidence,
    EvidenceSource,
    FeedbackInput,
    FeedbackOutcome,
    LearningSignalReview,
    LearningSignalStatus,
)
from backend.creator_agent.repository import (
    CreatorModelRevisionConflictError,
    CreatorReviewModelRequiredError,
    LearningSignalReviewConflictError,
)
from backend.db import creator_agent as creator_agent_db


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


def _definition(identity: str = "耐用体验创作者") -> CreatorModelDefinition:
    evidence = Evidence(
        evidence_id="e1",
        source_kind=EvidenceSource.CREATOR_STATEMENT,
        source_ref="creator://statement/1",
        claim="优先选择耐用的方案",
    )
    return CreatorModelDefinition(
        identity_summary=identity,
        policies=[
            DecisionPolicy(
                policy_id="p1",
                label="耐用优先",
                signal_weights={"durability": 1.0},
                rationale="长期使用先看耐用性。",
                evidence_ids=["e1"],
            )
        ],
        evidence=[evidence],
    )


def _request() -> DecisionRequest:
    return DecisionRequest(
        account_id="account-a",
        audience_id="audience-a",
        goal="选择日常方案",
        candidates=[
            DecisionCandidate(candidate_id="a", label="A", signals={"durability": 0.9}),
            DecisionCandidate(candidate_id="b", label="B", signals={"durability": 0.2}),
        ],
    )


@pytest.mark.asyncio
async def test_feedback_creates_stable_evidence_snapshot_and_retry_is_idempotent():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())
    feedback = FeedbackInput(
        feedback_id="feedback-1",
        audience_id="audience-a",
        outcome=FeedbackOutcome.DISSATISFIED,
        correction="更在意便携性。",
    )

    first = await advisor.record_feedback("account-a", decision.decision_id, feedback)
    retry = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-1",
            audience_id="audience-a",
            outcome=FeedbackOutcome.ACCEPTED,
            correction="retry must not replace the original",
        ),
    )

    assert first.created is True
    assert first.learning_signal is not None
    assert first.learning_signal.status is LearningSignalStatus.PENDING_CREATOR_REVIEW
    assert first.learning_signal.evidence_ids == ["e1"]
    assert retry.created is False
    assert retry.learning_signal is not None
    assert retry.learning_signal.signal_id == first.learning_signal.signal_id
    assert retry.learning_signal.correction == "更在意便携性。"

    listed = await advisor.list_learning_signals(
        "account-a", LearningSignalStatus.PENDING_CREATOR_REVIEW
    )
    assert [signal.signal_id for signal in listed] == [first.learning_signal.signal_id]


@pytest.mark.asyncio
async def test_whitespace_only_correction_does_not_create_learning_signal():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())

    result = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-whitespace",
            audience_id="audience-a",
            outcome=FeedbackOutcome.ACCEPTED,
            correction="   ",
        ),
    )

    assert result.learning_status.value == "observed"
    assert result.learning_signal is None
    assert await advisor.list_learning_signals("account-a") == []


@pytest.mark.asyncio
async def test_dismissal_is_model_neutral_and_conflicting_review_fails():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    initial = await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())
    feedback = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-2",
            audience_id="audience-a",
            outcome=FeedbackOutcome.DISSATISFIED,
        ),
    )
    signal = feedback.learning_signal
    assert signal is not None

    reviewed = await advisor.review_learning_signal(
        "account-a",
        signal.signal_id,
        LearningSignalReview(
            disposition=CreatorReviewDisposition.DISMISSED,
            review_note="一次性偏好，不纳入模型。",
        ),
    )
    current = await repo.get_model("account-a")
    assert reviewed.signal.status is LearningSignalStatus.DISMISSED
    assert reviewed.signal.applied_model_revision is None
    assert current is not None
    assert current.revision == initial.revision
    assert current.model_dump() == initial.model_dump()

    with pytest.raises(LearningSignalReviewConflictError):
        await advisor.review_learning_signal(
            "account-a",
            signal.signal_id,
            LearningSignalReview(
                disposition=CreatorReviewDisposition.APPROVED,
                expected_revision=initial.revision,
                model=_definition("不应被应用"),
            ),
        )


@pytest.mark.asyncio
async def test_approval_requires_complete_model_and_is_optimistic_concurrency_safe():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    initial = await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())
    feedback = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-3",
            audience_id="audience-a",
            outcome=FeedbackOutcome.DISSATISFIED,
            correction="更轻便。",
        ),
    )
    signal = feedback.learning_signal
    assert signal is not None

    with pytest.raises(CreatorReviewModelRequiredError):
        await advisor.review_learning_signal(
            "account-a",
            signal.signal_id,
            LearningSignalReview(disposition=CreatorReviewDisposition.APPROVED),
        )

    with pytest.raises(CreatorModelRevisionConflictError):
        await advisor.review_learning_signal(
            "account-a",
            signal.signal_id,
            LearningSignalReview(
                disposition=CreatorReviewDisposition.APPROVED,
                expected_revision=0,
                model=_definition("错误并发版本"),
            ),
        )
    unchanged = await repo.get_learning_signal("account-a", signal.signal_id)
    assert unchanged is not None
    assert unchanged.status is LearningSignalStatus.PENDING_CREATOR_REVIEW
    assert (await repo.get_model("account-a")).revision == initial.revision

    approved = await advisor.review_learning_signal(
        "account-a",
        signal.signal_id,
        LearningSignalReview(
            disposition=CreatorReviewDisposition.APPROVED,
            expected_revision=initial.revision,
            model=_definition("加入便携性权衡"),
        ),
    )
    assert approved.signal.status is LearningSignalStatus.APPROVED
    assert approved.signal.applied_model_revision == initial.revision + 1
    assert approved.model is not None
    assert approved.model.revision == initial.revision + 1

    repeated = await advisor.review_learning_signal(
        "account-a",
        signal.signal_id,
        LearningSignalReview(
            disposition=CreatorReviewDisposition.APPROVED,
            expected_revision=0,
            model=_definition("重复请求应被忽略"),
        ),
    )
    assert repeated.signal.model_dump() == approved.signal.model_dump()
