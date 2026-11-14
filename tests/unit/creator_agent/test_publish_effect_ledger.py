"""P4 row-5 closure (票 5bi): the executor's publish attempt is ledger-guarded.

Before this slice the control-plane executor relied on its ``ActionExecution``
receipt, which is written *after* the platform call — a crash in between looked
like "never attempted", and a retry could post twice.  These tests pin the fix:

* the ledger record exists as IN_FLIGHT **before** the dispatcher is called;
* it settles to CONFIRMED / FAILED / UNKNOWN from the outcome (a raised dispatch
  is UNKNOWN, never FAILED — FAILED would invite the retry the guard stops);
* a prior blocking state refuses as a typed error with no second dispatch.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from langgraph.store.memory import InMemoryStore
from pydantic import ValidationError

from backend.creator_agent import (
    ActionCapability,
    ActionExecutionStatus,
    ActionIntent,
    ActionIntentRequest,
    ActionOrigin,
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
    PublishOutcome,
    PublishStatus,
)
from backend.creator_agent.execution import (
    PUBLISH_EFFECT_NAMESPACE,
    publish_effect_id,
)
from backend.creator_agent.repository import ActionPublishAlreadyAttemptedError
from backend.db import creator_agent as creator_agent_db
from backend.services.xhs_credentials import XhsCredential
from backend.services.xhs_risk_gate import reset_gates_for_tests
from backend.state.artifacts import put_artifact
from backend.state.effects import EffectLedger, EffectStatus

ACCOUNT = "account-a"
THREAD = "thread-ledger-1"
KEY = "publish-ledger-1"
BODY: dict[str, Any] = {
    "title": "账本保护的笔记",
    "body": "正文内容",
    "hashtags": ["账本"],
    "image_paths": ["/tmp/ledger.png"],
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


def _decision_request() -> DecisionRequest:
    return DecisionRequest(
        account_id=ACCOUNT,
        audience_id="audience-a",
        goal="选一个更耐用的方案",
        candidates=[
            DecisionCandidate(candidate_id="a", label="A", signals={"durability": 0.9}),
            DecisionCandidate(candidate_id="b", label="B", signals={"durability": 0.4}),
        ],
    )


class _Recorder:
    """A dispatcher that records what it was asked to publish."""

    def __init__(self, outcome: PublishOutcome | None = None) -> None:
        self.outcome = outcome or PublishOutcome(
            status=PublishStatus.PUBLISHED, note_id="note-ledger"
        )
        self.requests: list[Any] = []

    async def __call__(self, request: Any) -> PublishOutcome:
        self.requests.append(request)
        return self.outcome


async def _advisor(store: Any, publish: Any) -> tuple[CreatorAdvisor, str]:
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model(ACCOUNT, _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo, artifact_store=store, publish=publish, credentials=_credentialed)
    decision = await advisor.decide(_decision_request())
    return advisor, decision.decision_id


async def _stored(store: Any, body: Any) -> tuple[str, str]:
    ref = await put_artifact(store, THREAD, "publish_payload", body)
    assert ref is not None
    return ref["ref"], ref["content_hash"]


async def _confirmed_publish(
    advisor: CreatorAdvisor,
    decision_id: str,
    *,
    artifact_ref: str,
    content_hash: str,
) -> Any:
    intent = await advisor.plan_action(
        ActionIntentRequest(
            account_id=ACCOUNT,
            decision_id=decision_id,
            action_kind=ActionCapability.PUBLISH,
            idempotency_key=KEY,
            artifact_ref=artifact_ref,
            content_hash=content_hash,
            thread_id=THREAD,
        )
    )
    await advisor.resolve_action(
        ACCOUNT,
        intent.action_id,
        ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
    )
    return intent


async def _ledger(store: Any) -> EffectLedger:
    return EffectLedger(store, PUBLISH_EFFECT_NAMESPACE)


async def _record(store: Any):
    return await (await _ledger(store)).get(publish_effect_id(ACCOUNT, KEY))


class TestTheLedgerWrapsTheDispatch:
    async def test_the_record_is_in_flight_before_the_platform_call(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        advisor, decision_id = await _advisor(store, _Recorder())
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )
        inside: list[EffectStatus] = []

        class _InspectingDispatcher:
            async def __call__(self, request: Any) -> PublishOutcome:
                record = await _record(store)
                assert record is not None
                inside.append(record.status)
                return PublishOutcome(status=PublishStatus.PUBLISHED, note_id="note-x")

        advisor._publish = _InspectingDispatcher()  # noqa: SLF001 - the seam under test
        await advisor.execute_action(ACCOUNT, intent.action_id)

        assert inside == [EffectStatus.IN_FLIGHT]
        record = await _record(store)
        assert record is not None and record.status is EffectStatus.CONFIRMED
        assert record.result_ref == "note-x"

    async def test_a_definite_failure_settles_failed(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        advisor, decision_id = await _advisor(
            store, _Recorder(PublishOutcome(status=PublishStatus.FAILED, error="no"))
        )
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        receipt = await advisor.execute_action(ACCOUNT, intent.action_id)

        record = await _record(store)
        assert record is not None and record.status is EffectStatus.FAILED
        assert receipt.status is ActionExecutionStatus.FAILED

    async def test_an_unknown_outcome_settles_unknown(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        advisor, decision_id = await _advisor(
            store, _Recorder(PublishOutcome(status=PublishStatus.UNKNOWN, error="lost"))
        )
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        await advisor.execute_action(ACCOUNT, intent.action_id)

        record = await _record(store)
        assert record is not None and record.status is EffectStatus.UNKNOWN

    async def test_a_raising_dispatcher_settles_unknown_and_propagates(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        advisor, decision_id = await _advisor(store, _Recorder())
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        class _Boom:
            async def __call__(self, request: Any) -> PublishOutcome:
                raise RuntimeError("gateway blew up")

        advisor._publish = _Boom()  # noqa: SLF001 - the seam under test

        with pytest.raises(RuntimeError):
            await advisor.execute_action(ACCOUNT, intent.action_id)

        record = await _record(store)
        assert record is not None and record.status is EffectStatus.UNKNOWN
        assert await advisor.get_action_execution(ACCOUNT, intent.action_id) is None


class TestAPriorAttemptIsRefusedInsteadOfDispatchedAgain:
    async def test_a_crash_window_after_submit_blocks_the_retry(self, monkeypatch):
        """The receipt is written after the call; the ledger covers that window."""
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )
        # Simulate a crash between the platform call and the receipt write.
        original = advisor._repository.create_action_execution  # noqa: SLF001
        monkeypatch.setattr(
            advisor._repository,  # noqa: SLF001
            "create_action_execution",
            AsyncMock(side_effect=RuntimeError("receipt write crashed")),
        )

        with pytest.raises(RuntimeError):
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert len(recorder.requests) == 1
        record = await _record(store)
        assert record is not None and record.status is EffectStatus.CONFIRMED

        # Retry: the receipt is still absent, but the ledger must stop a second post.
        monkeypatch.setattr(advisor._repository, "create_action_execution", original)  # noqa: SLF001
        with pytest.raises(ActionPublishAlreadyAttemptedError) as excinfo:
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert excinfo.value.prior_status == EffectStatus.CONFIRMED.value
        assert len(recorder.requests) == 1

    async def test_a_prior_unknown_effect_blocks_before_any_dispatch(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )
        ledger = await _ledger(store)
        await ledger.begin(publish_effect_id(ACCOUNT, KEY), tool_name="xhs.publish")
        await ledger.mark(publish_effect_id(ACCOUNT, KEY), EffectStatus.UNKNOWN, error="lost")

        with pytest.raises(ActionPublishAlreadyAttemptedError) as excinfo:
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert excinfo.value.prior_status == EffectStatus.UNKNOWN.value
        assert recorder.requests == []
        assert await advisor.get_action_execution(ACCOUNT, intent.action_id) is None


class TestTheEffectKeyIsAccountScoped:
    def test_two_accounts_reusing_a_key_do_not_collide(self):
        assert publish_effect_id("account-a", "k") != publish_effect_id("account-b", "k")

    def test_the_receipt_validator_still_refuses_a_mismatched_identity(self):
        from backend.creator_agent import ActionExecution, ActionOrigin

        with pytest.raises(ValidationError):
            ActionExecution(
                execution_id="e1",
                account_id=ACCOUNT,
                action_id="a1",
                decision_id="d1",
                origin=ActionOrigin.MAINLINE,
                creator_id="creator-x",
                audience_id="",
                action_kind=ActionCapability.PUBLISH,
                model_revision=None,
                executor_version="1",
                created_at="now",
                updated_at="now",
            )
        assert ActionStatus.CONFIRMED.value == "confirmed"


class TestTheOutcomeAuditFieldsAndForce:
    """票 5bn: mainline branch-B prerequisites.

    The receipt must be able to carry the platform's audit fields back to the
    workflow's ``publish_result`` mapping, and an operator-explicit ``force``
    must be able to claim a reconciled effect again — the two things the mainline
    executor wiring needs before it can replace the legacy dispatch段.
    """

    async def test_the_receipt_carries_the_platform_audit_fields(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        outcome = PublishOutcome(
            status=PublishStatus.PUBLISHED,
            note_id="note-audit",
            published_at="2026-01-01T00:00:00",
            result_known=True,
        )
        advisor, decision_id = await _advisor(store, _Recorder(outcome))
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        receipt = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert receipt.result["published_at"] == "2026-01-01T00:00:00"
        assert receipt.result["result_known"] is True
        assert receipt.result["note_id"] == "note-audit"

    async def test_a_failed_receipt_keeps_error_type_and_recovery(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        outcome = PublishOutcome(
            status=PublishStatus.FAILED,
            error="login expired",
            error_type="auth_expired",
            recovery={"action": "relogin", "hint": "扫码后重试"},
        )
        advisor, decision_id = await _advisor(store, _Recorder(outcome))
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        receipt = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert receipt.result["error_type"] == "auth_expired"
        assert receipt.result["recovery"] == {"action": "relogin", "hint": "扫码后重试"}

    async def test_force_claims_a_reconciled_unknown_effect_again(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )
        ledger = await _ledger(store)
        await ledger.begin(publish_effect_id(ACCOUNT, KEY), tool_name="xhs.publish")
        await ledger.mark(publish_effect_id(ACCOUNT, KEY), EffectStatus.UNKNOWN, error="lost")

        receipt = await advisor.execute_action(ACCOUNT, intent.action_id, force=True)

        assert len(recorder.requests) == 1
        assert receipt.status is ActionExecutionStatus.SUCCEEDED
        record = await _record(store)
        assert record is not None and record.status is EffectStatus.CONFIRMED
        assert record.attempt == 2


class TestReceiptsAreAttemptScoped:
    """票 5bq: one intent may execute more than once, so receipts are attempts.

    The mainline retries a KNOWN FAILED publish (the ledger's FAILED state is not
    blocking), and an operator force re-executes on purpose.  A single
    (account, action) receipt would turn both into "return the old receipt and
    never dispatch again" — a silent behaviour regression once the mainline entry
    switches onto this executor.
    """

    async def test_a_definite_failure_is_retryable_without_force(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        advisor, decision_id = await _advisor(
            store, _Recorder(PublishOutcome(status=PublishStatus.FAILED, error="boom"))
        )
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        first = await advisor.execute_action(ACCOUNT, intent.action_id)
        assert first.status is ActionExecutionStatus.FAILED
        assert first.attempt == 1

        retry = _Recorder(PublishOutcome(status=PublishStatus.PUBLISHED, note_id="note-2"))
        advisor._publish = retry  # noqa: SLF001 - the seam under test
        second = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert len(retry.requests) == 1
        assert second.status is ActionExecutionStatus.SUCCEEDED
        assert second.attempt == 2
        latest = await advisor.get_action_execution(ACCOUNT, intent.action_id)
        assert latest is not None and latest.attempt == 2
        exact = await advisor.get_action_execution(ACCOUNT, intent.action_id, 1)
        assert exact is not None and exact.execution_id == first.execution_id
        record = await _record(store)
        assert record is not None and record.status is EffectStatus.CONFIRMED

    async def test_a_successful_receipt_is_terminal_without_force(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        first = await advisor.execute_action(ACCOUNT, intent.action_id)
        second = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert len(recorder.requests) == 1
        assert second.execution_id == first.execution_id
        assert second.attempt == 1

    async def test_force_re_executes_after_a_successful_receipt(self):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        await advisor.execute_action(ACCOUNT, intent.action_id)
        forced = await advisor.execute_action(ACCOUNT, intent.action_id, force=True)

        assert len(recorder.requests) == 2
        assert forced.attempt == 2
        assert forced.status is ActionExecutionStatus.SUCCEEDED
        record = await _record(store)
        assert record is not None
        assert record.status is EffectStatus.CONFIRMED
        assert record.attempt == 2


class TestTheVerificationTelemetry:
    """P1-B: the control plane records *why* its publish is gated — once.

    The mainline publisher already emits one ``kind:"verification"`` entry
    before its dispatch; a creator-origin publish goes through this executor and
    used to leave the audit trail silent. A mainline-origin intent dispatched
    here would double-count the entry the publisher already wrote, so the
    executor deliberately stays quiet for that origin.
    """

    async def test_a_creator_publish_emits_one_verification_entry(self, monkeypatch):
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )
        batches: list[tuple[str, list[dict[str, Any]]]] = []

        async def _emit(thread_id: str, entries: list[dict[str, Any]]) -> int:
            batches.append((thread_id, entries))
            return len(entries)

        monkeypatch.setattr("backend.state.events.emit_events", _emit)

        await advisor.execute_action(ACCOUNT, intent.action_id)

        assert len(recorder.requests) == 1
        assert len(batches) == 1
        thread_id, entries = batches[0]
        assert thread_id == THREAD
        assert [entry["kind"] for entry in entries] == ["verification"]
        entry = entries[0]
        assert entry["action"] == "publish"
        assert entry["account_id"] == ACCOUNT
        assert entry["thread_id"] == THREAD
        assert entry["required"] is True
        assert entry["tier"] == "human"
        assert entry["reason"] == "critical_risk_floor"

    async def test_a_mainline_publish_does_not_emit_here(self, monkeypatch):
        """The publisher owns the mainline's one entry; the executor adds none."""
        store = InMemoryStore()
        ref, digest = await _stored(store, BODY)
        recorder = _Recorder()
        advisor, _ = await _advisor(store, recorder)
        intent = ActionIntent(
            action_id="mainline-verification-1",
            account_id=ACCOUNT,
            origin=ActionOrigin.MAINLINE,
            creator_id="",
            audience_id="",
            decision_id="mainline:verification-1",
            action_kind=ActionCapability.PUBLISH,
            candidate_ids=[],
            idempotency_key="mainline-publish-verification",
            status=ActionStatus.CONFIRMED,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            artifact_ref=ref,
            content_hash=digest,
            thread_id=THREAD,
        )
        await advisor._repository.create_action(intent)  # noqa: SLF001 - durable seam
        batches: list[tuple[str, list[dict[str, Any]]]] = []

        async def _emit(thread_id: str, entries: list[dict[str, Any]]) -> int:
            batches.append((thread_id, entries))
            return len(entries)

        monkeypatch.setattr("backend.state.events.emit_events", _emit)

        receipt = await advisor.execute_action(ACCOUNT, intent.action_id)

        # The publish really dispatched; it just did not emit *here*.
        assert len(recorder.requests) == 1
        assert receipt.status is ActionExecutionStatus.SUCCEEDED
        assert batches == []
