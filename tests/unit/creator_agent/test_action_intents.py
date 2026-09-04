from __future__ import annotations

import pytest

from backend.creator_agent import (
    ActionCapability,
    ActionIntentRequest,
    ActionResolution,
    ActionResolutionDisposition,
    ActionStatus,
    CreatorAdvisor,
    CreatorModelDefinition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    Evidence,
    EvidenceSource,
)
from backend.creator_agent.repository import (
    ActionIntentMissingError,
    ActionResolutionConflictError,
    ActionValidationError,
    DecisionRecordMissingError,
)
from backend.db import creator_agent as creator_agent_db


@pytest.fixture(autouse=True)
def _reset_store():
    creator_agent_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()


def _definition() -> CreatorModelDefinition:
    return CreatorModelDefinition(
        identity_summary="可解释的选择顾问",
        policies=[
            DecisionPolicy(
                policy_id="p1",
                label="耐用优先",
                signal_weights={"durability": 1.0},
                rationale="长期使用先看耐用性。",
                evidence_ids=["e1"],
            )
        ],
        evidence=[
            Evidence(
                evidence_id="e1",
                source_kind=EvidenceSource.CREATOR_STATEMENT,
                source_ref="creator://statement/1",
                claim="我优先耐用性",
            )
        ],
    )


def _request(account_id: str = "account-a", audience_id: str = "audience-a") -> DecisionRequest:
    return DecisionRequest(
        account_id=account_id,
        audience_id=audience_id,
        goal="选择日常方案",
        candidates=[
            DecisionCandidate(candidate_id="a", label="A", signals={"durability": 0.9}),
            DecisionCandidate(candidate_id="b", label="B", signals={"durability": 0.2}),
            DecisionCandidate(candidate_id="c", label="C", signals={"durability": 0.1}),
        ],
    )


async def _advisor_with_decision(
    account_id: str = "account-a", audience_id: str = "audience-a"
) -> tuple[CreatorAdvisor, str]:
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model(account_id, _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request(account_id, audience_id))
    return advisor, decision.decision_id


@pytest.mark.asyncio
async def test_all_safe_capabilities_are_pending_and_idempotent():
    advisor, decision_id = await _advisor_with_decision()

    compare = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_id,
            action_kind=ActionCapability.COMPARE_OPTIONS,
            candidate_ids=["a", "b"],
            idempotency_key="compare-1",
        )
    )
    shortlist = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_id,
            action_kind=ActionCapability.SAVE_SHORTLIST,
            candidate_ids=["a"],
            idempotency_key="shortlist-1",
        )
    )
    evidence = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_id,
            action_kind=ActionCapability.REQUEST_MORE_EVIDENCE,
            idempotency_key="evidence-1",
        )
    )

    assert {compare.status, shortlist.status, evidence.status} == {
        ActionStatus.PENDING_CONFIRMATION
    }
    assert evidence.candidate_ids == []
    retry = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_id,
            action_kind=ActionCapability.COMPARE_OPTIONS,
            candidate_ids=["b", "c"],
            idempotency_key="compare-1",
        )
    )
    assert retry.model_dump() == compare.model_dump()
    assert len(await advisor.list_actions("account-a")) == 3


@pytest.mark.asyncio
async def test_candidate_and_status_invariants_do_not_write():
    advisor, decision_id = await _advisor_with_decision()

    with pytest.raises(ActionValidationError):
        await advisor.plan_action(
            ActionIntentRequest(
                account_id="account-a",
                decision_id=decision_id,
                action_kind=ActionCapability.COMPARE_OPTIONS,
                candidate_ids=["a"],
                idempotency_key="bad-count",
            )
        )
    with pytest.raises(ActionValidationError):
        await advisor.plan_action(
            ActionIntentRequest(
                account_id="account-a",
                decision_id=decision_id,
                action_kind=ActionCapability.SAVE_SHORTLIST,
                candidate_ids=["unknown"],
                idempotency_key="bad-candidate",
            )
        )
    with pytest.raises(ActionValidationError):
        await advisor.plan_action(
            ActionIntentRequest(
                account_id="account-a",
                decision_id=decision_id,
                action_kind=ActionCapability.REQUEST_MORE_EVIDENCE,
                candidate_ids=["a"],
                idempotency_key="bad-target",
            )
        )
    assert await advisor.list_actions("account-a") == []


@pytest.mark.asyncio
async def test_insufficient_decision_allows_only_request_more_evidence():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model(
        "account-a",
        CreatorModelDefinition(identity_summary="没有足够证据"),
        expected_revision=0,
    )
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(_request())
    assert decision.status.value == "insufficient_evidence"

    intent = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision.decision_id,
            action_kind=ActionCapability.REQUEST_MORE_EVIDENCE,
            idempotency_key="need-evidence",
        )
    )
    assert intent.status is ActionStatus.PENDING_CONFIRMATION
    with pytest.raises(ActionValidationError):
        await advisor.plan_action(
            ActionIntentRequest(
                account_id="account-a",
                decision_id=decision.decision_id,
                action_kind=ActionCapability.SAVE_SHORTLIST,
                candidate_ids=["a"],
                idempotency_key="bad-status",
            )
        )


@pytest.mark.asyncio
async def test_resolution_is_explicit_idempotent_and_conflict_safe():
    advisor, decision_id = await _advisor_with_decision()
    intent = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_id,
            action_kind=ActionCapability.SAVE_SHORTLIST,
            candidate_ids=["a"],
            idempotency_key="resolve-1",
        )
    )

    confirmed = await advisor.resolve_action(
        "account-a",
        intent.action_id,
        ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
    )
    assert confirmed.status is ActionStatus.CONFIRMED
    assert confirmed.resolved_at is not None
    repeated = await advisor.resolve_action(
        "account-a",
        intent.action_id,
        ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
    )
    assert repeated.model_dump() == confirmed.model_dump()
    with pytest.raises(ActionResolutionConflictError):
        await advisor.resolve_action(
            "account-a",
            intent.action_id,
            ActionResolution(disposition=ActionResolutionDisposition.CANCELLED),
        )
    with pytest.raises(ActionIntentMissingError):
        await advisor.resolve_action(
            "account-a",
            "missing",
            ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
        )


@pytest.mark.asyncio
async def test_action_idempotency_is_account_scoped():
    advisor_a, decision_a = await _advisor_with_decision("account-a", "audience-a")
    advisor_b, decision_b = await _advisor_with_decision("account-b", "audience-b")
    action_a = await advisor_a.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_a,
            action_kind=ActionCapability.SAVE_SHORTLIST,
            candidate_ids=["a"],
            idempotency_key="same-key",
        )
    )
    action_b = await advisor_b.plan_action(
        ActionIntentRequest(
            account_id="account-b",
            decision_id=decision_b,
            action_kind=ActionCapability.SAVE_SHORTLIST,
            candidate_ids=["b"],
            idempotency_key="same-key",
        )
    )
    assert action_a.action_id != action_b.action_id
    assert [item.account_id for item in await advisor_a.list_actions("account-a")] == ["account-a"]
    assert [item.account_id for item in await advisor_b.list_actions("account-b")] == ["account-b"]

    with pytest.raises(DecisionRecordMissingError):
        await advisor_a.plan_action(
            ActionIntentRequest(
                account_id="account-a",
                decision_id="missing",
                action_kind=ActionCapability.SAVE_SHORTLIST,
                candidate_ids=["a"],
                idempotency_key="new-key",
            )
        )
