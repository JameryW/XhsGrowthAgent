"""P2a-S2: the deterministic policy gate between planning and confirmation.

What is pinned here:

1. **The rule table** -- a pure function, exercised directly.
2. **Fail-closed at the boundary** -- a risk gate that raises must become a
   *denial*, never an allow.  This is the one direction of error that costs a
   real publish.
3. **Placement** -- a denial must leave **no** Action Intent behind, because an
   intent nobody can ever confirm is a dead record; and the three
   non-transactional capabilities must be untouched by a policy that has nothing
   to say about them.
4. **A pre-existing gap, pinned rather than hidden** -- see
   ``test_the_intent_time_check_reads_a_key_the_runtime_never_writes``.
"""

from __future__ import annotations

import pytest

from backend.api.errors import CreatorActionPolicyDeniedError, ErrorCode
from backend.creator_agent import (
    ActionCapability,
    ActionIntentRequest,
    ActionPolicyDeniedError,
    ActionPolicySnapshot,
    CreatorAdvisor,
    CreatorModelDefinition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    Evidence,
    EvidenceSource,
    PolicyId,
    PolicyVerdict,
    RiskVerdict,
    build_action_policy_snapshot,
    evaluate_action_policy,
)
from backend.db import creator_agent as creator_agent_db
from backend.services.xhs_risk_gate import (
    GateBlock,
    check_publish_allowed,
    note_publish,
    reset_gates_for_tests,
)

SHA = "a" * 64
REF = "artifact://publish/p1"
THREAD = "thread-1"
NON_PUBLISH = (
    ActionCapability.COMPARE_OPTIONS,
    ActionCapability.SAVE_SHORTLIST,
    ActionCapability.REQUEST_MORE_EVIDENCE,
)


@pytest.fixture(autouse=True)
def _reset():
    creator_agent_db._reset_memory_store()
    reset_gates_for_tests()
    yield
    creator_agent_db._reset_memory_store()
    reset_gates_for_tests()


def _block(retry_after: int = 42) -> GateBlock:
    return GateBlock(
        reason="publish_cooldown",
        risk_code="publish_cooldown",
        message="发布冷却中。",
        retry_after_seconds=retry_after,
    )


def _request(**overrides) -> ActionIntentRequest:
    base: dict = {
        "account_id": "account-a",
        "decision_id": "decision-1",
        "action_kind": ActionCapability.PUBLISH,
        "idempotency_key": "publish-1",
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


async def _advisor_with_decision() -> tuple[CreatorAdvisor, str]:
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo)
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


class TestTheRuleTable:
    def test_a_clear_gate_allows_a_publish_intent(self):
        verdict = evaluate_action_policy(
            ActionPolicySnapshot(capability=ActionCapability.PUBLISH, account_id="account-a")
        )
        assert verdict.allowed is True
        assert verdict.policy_id is PolicyId.ALLOWED

    def test_a_risk_block_denies_and_carries_the_retry_hint(self):
        verdict = evaluate_action_policy(
            ActionPolicySnapshot(
                capability=ActionCapability.PUBLISH,
                account_id="account-a",
                risk=RiskVerdict(
                    policy_id=PolicyId.RISK_COOLDOWN,
                    reason="发布冷却中。",
                    retry_after_seconds=42,
                ),
            )
        )
        assert verdict.allowed is False
        assert verdict.policy_id is PolicyId.RISK_COOLDOWN
        assert verdict.retry_after_seconds == 42
        assert verdict.reason == "发布冷却中。"

    @pytest.mark.parametrize("kind", NON_PUBLISH)
    def test_a_non_publish_capability_is_out_of_this_policy_scope(self, kind):
        """The three non-transactional capabilities keep their behaviour."""
        verdict = evaluate_action_policy(
            ActionPolicySnapshot(capability=kind, account_id="account-a")
        )
        assert verdict.allowed is True
        assert verdict.policy_id is PolicyId.NOT_APPLICABLE

    def test_a_non_publish_capability_is_allowed_even_with_a_blocking_risk_verdict(self):
        """``NOT_APPLICABLE`` is decided before the risk verdict is even read."""
        verdict = evaluate_action_policy(
            ActionPolicySnapshot(
                capability=ActionCapability.SAVE_SHORTLIST,
                account_id="account-a",
                risk=RiskVerdict(
                    policy_id=PolicyId.RISK_COOLDOWN, reason="冷却中。", retry_after_seconds=9
                ),
            )
        )
        assert verdict.allowed is True
        assert verdict.policy_id is PolicyId.NOT_APPLICABLE

    def test_a_missing_account_is_a_denial_not_an_allow(self):
        """Fail-closed: no account means nothing to evaluate, which is not a yes."""
        verdict = evaluate_action_policy(
            ActionPolicySnapshot(capability=ActionCapability.PUBLISH, account_id="   ")
        )
        assert verdict.allowed is False
        assert verdict.policy_id is PolicyId.ACCOUNT_MISSING

    def test_an_unreadable_gate_is_expressed_as_a_verdict_not_as_none(self):
        """``risk=None`` already means "clear" -- an unreadable gate must not alias it."""
        verdict = evaluate_action_policy(
            ActionPolicySnapshot(
                capability=ActionCapability.PUBLISH,
                account_id="account-a",
                risk=RiskVerdict(policy_id=PolicyId.RISK_UNAVAILABLE, reason="gate blew up"),
            )
        )
        assert verdict.allowed is False
        assert verdict.policy_id is PolicyId.RISK_UNAVAILABLE
        assert verdict.retry_after_seconds is None


