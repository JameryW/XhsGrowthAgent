"""P3b (票 5bf): the executor runs a mainline-origin publish intent.

The mainline identity (票 5bc) has no creator decision: its approval identity is
the ``decision_id`` the review endpoint wrote.  These tests pin that the *same*
executor runs such an intent exactly once and produces a receipt that says so —
mainline origin, empty creator half, no model revision — instead of inventing a
``DecisionRecord``.  Creator-origin behaviour stays covered by the neighbouring
execution tests.
"""

from __future__ import annotations

from typing import Any

import pytest
from langgraph.store.memory import InMemoryStore
from pydantic import ValidationError

from backend.creator_agent import (
    ActionCapability,
    ActionExecution,
    ActionExecutionStatus,
    ActionIntent,
    ActionOrigin,
    ActionStatus,
    CreatorAdvisor,
    CreatorModelDefinition,
    DecisionPolicy,
    Evidence,
    EvidenceSource,
    PublishOutcome,
    PublishStatus,
)
from backend.creator_agent.repository import (
    ActionCapabilityNotWiredError,
    ActionExecutionNotAllowedError,
)
from backend.db import creator_agent as creator_agent_db
from backend.services.xhs_credentials import XhsCredential
from backend.services.xhs_risk_gate import reset_gates_for_tests
from backend.state.artifacts import put_artifact

ACCOUNT = "account-a"
THREAD = "thread-mainline-1"
NOW = "2026-01-01T00:00:00+00:00"
BODY: dict[str, Any] = {
    "title": "主链批准的一条笔记",
    "body": "正文内容",
    "hashtags": ["主链"],
    "image_paths": ["/tmp/mainline.png"],
}
COOKIE = "a1=" + "0" * 20 + "; web_session=session"


async def _credentialed(account_id: str) -> XhsCredential:
    return XhsCredential(account_id=account_id, cookie=COOKIE, source="account")


@pytest.fixture(autouse=True)
def _reset():
    creator_agent_db._reset_memory_store()
    reset_gates_for_tests()
    yield
    creator_agent_db._reset_memory_store()
    reset_gates_for_tests()


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


class _Recorder:
    """A dispatcher that records what it was asked to publish."""

    def __init__(self, outcome: PublishOutcome | None = None) -> None:
        self.outcome = outcome or PublishOutcome(
            status=PublishStatus.PUBLISHED, note_id="note-mainline"
        )
        self.requests: list[Any] = []

    async def __call__(self, request: Any) -> PublishOutcome:
        self.requests.append(request)
        return self.outcome


async def _advisor(store: Any, publish: Any) -> tuple[CreatorAdvisor, Any]:
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model(ACCOUNT, _definition(), expected_revision=0)
    advisor = CreatorAdvisor(
        repo, artifact_store=store, publish=publish, credentials=_credentialed
    )
    return advisor, repo


async def _stored(store: Any, body: Any) -> tuple[str, str]:
    ref = await put_artifact(store, THREAD, "publish_payload", body)
    assert ref is not None
    return ref["ref"], ref["content_hash"]


def _mainline_intent(
    *,
    artifact_ref: str | None,
    content_hash: str | None,
    action_kind: ActionCapability = ActionCapability.PUBLISH,
    status: ActionStatus = ActionStatus.CONFIRMED,
    thread_id: str | None = THREAD,
) -> ActionIntent:
    return ActionIntent(
        action_id="mainline-action-1",
        account_id=ACCOUNT,
        origin=ActionOrigin.MAINLINE,
        creator_id="",
        audience_id="",
        decision_id="mainline:approval-1",
        action_kind=action_kind,
        candidate_ids=[],
        idempotency_key="mainline-publish-1",
        status=status,
        created_at=NOW,
        updated_at=NOW,
        artifact_ref=artifact_ref,
        content_hash=content_hash,
        thread_id=thread_id,
    )


