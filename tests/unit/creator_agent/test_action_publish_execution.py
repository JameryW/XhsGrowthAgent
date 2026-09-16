"""P2a-S3: the Action Executor's publish path.

Four things are pinned here.

1. **The payload is built from the intent, and only from the intent.**  That
   determinism is what makes a receipt a statement about *that* intent rather
   than about whoever happened to call execute; and every payload key must be a
   parameter the tool really accepts, because the Gateway hands the whole
   mapping to ``ainvoke``.
2. **One mapping from the Gateway's vocabulary to the platform's.**  A result is
   either an answer (a domain outcome, whose *payload* is read) or a runtime
   failure.  The nested-payload shape is asserted directly: burying the verdict
   one level down still type-checks, still raises, and silently turns every
   verdict into an unexplained failure.
3. **Every refusal happens before the Gateway.**  No thread, unreadable
   artifact, body that does not match the hash a human confirmed: each must
   leave no call and no receipt behind.
4. **The default dispatcher is the real production path.**  A fake in the seam
   proves the seam works; only the real shared Gateway down to a lazily resolved
   tool proves the production wiring does.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any

import pytest
from langchain_core.tools import tool
from langgraph.store.memory import InMemoryStore

from backend.creator_agent import (
    ActionCapability,
    ActionExecutionStatus,
    ActionIntent,
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
    PublishOutcome,
    PublishRequest,
    PublishStatus,
    build_publish_payload,
    interpret_publish_result,
)
from backend.creator_agent.execution import (
    PUBLISH_CAPABILITY,
    gateway_publish_dispatcher,
    load_publish_content,
)
from backend.creator_agent.repository import (
    ActionCredentialUnavailableError,
    ActionPublishContentUnavailableError,
)
from backend.db import creator_agent as creator_agent_db
from backend.services.xhs_credentials import XhsCredential
from backend.services.xhs_risk_gate import reset_gates_for_tests
from backend.state.artifacts import put_artifact
from backend.tools.runtime.bridge import shared_gateway
from backend.tools.runtime.gateway import PermissionDeniedError
from backend.tools.runtime.models import ErrorKind, ToolResult

ACCOUNT = "account-a"
THREAD = "thread-1"
KEY = "publish-1"
NOW = "2026-01-01T00:00:00+00:00"
BODY: dict[str, Any] = {
    "title": "一条耐用的笔记",
    "body": "正文内容",
    "hashtags": ["耐用"],
    "image_paths": ["/tmp/a.png"],
}

# P2a-S5a: a publish account must hold the credential the runtime requires, so
# these fixtures *state* one instead of inheriting an empty test environment.
# ``a1`` is the login material ``XHSCookieParser.is_valid`` looks for, so this
# is a usable credential rather than a plausible-looking string.
COOKIE = "a1=" + "0" * 20 + "; web_session=session"


async def _credentialed(account_id: str) -> XhsCredential:
    """The credential seam, standing in for the real resolver.

    Injecting the *answer* (not a bypass) is the point: the executor still
    derives its verdict from ``XhsCredential.scopes``, so a test that wants to
    see the credential refusal only has to state an empty credential.
    """
    return XhsCredential(account_id=account_id, cookie=COOKIE, source="account")


@pytest.fixture(autouse=True)
def _reset():
    creator_agent_db._reset_memory_store()
    reset_calls = reset_gates_for_tests()
    yield
    creator_agent_db._reset_memory_store()
    reset_gates_for_tests()
    _ = reset_calls


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
        self.outcome = outcome or PublishOutcome(status=PublishStatus.PUBLISHED, note_id="note-1")
        self.requests: list[PublishRequest] = []

    async def __call__(self, request: PublishRequest) -> PublishOutcome:
        self.requests.append(request)
        return self.outcome


def _request() -> PublishRequest:
    return PublishRequest(
        account_id=ACCOUNT,
        thread_id=THREAD,
        idempotency_key=KEY,
        artifact_ref="artifact://publish_payload/latest",
        content_hash="a" * 64,
        content=load_publish_content(BODY),  # type: ignore[arg-type]
    )


async def _advisor(
    store: Any, publish: Any, credentials: Any = _credentialed
) -> tuple[CreatorAdvisor, str]:
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model(ACCOUNT, _definition(), expected_revision=0)
    advisor = CreatorAdvisor(repo, artifact_store=store, publish=publish, credentials=credentials)
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
    thread_id: str | None = THREAD,
) -> ActionIntent:
    intent = await advisor.plan_action(
        ActionIntentRequest(
            account_id=ACCOUNT,
            decision_id=decision_id,
            action_kind=ActionCapability.PUBLISH,
            idempotency_key=KEY,
            artifact_ref=artifact_ref,
            content_hash=content_hash,
            thread_id=thread_id,
        )
    )
    await advisor.resolve_action(
        ACCOUNT,
        intent.action_id,
        ActionResolution(disposition=ActionResolutionDisposition.CONFIRMED),
    )
    return intent


class TestThePublishPayload:
    def test_it_carries_the_content_and_the_two_runtime_keys(self):
        payload = build_publish_payload(_request())
        assert payload["account_id"] == ACCOUNT
        assert payload["idempotency_key"] == KEY
        assert payload["title"] == "一条耐用的笔记"
        assert payload["image_paths"] == ["/tmp/a.png"]

    def test_every_payload_key_is_a_parameter_the_tool_accepts(self):
        """The Gateway hands the whole mapping to ``ainvoke``.

        A key the tool's own schema does not declare fails validation *inside*
        the runtime, so the two sets are compared instead of kept in sync by
        hand -- this is the check that would have caught adding
        ``account_id``/``idempotency_key`` to the payload without extending the
        tool's signature.
        """
        from backend.tools.xhs.publisher import xhs_publisher

        declared = set(xhs_publisher.args_schema.model_fields)
        accepted = set(build_publish_payload(_request()))
        assert accepted <= declared, accepted - declared

    def test_it_is_built_only_from_the_request(self):
        assert build_publish_payload(_request()) == build_publish_payload(_request())

    def test_a_body_without_a_title_is_not_publishable(self):
        assert load_publish_content({"title": "  ", "body": "x"}) is None
        assert load_publish_content({"title": "x"}) is None
        assert load_publish_content("not a mapping") is None


class TestTheResultVocabulary:
    def _ok(self, value: Any) -> ToolResult:
        return ToolResult(capability=PUBLISH_CAPABILITY, ok=True, value=value)

    def _domain(self, payload: Mapping[str, Any]) -> ToolResult:
        return ToolResult(
            capability=PUBLISH_CAPABILITY,
            ok=False,
            error="domain outcome: refused",
            error_kind=ErrorKind.DOMAIN,
            domain=dict(payload),
        )

    def _runtime_failure(self, kind: ErrorKind) -> ToolResult:
        return ToolResult(
            capability=PUBLISH_CAPABILITY, ok=False, error="timeout after 900s", error_kind=kind
        )

    def test_a_published_result_carries_the_note_identity(self):
        outcome = interpret_publish_result(
            self._ok({"status": "published", "post_id": "note-7", "post_url": "https://x/note-7"})
        )
        assert outcome.status is PublishStatus.PUBLISHED
        assert outcome.note_id == "note-7"
        assert outcome.note_url == "https://x/note-7"
        assert outcome.succeeded is True

    def test_an_ambiguous_verdict_is_read_out_of_the_domain_payload(self):
        outcome = interpret_publish_result(self._domain({"status": "unknown", "error": "结果不明"}))
        assert outcome.status is PublishStatus.UNKNOWN
        assert outcome.succeeded is False
        assert outcome.error == "结果不明"

    def test_a_nested_verdict_would_be_an_unexplained_failure(self):
        """The regression this slice nearly shipped, asserted from the reader's side.

        A domain payload that carries the verdict under a ``payload`` key still
        constructs, still raises and still reads -- as a failure with a generic
        message.  Pinning the *wrong* shape here is what makes the right shape
        meaningful.
        """
        nested = self._domain({"reason": "refused", "payload": {"status": "unknown"}})
        outcome = interpret_publish_result(nested)
        assert outcome.status is PublishStatus.FAILED
        assert outcome.error == "publish did not report success"

    def test_a_blocked_publish_keeps_its_retry_hint(self):
        outcome = interpret_publish_result(
            self._domain(
                {
                    "status": "failed",
                    "error": "发布冷却中。",
                    "retry_after_seconds": 42,
                }
            )
        )
        assert outcome.status is PublishStatus.FAILED
        assert outcome.retry_after_seconds == 42

    @pytest.mark.parametrize("kind", [ErrorKind.TIMEOUT, ErrorKind.EXCEPTION])
    def test_a_runtime_failure_is_a_failure_with_the_runtime_message(self, kind):
        outcome = interpret_publish_result(self._runtime_failure(kind))
        assert outcome.status is PublishStatus.FAILED
        assert outcome.error == "timeout after 900s"


class TestEveryRefusalPrecedesTheGateway:
    async def test_an_intent_without_a_thread_is_refused(self):
        """A row written before P2a-S3 has no thread, so its ref is unresolvable."""
        store = InMemoryStore()
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        ref, digest = await _stored(store, BODY)
        legacy = ActionIntent(
            action_id="legacy-1",
            account_id=ACCOUNT,
            creator_id="creator-a",
            audience_id="audience-a",
            decision_id=decision_id,
            action_kind=ActionCapability.PUBLISH,
            candidate_ids=[],
            idempotency_key=KEY,
            status=ActionStatus.CONFIRMED,
            created_at=NOW,
            updated_at=NOW,
            artifact_ref=ref,
            content_hash=digest,
        )
        await advisor._repository.create_action(legacy)  # noqa: SLF001

        with pytest.raises(ActionPublishContentUnavailableError) as excinfo:
            await advisor.execute_action(ACCOUNT, legacy.action_id)

        assert "thread" in excinfo.value.reason
        assert recorder.requests == []
        assert await advisor.get_action_execution(ACCOUNT, legacy.action_id) is None

    async def test_an_unreadable_artifact_is_refused(self):
        store = InMemoryStore()
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        # A ref that validates but points at nothing in this thread's store.
        intent = await _confirmed_publish(
            advisor,
            decision_id,
            artifact_ref="artifact://publish_payload/missing",
            content_hash="a" * 64,
        )

        with pytest.raises(ActionPublishContentUnavailableError) as excinfo:
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert "no publishable body" in excinfo.value.reason
        assert recorder.requests == []
        assert await advisor.get_action_execution(ACCOUNT, intent.action_id) is None

    async def test_a_body_that_does_not_match_the_confirmed_hash_is_refused(self):
        """The hash is what the human confirmed; a mismatch would post something
        nobody approved, so it is a refusal rather than a warning."""
        store = InMemoryStore()
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        ref, _ = await _stored(store, BODY)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash="b" * 64
        )

        with pytest.raises(ActionPublishContentUnavailableError) as excinfo:
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert "content_hash" in excinfo.value.reason
        assert recorder.requests == []
        assert await advisor.get_action_execution(ACCOUNT, intent.action_id) is None


class TestTheCredentialRefusal:
    """P2a-S5a: an account that holds no credential cannot publish.

    The fourth refusal on this path, and the first one that is not about the
    intent: the intent can be perfectly well formed and still not be executable
    because the *account* was never credentialed.  It is asserted with the same
    two companions as its neighbours -- no Gateway call, no receipt -- because
    the only failure worth fearing here is a publish that happens anyway.
    """

    @staticmethod
    async def _empty(account_id: str) -> XhsCredential:
        return XhsCredential(account_id=account_id)

    async def test_an_account_with_no_credential_is_refused_before_the_gateway(self):
        store = InMemoryStore()
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder, credentials=self._empty)
        ref, digest = await _stored(store, BODY)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        with pytest.raises(ActionCredentialUnavailableError) as excinfo:
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert excinfo.value.account_id == ACCOUNT
        assert excinfo.value.required_scopes == ("xhs:write",)
        assert recorder.requests == []
        assert await advisor.get_action_execution(ACCOUNT, intent.action_id) is None

    def test_the_required_scope_is_read_from_the_capability_it_publishes_through(self):
        """The refusal asks for what ``xhs.publish`` declares, not for a literal.

        A literal here would be a second statement of the same requirement, free
        to drift from the catalog -- and the drift would be silent, because the
        Gateway would still enforce the *declared* one while the executor refused
        for the other.  Deriving it is what keeps the two in one place; this
        asserts the derivation really is the declaration.
        """
        from backend.creator_agent.advisor import _required_publish_scopes  # noqa: SLF001

        declared = shared_gateway().registry.spec(PUBLISH_CAPABILITY).auth_scope
        assert _required_publish_scopes() == tuple(declared)
        assert declared, "the publish capability must declare a scope to require"

    async def test_a_present_but_unusable_credential_is_not_a_credential(self):
        """Availability is half the answer, and presence is not availability.

        A cookie with no login material would put the HTTP client in the
        "configured, but every call fails" state; treating it as a grant would
        make the scope check agree with a credential that cannot be used.
        """

        async def _malformed(account_id: str) -> XhsCredential:
            return XhsCredential(account_id=account_id, cookie="web_session=stale")

        store = InMemoryStore()
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder, credentials=_malformed)
        ref, digest = await _stored(store, BODY)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        with pytest.raises(ActionCredentialUnavailableError):
            await advisor.execute_action(ACCOUNT, intent.action_id)

        assert recorder.requests == []

    async def test_entitlement_is_answered_without_reading_the_artifact(self):
        """Ordering, asserted rather than implied.

        With no credential *and* an unresolvable artifact, the verdict is the
        credential one.  That is the design: whether this account may publish at
        all does not depend on the artifact, so conditioning the answer on an
        artifact read would let an unentitled account be told its *content* was
        the problem -- and would make the verdict depend on the store being up.
        """
        recorder = _Recorder()
        advisor, decision_id = await _advisor(InMemoryStore(), recorder, credentials=self._empty)
        intent = await _confirmed_publish(
            advisor,
            decision_id,
            artifact_ref="artifact://publish_payload/missing",
            content_hash="a" * 64,
        )

        with pytest.raises(ActionCredentialUnavailableError):
            await advisor.execute_action(ACCOUNT, intent.action_id)

    async def test_a_credentialed_account_still_publishes(self):
        """The contrast that keeps the refusal from being a blanket.

        Same fixture, one difference: the account holds a usable credential --
        and the intent reaches the dispatcher exactly as it did before S5a.
        """
        store = InMemoryStore()
        recorder = _Recorder()
        advisor, decision_id = await _advisor(store, recorder)
        ref, digest = await _stored(store, BODY)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        receipt = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert [request.account_id for request in recorder.requests] == [ACCOUNT]
        assert receipt.status is ActionExecutionStatus.SUCCEEDED


class TestTheReceipt:
    async def _executed(self, outcome: PublishOutcome):
        store = InMemoryStore()
        recorder = _Recorder(outcome)
        advisor, decision_id = await _advisor(store, recorder)
        ref, digest = await _stored(store, BODY)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )
        receipt = await advisor.execute_action(ACCOUNT, intent.action_id)
        return advisor, intent, receipt, recorder

    async def test_a_published_note_mints_a_succeeded_receipt(self):
        _, intent, receipt, _ = await self._executed(
            PublishOutcome(
                status=PublishStatus.PUBLISHED, note_id="note-7", note_url="https://x/note-7"
            )
        )
        assert receipt.status is ActionExecutionStatus.SUCCEEDED
        assert receipt.action_id == intent.action_id
        assert receipt.result["status"] == "published"
        assert receipt.result["note_id"] == "note-7"
        assert receipt.result["note_url"] == "https://x/note-7"

    async def test_the_dispatcher_receives_the_intents_own_identity(self):
        """Account, thread and idempotency key all come off the immutable intent."""
        _, intent, _, recorder = await self._executed(
            PublishOutcome(status=PublishStatus.PUBLISHED)
        )
        assert len(recorder.requests) == 1
        sent = recorder.requests[0]
        assert sent.account_id == ACCOUNT
        assert sent.thread_id == THREAD
        assert sent.idempotency_key == intent.idempotency_key
        assert sent.content_hash == intent.content_hash
        assert sent.content.title == BODY["title"]

    async def test_a_failed_publish_mints_a_failed_receipt_rather_than_raising(self):
        """The execution *happened*; its outcome is what failed."""
        _, _, receipt, _ = await self._executed(
            PublishOutcome(
                status=PublishStatus.FAILED, error="发布冷却中。", retry_after_seconds=20
            )
        )
        assert receipt.status is ActionExecutionStatus.FAILED
        assert receipt.result["status"] == "failed"
        assert receipt.result["error"] == "发布冷却中。"
        assert receipt.result["retry_after_seconds"] == 20

    async def test_an_unknown_outcome_shares_failed_but_keeps_its_status(self):
        """An ambiguous publish must not read as "nothing happened".

        ``ActionExecutionStatus`` has no third value, so ``result["status"]`` is
        where the distinction lives -- and that is exactly why it is asserted
        here rather than assumed.
        """
        _, _, receipt, _ = await self._executed(
            PublishOutcome(status=PublishStatus.UNKNOWN, error="提交已发起，结果不明")
        )
        assert receipt.status is ActionExecutionStatus.FAILED
        assert receipt.result["status"] == "unknown"
        assert "note_id" not in receipt.result

    async def test_re_executing_returns_the_same_receipt_and_republishes_nothing(self):
        store = InMemoryStore()
        recorder = _Recorder(PublishOutcome(status=PublishStatus.PUBLISHED, note_id="note-7"))
        advisor, decision_id = await _advisor(store, recorder)
        ref, digest = await _stored(store, BODY)
        intent = await _confirmed_publish(
            advisor, decision_id, artifact_ref=ref, content_hash=digest
        )

        first = await advisor.execute_action(ACCOUNT, intent.action_id)
        second = await advisor.execute_action(ACCOUNT, intent.action_id)

        assert first.execution_id == second.execution_id
        assert len(recorder.requests) == 1


class TestTheDefaultDispatcherIsTheRealPath:
    @pytest.mark.asyncio
    async def test_it_reaches_the_shared_gateway_and_the_lazily_resolved_tool(self, monkeypatch):
        """A fake in the seam proves the seam; this proves the wiring.

        ``catalog.bind`` resolves the implementation by module attribute on every
        call, which is exactly why replacing ``xhs_publisher`` here is honoured
        instead of being frozen at build time.

        P2a-S5a adds one more link to that chain, so the credential is supplied
        the way a single-account deployment supplies it -- ``XHS_COOKIE`` in the
        environment.  The test therefore runs the whole production path:
        environment -> ``services.xhs_credentials`` -> granted scopes ->
        ``xhs.publish``'s declared ``auth_scope`` -> the Gateway -> the tool.
        """
        seen: list[dict[str, Any]] = []

        @tool
        async def _stand_in(
            title: str,
            body: str,
            hashtags: list[str] | None = None,
            image_paths: list[str] | None = None,
            category: str = "",
            location: str = "",
            scheduled_time: str = "",
            is_private: bool = False,
            account_id: str = "",
            idempotency_key: str = "",
        ) -> dict[str, Any]:
            """A stand-in with the real signature."""
            seen.append({"title": title, "account_id": account_id, "key": idempotency_key})
            return {"post_id": "note-9", "post_url": "https://x/note-9", "status": "published"}

        declared = inspect.signature(_stand_in.coroutine).parameters
        payload = build_publish_payload(_request())
        assert set(payload) <= set(declared), set(payload) - set(declared)
        required = {
            name for name, param in declared.items() if param.default is inspect.Parameter.empty
        }
        assert required <= set(payload), required - set(payload)
        monkeypatch.setattr("backend.tools.xhs.publisher.xhs_publisher", _stand_in)
        monkeypatch.setenv("XHS_COOKIE", COOKIE)

        outcome = await gateway_publish_dispatcher()(_request())

        assert outcome.status is PublishStatus.PUBLISHED
        assert outcome.note_id == "note-9"
        assert seen == [{"title": "一条耐用的笔记", "account_id": ACCOUNT, "key": KEY}]
        assert PUBLISH_CAPABILITY in shared_gateway().registry.capabilities()

    @pytest.mark.asyncio
    async def test_an_unusable_credential_stops_the_publish_at_the_scope_check(self, monkeypatch):
        """The declaration stops being decorative, which is the whole point.

        ``xhs.publish`` has declared ``auth_scope=("xhs:write",)`` since S1, but
        every production caller passed ``granted_scopes=None`` and the Gateway
        reads that as *unchecked* -- so the requirement had no effect.  With the
        scopes resolved from the account, an account whose credential cannot be
        used holds no scope at all and is refused *before the tool is resolved*:
        nothing is posted, and no receipt is minted further up.

        The cookie is set to a malformed value rather than removed, so the test
        states the condition instead of depending on the machine's environment
        (and on the environment beating whatever ``.env`` holds).
        """
        calls: list[str] = []

        @tool
        async def _stand_in(
            title: str,
            body: str,
            hashtags: list[str] | None = None,
            image_paths: list[str] | None = None,
            category: str = "",
            location: str = "",
            scheduled_time: str = "",
            is_private: bool = False,
            account_id: str = "",
            idempotency_key: str = "",
        ) -> dict[str, Any]:
            """A stand-in that would publish if it were ever reached."""
            calls.append(title)
            return {"post_id": "note-9", "status": "published"}

        monkeypatch.setattr("backend.tools.xhs.publisher.xhs_publisher", _stand_in)
        monkeypatch.setenv("XHS_COOKIE", "web_session=no-login-material")

        with pytest.raises(PermissionDeniedError):
            await gateway_publish_dispatcher()(_request())

        assert calls == []


class TestTheRuntimeBudget:
    def test_the_publish_net_outlives_the_generic_slow_net(self):
        """The net has to sit *above* the tool's own budget, not below it.

        ``services.xhs_publisher`` can hold the CDP lock for hundreds of seconds
        before it even starts uploading, so the Gateway generic SLOW net (120s)
        would cancel a publish that is still legitimately in flight -- and
        report a timeout for a submit that may well have gone out.  That is a
        worse answer than the one it pre-empted.  The generic net is *derived*
        here rather than repeated as a literal, so lowering it cannot silently
        invert the ordering this asserts.
        """
        from backend.tools.runtime.catalog import build_registry
        from backend.tools.runtime.models import LatencyClass, SideEffect, ToolSpec

        generic = ToolSpec(
            capability="demo.slow",
            summary="the generic net, by definition",
            side_effect=SideEffect.PURE,
            latency=LatencyClass.SLOW,
        ).effective_timeout_s
        spec = build_registry().spec(PUBLISH_CAPABILITY)

        assert spec.latency is LatencyClass.SLOW
        assert spec.timeout_s is not None, "publish must carry its own net"
        assert spec.timeout_s > generic