class TestTheGateBoundaryFailsClosed:
    def test_a_raising_gate_becomes_a_denial_not_an_allow(self):
        def boom(_account_id: str) -> RiskVerdict | None:
            raise RuntimeError("gate down")

        snapshot = build_action_policy_snapshot(_request(), cooldown_checker=boom)
        assert snapshot.risk is not None
        assert snapshot.risk.policy_id is PolicyId.RISK_UNAVAILABLE
        assert "RuntimeError" in snapshot.risk.reason

        verdict = evaluate_action_policy(snapshot)
        assert verdict.allowed is False
        assert verdict.policy_id is PolicyId.RISK_UNAVAILABLE

    def test_a_blocking_gate_becomes_a_denial_with_its_retry_hint(self):
        snapshot = build_action_policy_snapshot(
            _request(),
            cooldown_checker=lambda _account_id: RiskVerdict(
                policy_id=PolicyId.RISK_COOLDOWN, reason="冷却中。", retry_after_seconds=7
            ),
        )
        verdict = evaluate_action_policy(snapshot)
        assert verdict.allowed is False
        assert verdict.retry_after_seconds == 7

    def test_the_gate_is_not_consulted_for_non_publish_capabilities(self):
        calls: list[str] = []

        def spy(account_id: str) -> RiskVerdict | None:
            calls.append(account_id)
            return None

        snapshot = build_action_policy_snapshot(
            _request(
                action_kind=ActionCapability.SAVE_SHORTLIST,
                artifact_ref=None,
                content_hash=None,
                thread_id=None,
                candidate_ids=["a"],
            ),
            cooldown_checker=spy,
        )
        assert calls == []
        assert snapshot.risk is None

    def test_the_default_checker_is_the_real_gate(self, monkeypatch):
        """The injected seam must not be the *only* thing that works."""
        monkeypatch.setenv("XHS_PUBLISH_COOLDOWN_SECONDS", "60")
        note_publish(account_id="account-a")

        snapshot = build_action_policy_snapshot(_request())
        assert snapshot.risk is not None
        assert snapshot.risk.policy_id is PolicyId.RISK_COOLDOWN
        assert snapshot.risk.retry_after_seconds > 0


