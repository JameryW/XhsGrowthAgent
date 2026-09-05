from __future__ import annotations

import pytest

from backend.creator_agent import (
    ActionCapability,
    ActionExecutionStatus,
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
    ActionExecutionNotAllowedError,
    ActionIntentMissingError,
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


async def _advisor_with_decision() -> tuple[CreatorAdvisor, str]:
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
    decision = await advisor.decide(
        DecisionRequest(
            account_id="account-a",
            audience_id="audience-a",
            goal="选择日常方案",
            candidates=[
                DecisionCandidate(candidate_id="a", label="A", signals={"durability": 0.9}),
                DecisionCandidate(candidate_id="b", label="B", signals={"durability": 0.2}),
                DecisionCandidate(candidate_id="c", label="C", signals={"durability": 0.1}),
            ],
        )
    )
    return advisor, decision.decision_id


async def _confirmed_action(
    advisor: CreatorAdvisor,
    decision_id: str,
    capability: ActionCapability,
    *,
    candidate_ids: list[str] | None = None,
    key: str = "execute-1",
):
    action = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_id,
            action_kind=capability,
            candidate_ids=candidate_ids or [],
            idempotency_key=key,
        )
    )
    return await advisor.resolve_action(
        "account-a",
        action.action_id,
        ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
    )


@pytest.mark.asyncio
async def test_each_safe_capability_emits_a_deterministic_receipt():
    advisor, decision_id = await _advisor_with_decision()

    compare = await _confirmed_action(
        advisor, decision_id, ActionCapability.COMPARE_OPTIONS, candidate_ids=["a", "b"], key="c"
    )
    compare_receipt = await advisor.execute_action("account-a", compare.action_id)
    assert compare_receipt.status is ActionExecutionStatus.SUCCEEDED
    assert compare_receipt.action_id == compare.action_id
    assert compare_receipt.decision_id == decision_id
    assert compare_receipt.executor_version == "local-v1"
    assert compare_receipt.result["candidate_ids"] == ["a", "b"]
    assert [item["candidate_id"] for item in compare_receipt.result["candidates"]] == ["a", "b"]
    assert all(
        "score" in item and "rationale" in item and "evidence_ids" in item
        for item in compare_receipt.result["candidates"]
    )

    shortlist = await _confirmed_action(
        advisor, decision_id, ActionCapability.SAVE_SHORTLIST, candidate_ids=["a"], key="s"
    )
    shortlist_receipt = await advisor.execute_action("account-a", shortlist.action_id)
    assert shortlist_receipt.result == {
        "decision_id": decision_id,
        "candidate_ids": ["a"],
        "saved": True,
    }

    evidence = await _confirmed_action(
        advisor, decision_id, ActionCapability.REQUEST_MORE_EVIDENCE, key="e"
    )
    evidence_receipt = await advisor.execute_action("account-a", evidence.action_id)
    assert evidence_receipt.result["decision_id"] == decision_id
    assert evidence_receipt.result["decision_status"] == "recommended"
    assert set(evidence_receipt.result) >= {
        "decision_id",
        "decision_status",
        "evidence_coverage",
        "confidence",
    }


@pytest.mark.asyncio
async def test_execution_requires_confirmation_and_is_idempotent():
    advisor, decision_id = await _advisor_with_decision()
    action = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_id,
            action_kind=ActionCapability.SAVE_SHORTLIST,
            candidate_ids=["a"],
            idempotency_key="pending",
        )
    )
    with pytest.raises(ActionExecutionNotAllowedError):
        await advisor.execute_action("account-a", action.action_id)
    assert await advisor.get_action_execution("account-a", action.action_id) is None

    confirmed = await advisor.resolve_action(
        "account-a",
        action.action_id,
        ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
    )
    first = await advisor.execute_action("account-a", confirmed.action_id)
    repeated = await advisor.execute_action("account-a", confirmed.action_id)
    fetched = await advisor.get_action_execution("account-a", confirmed.action_id)
    assert repeated.model_dump() == first.model_dump()
    assert fetched is not None
    assert fetched.model_dump() == first.model_dump()


@pytest.mark.asyncio
async def test_cancelled_and_foreign_actions_leave_no_receipt():
    advisor, decision_id = await _advisor_with_decision()
    action = await advisor.plan_action(
        ActionIntentRequest(
            account_id="account-a",
            decision_id=decision_id,
            action_kind=ActionCapability.SAVE_SHORTLIST,
            candidate_ids=["a"],
            idempotency_key="cancelled",
        )
    )
    cancelled = await advisor.resolve_action(
        "account-a",
        action.action_id,
        ActionResolution(disposition=ActionResolutionDisposition.CANCELLED),
    )
    with pytest.raises(ActionExecutionNotAllowedError) as exc_info:
        await advisor.execute_action("account-a", cancelled.action_id)
    assert exc_info.value.status is ActionStatus.CANCELLED
    assert await advisor.get_action_execution("account-a", cancelled.action_id) is None
    with pytest.raises(ActionIntentMissingError):
        await advisor.execute_action("account-b", cancelled.action_id)
