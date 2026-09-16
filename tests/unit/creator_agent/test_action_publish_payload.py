"""P2a-S1: the publish payload on the Action protocol.

两件事被钉住：

1. **形状**：publish intent 携带 ``artifact_ref`` + ``content_hash`` + ``thread_id``、
   不接受 candidate IDs；其它能力**拒绝** publish 载荷（而不是静默忽略）。
2. **键级三态**：publish 两个键只在调用方**真写过**时才出现在 ``model_dump`` 里 ——
   ``db/creator_agent._dumps`` 走的是 ``model_dump(mode="json")``（无 ``exclude_none``），
   所以普通 ``None`` 默认值会给**每个非 publish intent** 的落库 payload 加一个
   ``"artifact_ref": null``，那是与发布无关的能力的形状变更。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.api.errors import CreatorActionCapabilityNotWiredError, ErrorCode
from backend.creator_agent import (
    ActionCapability,
    ActionIntent,
    ActionIntentRequest,
    ActionResolution,
    ActionResolutionDisposition,
    CreatorAdvisor,
    CreatorModelDefinition,
    DecisionCandidate,
    DecisionPolicy,
    DecisionRequest,
    Evidence,
    EvidenceSource,
)
from backend.creator_agent.repository import ActionPublishContentUnavailableError
from backend.db import creator_agent as creator_agent_db
from backend.services.xhs_credentials import XhsCredential
from backend.state.artifacts import make_ref, parse_ref

SHA = "a" * 64
REF = "artifact://publish/p1"
THREAD = "thread-1"
NOW = "2026-01-01T00:00:00+00:00"
COOKIE = "a1=" + "0" * 20 + "; web_session=session"


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


def _decision_request() -> DecisionRequest:
    return DecisionRequest(
        account_id="account-a",
        audience_id="audience-a",
        goal="选一个更耐用的方案",
        candidates=[
            DecisionCandidate(candidate_id="a", label="A", signals={"durability": 0.9}),
            DecisionCandidate(candidate_id="b", label="B", signals={"durability": 0.2}),
        ],
    )


async def _advisor_with_decision() -> tuple[CreatorAdvisor, str]:
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)
    # P2a-S5a: publishing needs an account that holds a credential, so the
    # fixture states one (see test_action_publish_execution for the cookie).
    advisor = CreatorAdvisor(repo, credentials=_credentialed)
    decision = await advisor.decide(_decision_request())
    return advisor, decision.decision_id


async def _credentialed(account_id: str) -> XhsCredential:
    return XhsCredential(account_id=account_id, cookie=COOKIE, source="account")


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


def _intent(**overrides) -> ActionIntent:
    base: dict = {
        "action_id": "action-1",
        "account_id": "account-a",
        "creator_id": "creator-a",
        "audience_id": "audience-a",
        "decision_id": "decision-1",
        "action_kind": ActionCapability.COMPARE_OPTIONS,
        "candidate_ids": ["a", "b"],
        "idempotency_key": "compare-1",
        "created_at": NOW,
        "updated_at": NOW,
    }
    base.update(overrides)
    return ActionIntent(**base)


class TestPublishPayloadShape:
    def test_publish_is_a_capability(self):
        assert ActionCapability.PUBLISH == "publish"

    def test_a_well_formed_publish_request_is_accepted(self):
        request = _request()
        assert request.artifact_ref == REF
        assert request.content_hash == SHA
        assert request.thread_id == THREAD
        assert request.candidate_ids == []

    def test_a_publish_request_must_say_which_thread_its_artifact_lives_in(self):
        """P2a-S3: an artifact ref is thread-scoped, so an intent that omits the
        thread cannot resolve its own payload -- refused at the creation
        boundary rather than discovered at execute time."""
        with pytest.raises(ValidationError) as excinfo:
            _request(thread_id=None)
        assert "publish requires thread_id" in str(excinfo.value)

    @pytest.mark.parametrize(
        ("overrides", "reason"),
        [
            ({"artifact_ref": None}, "requires artifact_ref"),
            ({"content_hash": None}, "requires content_hash"),
            ({"artifact_ref": "   "}, "requires artifact_ref"),
            ({"content_hash": "   "}, "requires content_hash"),
            ({"thread_id": "   "}, "cannot be blank"),
            ({"artifact_ref": "publish/p1"}, "artifact://<kind>/<id>"),
            ({"artifact_ref": "artifact://p1"}, "artifact://<kind>/<id>"),
            ({"artifact_ref": "artifact:///p1"}, "artifact://<kind>/<id>"),
            ({"content_hash": "abc"}, "sha256 hexdigest"),
            ({"content_hash": "A" * 64}, "sha256 hexdigest"),
            ({"content_hash": "z" * 64}, "sha256 hexdigest"),
            ({"candidate_ids": ["a"]}, "does not accept candidate IDs"),
        ],
    )
    def test_a_malformed_publish_request_is_refused(self, overrides, reason):
        with pytest.raises(ValidationError) as excinfo:
            _request(**overrides)
        assert reason in str(excinfo.value)

    @pytest.mark.parametrize(
        "kind",
        [
            ActionCapability.COMPARE_OPTIONS,
            ActionCapability.SAVE_SHORTLIST,
            ActionCapability.REQUEST_MORE_EVIDENCE,
        ],
    )
    def test_a_non_publish_capability_refuses_a_publish_payload(self, kind):
        """Mismatched combinations are refused, not silently ignored."""
        with pytest.raises(ValidationError) as excinfo:
            _request(
                action_kind=kind,
                candidate_ids=[] if kind is not ActionCapability.COMPARE_OPTIONS else ["a", "b"],
            )
        assert "does not accept a publish payload" in str(excinfo.value)

    def test_the_intent_model_enforces_the_same_shape(self):
        with pytest.raises(ValidationError) as excinfo:
            _intent(action_kind=ActionCapability.PUBLISH, candidate_ids=[])
        assert "publish requires artifact_ref" in str(excinfo.value)


class TestTheLocalRefRuleAgreesWithTheStateLayer:
    """``_ARTIFACT_REF_PREFIX`` is a local copy of the state layer's constant.

    The domain-models layer deliberately does not import ``backend.state.artifacts``
    (it pulls ``langgraph.store.base`` in at module level), so the agreement is
    *proven* here rather than assumed.
    """

    def test_a_ref_built_by_the_state_layer_passes_validation(self):
        artifact = make_ref("publish", "p1", {"title": "hello"})
        assert parse_ref(artifact["ref"]) == ("publish", "p1")

        request = _request(artifact_ref=artifact["ref"], content_hash=artifact["content_hash"])
        assert request.artifact_ref == artifact["ref"]

    @pytest.mark.parametrize("bad", ["artifact:/publish/p1", "publish://p1", "artifact://p1"])
    def test_refs_the_state_layer_rejects_are_rejected_here_too(self, bad):
        assert parse_ref(bad) is None
        with pytest.raises(ValidationError):
            _request(artifact_ref=bad)

    def test_a_ref_the_state_layer_accepts_but_we_reject_would_be_a_drift(self):
        """Guard the guard: a well-formed ref must not be refused by the local rule."""
        artifact = make_ref("", "x", {"a": 1})
        # ``artifact://`` + "" + "/" + "x" has an empty kind → both sides reject it.
        assert parse_ref(artifact["ref"]) is None
        with pytest.raises(ValidationError):
            _request(artifact_ref=artifact["ref"])


class TestKeyLevelThreeState:
    def test_a_non_publish_intent_does_not_gain_the_publish_keys(self):
        dumped = _intent().model_dump(mode="json")
        assert "artifact_ref" not in dumped
        assert "content_hash" not in dumped
        assert "thread_id" not in dumped

    def test_a_non_publish_intent_payload_is_still_byte_identical(self):
        """The stored payload is what ``db/creator_agent._dumps`` produces."""
        payload = creator_agent_db._dumps(_intent())
        assert "artifact_ref" not in payload
        assert "content_hash" not in payload
        assert "thread_id" not in payload
        assert '"resolved_at":null' in payload  # an existing null default is untouched

    def test_a_publish_intent_carries_all_three_keys(self):
        dumped = _intent(
            action_kind=ActionCapability.PUBLISH,
            candidate_ids=[],
            artifact_ref=REF,
            content_hash=SHA,
            thread_id=THREAD,
        ).model_dump(mode="json")
        assert dumped["artifact_ref"] == REF
        assert dumped["content_hash"] == SHA
        assert dumped["thread_id"] == THREAD

    def test_a_stored_publish_row_written_before_s3_is_still_readable(self):
        """The one deliberate asymmetry: ``thread_id`` is required to *create* a
        publish intent but optional on the stored row.

        Rows written before P2a-S3 carry no thread, and turning every read of
        them into a 500 would be a migration hazard rather than a safety
        improvement.  The refusal lives at execute time, where it costs nothing
        (see ``test_a_publish_intent_without_a_thread_is_refused_before_any_side_effect``).
        """
        legacy = _intent(
            action_kind=ActionCapability.PUBLISH,
            candidate_ids=[],
            artifact_ref=REF,
            content_hash=SHA,
        )
        assert legacy.thread_id is None
        assert "thread_id" not in legacy.model_dump(mode="json")

    def test_an_explicitly_set_none_is_still_honoured(self):
        """Three-state: unset ≠ explicitly None.  Only the *unset* case is dropped."""
        dumped = _intent(artifact_ref=None).model_dump(mode="json")
        assert "artifact_ref" in dumped
        assert dumped["artifact_ref"] is None


class TestPlanAndExecutePublish:
    @pytest.mark.asyncio
    async def test_plan_action_persists_a_publish_intent_with_its_payload(self):
        advisor, decision_id = await _advisor_with_decision()

        intent = await advisor.plan_action(
            _request(decision_id=decision_id, idempotency_key="publish-1")
        )

        assert intent.action_kind is ActionCapability.PUBLISH
        assert intent.candidate_ids == []
        assert intent.artifact_ref == REF
        assert intent.content_hash == SHA
        assert intent.thread_id == THREAD
        assert intent.status.value == "pending_confirmation"

        stored = await advisor._repository.get_action("account-a", intent.action_id)  # noqa: SLF001
        assert stored is not None
        assert stored.artifact_ref == REF
        assert stored.content_hash == SHA
        assert stored.thread_id == THREAD

    @pytest.mark.asyncio
    async def test_an_unconfirmed_publish_intent_cannot_execute(self):
        advisor, decision_id = await _advisor_with_decision()
        intent = await advisor.plan_action(
            _request(decision_id=decision_id, idempotency_key="publish-2")
        )

        with pytest.raises(Exception) as excinfo:
            await advisor.execute_action("account-a", intent.action_id)
        assert excinfo.value.__class__.__name__ == "ActionExecutionNotAllowedError"

    @pytest.mark.asyncio
    async def test_a_confirmed_publish_intent_without_content_is_refused_without_a_receipt(self):
        """P2a-S3 wires the executor; what stays loud is an unusable payload.

        The advisor here is built without an artifact store, so the intent's ref
        resolves to nothing.  The one thing that must never happen is a receipt
        for a publish that never left the process, so the refusal is asserted
        *and* the absence of a receipt is asserted with it.
        """
        advisor, decision_id = await _advisor_with_decision()
        intent = await advisor.plan_action(
            _request(decision_id=decision_id, idempotency_key="publish-3")
        )
        await advisor.resolve_action(
            "account-a",
            intent.action_id,
            ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
        )

        with pytest.raises(ActionPublishContentUnavailableError) as excinfo:
            await advisor.execute_action("account-a", intent.action_id)

        assert excinfo.value.action_id == intent.action_id
        assert await advisor.get_action_execution("account-a", intent.action_id) is None


class TestTheApiSurfaceForANotWiredCapability:
    def test_the_api_error_maps_to_501_with_its_own_code(self):
        error = CreatorActionCapabilityNotWiredError("action-1", "publish")
        assert error.status_code == 501
        assert error.code is ErrorCode.CREATOR_ACTION_CAPABILITY_NOT_WIRED
        assert error.details == {"action_id": "action-1", "action_kind": "publish"}
