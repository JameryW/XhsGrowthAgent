from __future__ import annotations

import pytest

from backend.creator_agent import (
    CreatorAdvisor,
    CreatorModelDefinition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    DecisionStatus,
    Evidence,
    EvidenceSource,
    FeedbackInput,
    FeedbackOutcome,
    Preference,
    PreferenceStance,
)
from backend.creator_agent.repository import CreatorModelRevisionConflictError
from backend.db import creator_agent as creator_agent_db


def _definition(*, with_policy: bool = True) -> CreatorModelDefinition:
    evidence = Evidence(
        evidence_id="statement-1",
        source_kind=EvidenceSource.CREATOR_STATEMENT,
        source_ref="creator://statement/1",
        claim="优先选择耐用、低维护的方案",
        confidence=0.9,
    )
    policies = (
        [
            DecisionPolicy(
                policy_id="durability-first",
                label="耐用优先",
                applies_when={"scene": "daily"},
                signal_weights={"durability": 0.8, "price": 0.2},
                excluded_tags=["high-maintenance"],
                rationale="长期使用时先保证稳定性，再看价格。",
                evidence_ids=["statement-1"],
            )
        ]
        if with_policy
        else []
    )
    return CreatorModelDefinition(
        identity_summary="重视长期体验和可解释权衡的生活方式创作者",
        domains=["生活方式"],
        preferences=[
            Preference(
                preference_id="low-maintenance",
                label="低维护",
                stance=PreferenceStance.PREFER,
                tags=["low-maintenance"],
                strength=0.8,
                evidence_ids=["statement-1"],
            )
        ],
        policies=policies,
        evidence=[evidence],
    )


def _request(account_id: str = "account-a") -> DecisionRequest:
    return DecisionRequest(
        account_id=account_id,
        audience_id="audience-a",
        goal="选一个适合每天使用的方案",
        context={"scene": "daily"},
        candidates=[
            DecisionCandidate(
                candidate_id="candidate-a",
                label="耐用方案",
                tags=["low-maintenance"],
                signals={"durability": 0.95, "price": 0.4},
            ),
            DecisionCandidate(
                candidate_id="candidate-b",
                label="便宜方案",
                tags=["high-maintenance"],
                signals={"durability": 0.4, "price": 0.95},
            ),
        ],
    )


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


@pytest.mark.asyncio
async def test_decision_is_ranked_and_evidence_backed():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    model = await repo.save_model("account-a", _definition(), expected_revision=0)
    decision = await CreatorAdvisor(repo).decide(_request())

    assert decision.status is DecisionStatus.RECOMMENDED
    assert decision.model_revision == model.revision == 1
    assert [item.candidate_id for item in decision.recommendations] == ["candidate-a"]
    assert decision.excluded_candidates[0].candidate_id == "candidate-b"
    assert "policy:durability-first:excluded_tag:high-maintenance" in (
        decision.excluded_candidates[0].reasons
    )
    assert decision.recommendations[0].evidence_ids == ["statement-1"]
    assert decision.evidence[0].source_ref == "creator://statement/1"
    assert decision.confidence > 0


@pytest.mark.asyncio
async def test_missing_policy_is_explicitly_insufficient():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(with_policy=False), expected_revision=0)

    decision = await CreatorAdvisor(repo).decide(_request())

    assert decision.status is DecisionStatus.INSUFFICIENT_EVIDENCE
    assert decision.recommendations == []
    assert decision.confidence == 0


@pytest.mark.asyncio
async def test_policy_context_requires_exact_match():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)

    request = _request()
    request.context = {"scene": "daily", "audience": "new"}
    decision = await CreatorAdvisor(repo).decide(request)

    assert decision.status is DecisionStatus.INSUFFICIENT_EVIDENCE
    assert decision.matched_policy_ids == []


@pytest.mark.asyncio
async def test_feedback_is_idempotent_and_does_not_mutate_model():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    model = await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())
    feedback = FeedbackInput(
        feedback_id="feedback-1",
        audience_id="audience-a",
        outcome=FeedbackOutcome.DISSATISFIED,
        selected_candidate_id="candidate-a",
        correction="我更在意轻便，而不是耐用。",
    )

    first = await advisor.record_feedback("account-a", decision.decision_id, feedback)
    second = await advisor.record_feedback("account-a", decision.decision_id, feedback)
    current_model = await repo.get_model("account-a")

    assert first.created is True
    assert second.created is False
    assert first.learning_status.value == "pending_creator_review"
    assert first.relationship.interaction_count == 1
    assert first.relationship.rejected_candidate_ids == ["candidate-a"]
    assert len(second.decision.feedback) == 1
    assert current_model is not None
    assert current_model.revision == model.revision
    assert current_model.model_dump() == model.model_dump()


@pytest.mark.asyncio
async def test_feedback_retry_uses_persisted_learning_status():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())

    first = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-1",
            audience_id="audience-a",
            outcome=FeedbackOutcome.ACCEPTED,
        ),
    )
    retry = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-1",
            audience_id="audience-a",
            outcome=FeedbackOutcome.DISSATISFIED,
            correction="retry payload must not replace the original",
        ),
    )

    assert first.learning_status.value == "observed"
    assert retry.created is False
    assert retry.learning_status.value == "observed"
    assert retry.decision.feedback[0].outcome is FeedbackOutcome.ACCEPTED


@pytest.mark.asyncio
async def test_model_revision_conflict_preserves_current_revision():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)

    with pytest.raises(CreatorModelRevisionConflictError) as exc_info:
        await repo.save_model("account-a", _definition(), expected_revision=0)

    assert exc_info.value.actual == 1
    assert (await repo.get_model("account-a")).revision == 1