class TestTheExecutorRunsAMainlineIntent:
    async def test_it_executes_once_and_records_the_mainline_origin(self):
        store = InMemoryStore()
        recorder = _Recorder()
        ref, digest = await _stored(store, BODY)
        advisor, repo = await _advisor(store, recorder)
        intent = _mainline_intent(artifact_ref=ref, content_hash=digest)
        await repo.create_action(intent)

        receipt = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert receipt.origin is ActionOrigin.MAINLINE
        assert receipt.decision_id == "mainline:approval-1"
        assert receipt.creator_id == ""
        assert receipt.audience_id == ""
        assert receipt.model_revision is None
        assert receipt.status is ActionExecutionStatus.SUCCEEDED
        assert receipt.result["status"] == "published"
        assert receipt.result["note_id"] == "note-mainline"
        assert len(recorder.requests) == 1
        request = recorder.requests[0]
        assert request.account_id == ACCOUNT
        assert request.idempotency_key == "mainline-publish-1"
        assert request.artifact_ref == ref
        assert request.content_hash == digest
        assert request.content.title == "主链批准的一条笔记"

    async def test_executing_twice_returns_the_same_receipt_and_dispatches_once(self):
        store = InMemoryStore()
        recorder = _Recorder()
        ref, digest = await _stored(store, BODY)
        advisor, repo = await _advisor(store, recorder)
        intent = _mainline_intent(artifact_ref=ref, content_hash=digest)
        await repo.create_action(intent)

        first = await advisor.execute_action(ACCOUNT, intent.action_id)
        again = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert again.execution_id == first.execution_id
        assert len(recorder.requests) == 1

    async def test_a_failed_publish_is_a_failed_receipt(self):
        store = InMemoryStore()
        recorder = _Recorder(
            PublishOutcome(status=PublishStatus.FAILED, error="platform said no")
        )
        ref, digest = await _stored(store, BODY)
        advisor, repo = await _advisor(store, recorder)
        intent = _mainline_intent(artifact_ref=ref, content_hash=digest)
        await repo.create_action(intent)

        receipt = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert receipt.status is ActionExecutionStatus.FAILED
        assert receipt.result["status"] == "failed"
        assert receipt.result["error"] == "platform said no"


class TestWhatTheMainlineExecutorRefuses:
    async def test_a_non_publish_mainline_capability_is_refused_without_a_receipt(self):
        store = InMemoryStore()
        recorder = _Recorder()
        advisor, repo = await _advisor(store, recorder)
        intent = _mainline_intent(
            artifact_ref=None,
            content_hash=None,
            action_kind=ActionCapability.COMPARE_OPTIONS,
            thread_id=None,
        )
        await repo.create_action(intent)

        with pytest.raises(ActionCapabilityNotWiredError):
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert recorder.requests == []
        assert await repo.get_action_execution(ACCOUNT, intent.action_id) is None

    async def test_a_pending_mainline_intent_is_refused(self):
        store = InMemoryStore()
        recorder = _Recorder()
        advisor, repo = await _advisor(store, recorder)
        intent = _mainline_intent(
            artifact_ref="artifact://publish_content/p1",
            content_hash="a" * 64,
            status=ActionStatus.PENDING_CONFIRMATION,
        )
        await repo.create_action(intent)

        with pytest.raises(ActionExecutionNotAllowedError):
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert recorder.requests == []


class TestTheReceiptModelRefusesAMixedIdentity:
    def _receipt(self, **overrides: Any) -> ActionExecution:
        base: dict[str, Any] = {
            "execution_id": "exec-1",
            "account_id": ACCOUNT,
            "action_id": "mainline-action-1",
            "decision_id": "mainline:approval-1",
            "origin": ActionOrigin.MAINLINE,
            "creator_id": "",
            "audience_id": "",
            "action_kind": ActionCapability.PUBLISH,
            "model_revision": None,
            "executor_version": "1",
            "created_at": NOW,
            "updated_at": NOW,
        }
        base.update(overrides)
        return ActionExecution(**base)

    def test_a_mainline_receipt_carrying_creator_identity_is_refused(self):
        with pytest.raises(ValidationError, match="must not carry"):
            self._receipt(creator_id="creator-a")
        with pytest.raises(ValidationError, match="must not carry"):
            self._receipt(model_revision=3)

    def test_a_creator_receipt_without_its_identity_is_refused(self):
        with pytest.raises(ValidationError, match="creator-origin executions require"):
            self._receipt(
                origin=ActionOrigin.CREATOR,
                creator_id="",
                audience_id="",
                model_revision=None,
            )
