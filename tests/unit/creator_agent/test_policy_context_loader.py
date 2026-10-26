"""Plan-time auto-load of stamped publish eligibility from thread checkpoint."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.creator_agent import (
    ActionCapability,
    ActionIntentRequest,
    ActionPolicyContext,
    ActionPolicyDeniedError,
    CreatorAdvisor,
    CreatorModelDefinition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    Evidence,
    EvidenceSource,
    PolicyId,
    load_action_policy_context_from_thread,
)
from backend.creator_agent.policy_context import (
    EligibilityContextUnavailableError,
    thread_policy_context_loader,
)
from backend.db import creator_agent as creator_agent_db
from backend.services.xhs_risk_gate import reset_gates_for_tests

SHA = "a" * 64
REF = "artifact://publish/p1"
THREAD = "thread-stamp-1"


@pytest.fixture(autouse=True)
def _reset():
    creator_agent_db._reset_memory_store()
    reset_gates_for_tests()
    yield
    creator_agent_db._reset_memory_store()
    reset_gates_for_tests()


def _graph_with_values(values: dict[str, Any] | None, *, raises: Exception | None = None) -> Any:
    graph = MagicMock()
    if raises is not None:
        graph.aget_state = AsyncMock(side_effect=raises)
    else:
        graph.aget_state = AsyncMock(return_value=SimpleNamespace(values=values))
    return graph


def _request(**overrides: Any) -> ActionIntentRequest:
    base: dict[str, Any] = {
        "account_id": "account-a",
        "decision_id": "decision-1",
        "action_kind": ActionCapability.PUBLISH,
        "idempotency_key": "publish-stamp-1",
        "artifact_ref": REF,
        "content_hash": SHA,
        "thread_id": THREAD,
    }
    base.update(overrides)
    return ActionIntentRequest(**base)


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


async def _advisor_with_decision(
    *,
    policy_context_loader: Any | None = None,
) -> tuple[CreatorAdvisor, str]:
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo, policy_context_loader=policy_context_loader)
    decision = await advisor.decide(
        DecisionRequest(
            account_id="account-a",
            audience_id="audience-a",
            goal="选一个更耐用的方案",
            candidates=[
                DecisionCandidate(candidate_id="a", label="A", signals={"durability": 0.9}),
                DecisionCandidate(candidate_id="b", label="B", signals={"durability": 0.2}),
            ],
        )
    )
    return advisor, decision.decision_id


class TestLoadActionPolicyContextFromThread:
    @pytest.mark.asyncio
    async def test_reads_stamped_eligibility_and_account_fields(self):
        graph = _graph_with_values(
            {
                "evaluation_result": {
                    "publish_eligibility": {
                        "allowed": False,
                        "blocking_failures": ["lexicon"],
                    }
                },
                "niche": "医美",
                "auto_publish": True,
                "is_commercial": True,
                "human_feedback": {"source": "auto_low_risk", "decision": "approved"},
            }
        )
        ctx = await load_action_policy_context_from_thread(THREAD, "account-a", graph=graph)
        assert ctx.publish_eligibility is not None
        assert ctx.publish_eligibility["allowed"] is False
        assert ctx.niche == "医美"
        assert ctx.auto_publish is True
        assert ctx.is_commercial is True
        assert ctx.extra is not None
        assert ctx.extra["human_feedback"]["source"] == "auto_low_risk"
        graph.aget_state.assert_awaited_once_with({"configurable": {"thread_id": THREAD}})

    @pytest.mark.asyncio
    async def test_missing_stamp_returns_none_eligibility(self):
        graph = _graph_with_values({"niche": "生活方式", "auto_publish": False, "session_id": "s1"})
        ctx = await load_action_policy_context_from_thread(THREAD, graph=graph)
        assert ctx.publish_eligibility is None
        assert ctx.niche == "生活方式"

    @pytest.mark.asyncio
    async def test_niche_falls_back_to_content_plan(self):
        graph = _graph_with_values({"content_plan": {"niche": "美妆"}, "session_id": "s1"})
        ctx = await load_action_policy_context_from_thread(THREAD, graph=graph)
        assert ctx.niche == "美妆"

    @pytest.mark.asyncio
    async def test_brief_mode_marks_commercial_via_mode_spec(self):
        """Compliance baseline: commercial via mode_spec, not bare is_commercial."""
        graph = _graph_with_values({"workflow_mode": "brief", "session_id": "s1"})
        ctx = await load_action_policy_context_from_thread(THREAD, graph=graph)
        assert ctx.is_commercial is True

    @pytest.mark.asyncio
    async def test_graph_none_fails_closed(self):
        with pytest.raises(EligibilityContextUnavailableError, match="graph is unavailable"):
            await load_action_policy_context_from_thread(THREAD, graph=None)

    @pytest.mark.asyncio
    async def test_aget_state_failure_fails_closed(self):
        graph = _graph_with_values(None, raises=RuntimeError("checkpointer down"))
        with pytest.raises(EligibilityContextUnavailableError, match="could not be read"):
            await load_action_policy_context_from_thread(THREAD, graph=graph)

    @pytest.mark.asyncio
    async def test_empty_checkpoint_fails_closed(self):
        graph = _graph_with_values({})
        with pytest.raises(EligibilityContextUnavailableError, match="no readable values"):
            await load_action_policy_context_from_thread(THREAD, graph=graph)


class TestPlanActionAutoLoadsStamp:
    @pytest.mark.asyncio
    async def test_stamped_deny_without_manual_inject(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.xhs_risk_gate.check_publish_allowed", lambda **_kwargs: None
        )
        graph = _graph_with_values(
            {
                "evaluation_result": {
                    "publish_eligibility": {
                        "allowed": False,
                        "blocking_failures": ["commercial_disclosure"],
                    }
                },
                "session_id": "s1",
            }
        )
        advisor, decision_id = await _advisor_with_decision(
            policy_context_loader=thread_policy_context_loader(graph)
        )
        with pytest.raises(ActionPolicyDeniedError) as excinfo:
            await advisor.plan_action(
                _request(decision_id=decision_id, idempotency_key="auto-stamp-deny")
            )
        assert excinfo.value.policy_id is PolicyId.PUBLISH_ELIGIBILITY_DENIED
        assert "commercial_disclosure" in excinfo.value.reason
        assert await advisor.list_actions("account-a") == []

    @pytest.mark.asyncio
    async def test_missing_stamp_allows_plan(self, monkeypatch):
        monkeypatch.delenv("AUTO_APPROVE_LOW_RISK", raising=False)
        monkeypatch.setattr(
            "backend.services.xhs_risk_gate.check_publish_allowed", lambda **_kwargs: None
        )
        graph = _graph_with_values({"niche": "生活方式", "auto_publish": False, "session_id": "s1"})
        advisor, decision_id = await _advisor_with_decision(
            policy_context_loader=thread_policy_context_loader(graph)
        )
        intent = await advisor.plan_action(
            _request(decision_id=decision_id, idempotency_key="auto-stamp-missing")
        )
        assert intent.action_id
        assert len(await advisor.list_actions("account-a")) == 1

    @pytest.mark.asyncio
    async def test_load_failure_denies_with_stable_policy_id(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.xhs_risk_gate.check_publish_allowed", lambda **_kwargs: None
        )
        advisor, decision_id = await _advisor_with_decision(
            policy_context_loader=thread_policy_context_loader(None)
        )
        with pytest.raises(ActionPolicyDeniedError) as excinfo:
            await advisor.plan_action(
                _request(decision_id=decision_id, idempotency_key="auto-stamp-unavailable")
            )
        assert excinfo.value.policy_id is PolicyId.ELIGIBILITY_CONTEXT_UNAVAILABLE
        assert await advisor.list_actions("account-a") == []

    @pytest.mark.asyncio
    async def test_explicit_policy_context_overrides_loader(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.xhs_risk_gate.check_publish_allowed", lambda **_kwargs: None
        )
        # Loader would deny via stamped allowed=False; explicit empty context wins.
        graph = _graph_with_values(
            {
                "evaluation_result": {
                    "publish_eligibility": {
                        "allowed": False,
                        "blocking_failures": ["lexicon"],
                    }
                },
                "session_id": "s1",
            }
        )
        loader = thread_policy_context_loader(graph)
        advisor, decision_id = await _advisor_with_decision(policy_context_loader=loader)
        intent = await advisor.plan_action(
            _request(decision_id=decision_id, idempotency_key="override-stamp"),
            policy_context=ActionPolicyContext(),
        )
        assert intent.action_id
        # Loader must not have been consulted when context is explicit.
        graph.aget_state.assert_not_called()