class TestPlanActionPlacement:
    @pytest.mark.asyncio
    async def test_a_denied_publish_never_becomes_a_durable_intent(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.xhs_risk_gate.check_publish_allowed",
            lambda **_kwargs: _block(42),
        )
        advisor, decision_id = await _advisor_with_decision()

        with pytest.raises(ActionPolicyDeniedError) as excinfo:
            await advisor.plan_action(
                _request(decision_id=decision_id, idempotency_key="publish-denied")
            )

        assert excinfo.value.policy_id is PolicyId.RISK_COOLDOWN
        assert excinfo.value.retry_after_seconds == 42
        assert excinfo.value.account_id == "account-a"
        # The whole point of the placement: nothing to confirm, nothing to leak.
        assert await advisor.list_actions("account-a") == []

    @pytest.mark.asyncio
    async def test_a_gate_failure_denies_rather_than_plans(self, monkeypatch):
        def boom(**_kwargs):
            raise RuntimeError("gate down")

        monkeypatch.setattr("backend.services.xhs_risk_gate.check_publish_allowed", boom)
        advisor, decision_id = await _advisor_with_decision()

        with pytest.raises(ActionPolicyDeniedError) as excinfo:
            await advisor.plan_action(
                _request(decision_id=decision_id, idempotency_key="publish-gate-down")
            )
        assert excinfo.value.policy_id is PolicyId.RISK_UNAVAILABLE
        assert await advisor.list_actions("account-a") == []

    @pytest.mark.asyncio
    async def test_a_clean_gate_still_plans_the_intent(self, monkeypatch):
        monkeypatch.setattr(
            "backend.services.xhs_risk_gate.check_publish_allowed", lambda **_kwargs: None
        )
        advisor, decision_id = await _advisor_with_decision()

        intent = await advisor.plan_action(
            _request(decision_id=decision_id, idempotency_key="publish-ok")
        )
        assert intent.artifact_ref == REF
        assert len(await advisor.list_actions("account-a")) == 1

    @pytest.mark.asyncio
    async def test_a_non_publish_action_never_touches_the_gate(self, monkeypatch):
        """Red line: the policy must not change non-publish behaviour at all."""

        def boom(**_kwargs):
            raise AssertionError("the gate must not be consulted for non-publish actions")

        monkeypatch.setattr("backend.services.xhs_risk_gate.check_publish_allowed", boom)
        advisor, decision_id = await _advisor_with_decision()

        intent = await advisor.plan_action(
            _request(
                decision_id=decision_id,
                idempotency_key="compare-1",
                action_kind=ActionCapability.COMPARE_OPTIONS,
                artifact_ref=None,
                content_hash=None,
                thread_id=None,
                candidate_ids=["a", "b"],
            )
        )
        assert intent.action_kind is ActionCapability.COMPARE_OPTIONS
        assert intent.candidate_ids == ["a", "b"]


class TestTheAccountKeyedCooldownIsReachableNow:
    """P2a-S2 pinned "the account bucket has no production writer"; P2a-S3 gave
    it one -- the executor's publish hands ``account_id`` down through the tool
    into ``services.xhs_publisher`` -- so what is worth pinning changed shape.

    What remains true, and is what this now pins, is that the two keys are
    **separate buckets**: a record under one does not block a check under the
    other.  The writer half belongs to the layers that own it and is proven
    there (``tests/unit/creator_agent/test_action_publish_execution.py``,
    ``tests/unit/tools/test_xhs_publisher.py``); restating it here would be a
    second, weaker copy of the same fact.
    """

    def test_the_endpoint_and_account_buckets_do_not_share_a_cooldown(self, monkeypatch):
        monkeypatch.setenv("XHS_PUBLISH_COOLDOWN_SECONDS", "60")

        # A record written the way a caller without an account id writes it.
        note_publish(cdp_endpoint="http://127.0.0.1:9222")
        assert check_publish_allowed(account_id="acc-1") is None
        assert check_publish_allowed(cdp_endpoint="http://127.0.0.1:9222") is not None

        # A caller that knows the account id lands in its own bucket.
        note_publish(account_id="acc-1")
        assert check_publish_allowed(account_id="acc-1") is not None


class TestTheApiSurfaceForADeniedAction:
    def test_the_api_error_maps_to_403_with_its_own_code_and_retry_hint(self):
        error = CreatorActionPolicyDeniedError(
            policy_id=PolicyId.RISK_COOLDOWN.value,
            reason="发布冷却中。",
            account_id="account-a",
            retry_after_seconds=42,
        )
        assert error.status_code == 403
        assert error.code is ErrorCode.CREATOR_ACTION_POLICY_DENIED
        assert error.details == {
            "policy_id": "policy.action.risk_cooldown",
            "account_id": "account-a",
            "retry_after_seconds": 42,
        }

    def test_a_denial_without_a_retry_hint_omits_the_key(self):
        error = CreatorActionPolicyDeniedError(
            policy_id=PolicyId.RISK_UNAVAILABLE.value,
            reason="gate down",
            account_id="account-a",
        )
        assert error.status_code == 403
        assert "retry_after_seconds" not in error.details

    def test_the_verdict_type_is_the_same_one_the_engine_returns(self):
        """Guard the guard: the API error must not invent its own verdict shape."""
        verdict: PolicyVerdict = evaluate_action_policy(
            ActionPolicySnapshot(capability=ActionCapability.PUBLISH, account_id="account-a")
        )
        assert isinstance(verdict.policy_id, PolicyId)
