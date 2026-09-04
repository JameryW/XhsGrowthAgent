from __future__ import annotations

import pytest

from backend.creator_agent import (
    CreatorAdvisor,
    CreatorModelDefinition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    Evidence,
    EvidenceReferenceType,
    EvidenceSource,
    FeedbackInput,
    FeedbackOutcome,
    KnowledgeClaim,
    Preference,
)
from backend.db import creator_agent as creator_agent_db


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


def _model(*, claim: str = "优先耐用") -> CreatorModelDefinition:
    return CreatorModelDefinition(
        identity_summary="重视可解释判断的创作者",
        preferences=[
            Preference(
                preference_id="p1",
                label="耐用",
                tags=["durable"],
                evidence_ids=["e-model"],
            )
        ],
        knowledge=[
            KnowledgeClaim(
                claim_id="k1",
                statement=claim,
                evidence_ids=["e-model"],
            )
        ],
        policies=[
            DecisionPolicy(
                policy_id="policy-1",
                label="耐用优先",
                signal_weights={"durability": 1.0},
                rationale="稳定性优先",
                evidence_ids=["e-model"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="e-model",
                source_kind=EvidenceSource.CREATOR_STATEMENT,
                source_ref="creator://statement/1",
                claim=claim,
            )
        ],
    )


def _request(account_id: str = "account-a") -> DecisionRequest:
    return DecisionRequest(
        account_id=account_id,
        audience_id="audience-a",
        goal="选择耐用品",
        candidates=[
            DecisionCandidate(
                candidate_id="candidate-a",
                label="耐用方案",
                tags=["durable"],
                signals={"durability": 0.9},
                evidence=[
                    Evidence(
                        evidence_id="e-candidate",
                        source_kind=EvidenceSource.PRODUCT_FACT,
                        source_ref="product://a",
                        claim="产品 A 使用寿命更长",
                    )
                ],
            ),
            DecisionCandidate(
                candidate_id="candidate-b",
                label="普通方案",
                signals={"durability": 0.2},
            ),
        ],
    )


@pytest.mark.asyncio
async def test_evidence_graph_links_model_decision_candidate_and_signal():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _model(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())
    feedback = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-1",
            audience_id="audience-a",
            outcome=FeedbackOutcome.DISSATISFIED,
            correction="更看重轻便",
        ),
    )

    entries = await advisor.list_evidence("account-a")
    assert [entry.evidence.evidence_id for entry in entries] == [
        "e-candidate",
        "e-model",
    ]
    model_entry = next(entry for entry in entries if entry.evidence.evidence_id == "e-model")
    refs = {
        (reference.reference_type, reference.target_id, reference.model_revision)
        for reference in model_entry.references
    }
    assert any(
        reference.reference_type is EvidenceReferenceType.MODEL and reference.model_revision == 1
        for reference in model_entry.references
    )
    assert (EvidenceReferenceType.PREFERENCE, "p1", 1) in refs
    assert (EvidenceReferenceType.KNOWLEDGE_CLAIM, "k1", 1) in refs
    assert (EvidenceReferenceType.DECISION_POLICY, "policy-1", 1) in refs
    assert (EvidenceReferenceType.DECISION, decision.decision_id, 1) in refs
    assert feedback.learning_signal is not None
    assert (
        EvidenceReferenceType.LEARNING_SIGNAL,
        feedback.learning_signal.signal_id,
        1,
    ) in refs

    candidate_entry = next(
        entry for entry in entries if entry.evidence.evidence_id == "e-candidate"
    )
    assert any(
        reference.reference_type is EvidenceReferenceType.CANDIDATE
        and reference.target_id == f"{decision.decision_id}:candidate-a"
        and reference.model_revision == 1
        for reference in candidate_entry.references
    )


@pytest.mark.asyncio
async def test_evidence_graph_filters_and_account_isolation():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _model(), expected_revision=0)
    await repo.save_model("account-b", _model(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())

    product = await advisor.list_evidence("account-a", EvidenceSource.PRODUCT_FACT)
    assert [entry.evidence.evidence_id for entry in product] == ["e-candidate"]
    decisions = await advisor.list_evidence(
        "account-a", reference_type=EvidenceReferenceType.DECISION
    )
    assert [entry.evidence.evidence_id for entry in decisions] == ["e-candidate", "e-model"]
    assert await advisor.get_evidence("account-a", "e-model") is not None
    assert await advisor.get_evidence("account-b", "e-candidate") is None
    assert await advisor.get_evidence("account-a", "missing") is None
    assert decision.account_id == "account-a"


@pytest.mark.asyncio
async def test_learning_signal_keeps_original_decision_evidence_snapshot():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _model(claim="第一版判断"), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())
    feedback = await advisor.record_feedback(
        "account-a",
        decision.decision_id,
        FeedbackInput(
            feedback_id="feedback-1",
            audience_id="audience-a",
            outcome=FeedbackOutcome.DISSATISFIED,
        ),
    )
    await repo.save_model("account-a", _model(claim="第二版判断"), expected_revision=1)

    entry = await advisor.get_evidence("account-a", "e-model")
    assert entry is not None
    assert entry.evidence.claim == "第一版判断"
    assert feedback.learning_signal is not None
    assert any(
        reference.reference_type is EvidenceReferenceType.LEARNING_SIGNAL
        for reference in entry.references
    )


@pytest.mark.asyncio
async def test_evidence_graph_order_and_reference_deduplication():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _model(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    first = await advisor.decide(_request())
    second = await advisor.decide(_request())

    entries = await advisor.list_evidence("account-a")
    assert [entry.evidence.evidence_id for entry in entries] == ["e-candidate", "e-model"]
    model_entry = entries[1]
    reference_keys = [
        (item.reference_type.value, item.target_id, item.model_revision)
        for item in model_entry.references
    ]
    assert reference_keys == sorted(
        reference_keys, key=lambda item: (item[0], item[1], item[2] or 0)
    )
    assert len(reference_keys) == len(set(reference_keys))
    assert first.decision_id != second.decision_id
