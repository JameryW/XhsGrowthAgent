"""The engagement send path is a checked Tool Gateway call site (票 5av).

Two things have to stay true, and they are different questions:

1. **The declaration is satisfiable and enforced.**  ``xhs.comment_reply`` /
   ``xhs.dm_send`` declare ``("xhs:write", "xhs:outreach")``; a Gateway call
   that does not hold both is refused before the tool runs (§3.1's “do not
   declare a scope nobody checks”, retired).
2. **The service really dispatches through it.**  ``XHSEngagement`` resolves the
   account's grant (``granted_scopes(account_id)``, injectable seam), judges it
   before the Effect ledger claim, and hands the same tuple to
   ``shared_gateway().invoke(...)``.  Precheck/quota/ledger ordering is the
   pre-existing contract and is unchanged: gates → policy → scope → claim →
   send → record → quota.

The two capabilities are one behaviour apiece in the same class, so most tests
are parametrized.  Direct capability invocation (operator → Gateway → tool)
keeps its historical shape — the outer call already went through the Gateway,
so the service does not nest one — and that is pinned here too.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from backend.db.engagement_effects import _reset_memory_store
from backend.services.xhs_effect_ledger import (
    EffectKind,
    EffectState,
    EngagementApproval,
    EngagementEffectLedger,
    effect_idempotency_key,
)
from backend.services.xhs_engagement import (
    _ENGAGEMENT_REQUIRED_SCOPES,
    COMMENT_REPLY_CAPABILITY,
    DM_CAPABILITY,
    XHSEngagement,
)
from backend.tools.runtime.catalog import build_registry
from backend.tools.runtime.gateway import PermissionDeniedError, ToolGateway
from backend.tools.runtime.models import ErrorKind, ToolResult

GATE = "backend.services.xhs_risk_gate"


def _approval() -> EngagementApproval:
    return EngagementApproval(
        thread_id="thread-1",
        approved_by="operator-1",
        approved_at="2026-10-13T00:00:00+00:00",
    )


def _scopes(*scopes: str):
    """A scope seam answering with exactly ``scopes``."""

    async def _resolve(_account_id: str) -> tuple[str, ...]:
        return tuple(scopes)

    return _resolve


class _FakeGateway:
    """Records one invocation and answers with a prepared ``ToolResult``."""

    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def invoke(
        self,
        capability: str,
        payload: Mapping[str, Any] | None = None,
        *,
        thread_id: str = "",
        granted_scopes: tuple[str, ...] | None = None,
    ) -> ToolResult:
        self.calls.append(
            {
                "capability": capability,
                "payload": dict(payload or {}),
                "thread_id": thread_id,
                "granted_scopes": granted_scopes,
            }
        )
        return self.result


def _sent_comment_verdict() -> dict[str, Any]:
    return {
        "success": True,
        "status": "sent",
        "error_code": "",
        "error": "",
        "receipt_id": "",
        "receipt_source": "none",
        "correlation_id": "comment_reply-x",
        "verified": True,
        "retryable": False,
    }


def _blocked_verdict(code: str = "risk_control") -> dict[str, Any]:
    return {
        "success": False,
        "status": "blocked",
        "error_code": code,
        "error": "风控拦截",
        "receipt_id": "",
        "receipt_source": "none",
        "correlation_id": "dm-x",
        "verified": False,
        "retryable": False,
    }


def _page():
    from unittest.mock import AsyncMock, MagicMock

    page = MagicMock(url="https://www.xiaohongshu.com/explore/note-1")
    page.evaluate = AsyncMock(return_value="")
    page.goto = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.wait_for_function = AsyncMock()
    page.query_selector = AsyncMock(return_value=None)
    return page


_UNSET = object()


def _engagement(*, gateway: Any = None, scopes: Any = _UNSET) -> XHSEngagement:
    from contextlib import asynccontextmanager
    from unittest.mock import AsyncMock

    @asynccontextmanager
    async def _noop_hold(**_kwargs: Any):
        yield "acc-1"

    options: dict[str, Any] = {}
    if scopes is not _UNSET:
        options["scope_resolver"] = _scopes(*scopes)

    engagement = XHSEngagement(
        cdp_endpoint="http://127.0.0.1:9224",
        account_id="acc-1",
        cooldown_seconds=0.0,
        gateway=gateway,
        **options,
    )
    engagement._ensure_page = AsyncMock(return_value=_page())
    engagement._hold_cdp = AsyncMock(side_effect=lambda: _noop_hold())
    return engagement


@pytest.fixture(autouse=True)
def _clean_effects():
    _reset_memory_store()
    yield
    _reset_memory_store()


@pytest.fixture(autouse=True)
def _open_gates(monkeypatch: pytest.MonkeyPatch):
    """Every non-scope gate passes; each test states only the condition it is about."""
    for name in (
        "check_engagement_risk_pause",
        "check_comment_reply_quota",
        "check_dm_quota",
        "check_dm_target_allowed",
        "check_engagement_allowed",
    ):
        monkeypatch.setattr(f"{GATE}.{name}", lambda *a, **k: None)
    for name in ("note_comment_reply_sent", "note_dm_sent", "note_engagement_risk_pause"):
        monkeypatch.setattr(f"{GATE}.{name}", lambda *a, **k: None)


class TestTheDeclarationIsSatisfiableAndEnforced:
    def test_the_service_requirement_mirrors_the_catalog_declaration(self):
        """The service's pre-gate and the catalogue cannot drift apart."""
        registry = build_registry()
        for capability in (COMMENT_REPLY_CAPABILITY, DM_CAPABILITY):
            assert registry.spec(capability).auth_scope == _ENGAGEMENT_REQUIRED_SCOPES[capability]

    async def test_a_call_without_the_engagement_tier_is_refused(self):
        """§3.1: the declaration must be checked, not decorative."""
        gateway = ToolGateway(build_registry())

        with pytest.raises(PermissionDeniedError) as exc:
            await gateway.invoke(COMMENT_REPLY_CAPABILITY, {}, granted_scopes=())
        assert exc.value.missing == ("xhs:write", "xhs:outreach")

        with pytest.raises(PermissionDeniedError) as exc:
            await gateway.invoke(COMMENT_REPLY_CAPABILITY, {}, granted_scopes=("xhs:write",))
        assert exc.value.missing == ("xhs:outreach",)

    async def test_a_call_without_the_write_mechanism_is_refused(self):
        gateway = ToolGateway(build_registry())

        with pytest.raises(PermissionDeniedError) as exc:
            await gateway.invoke(DM_CAPABILITY, {}, granted_scopes=("xhs:outreach",))
        assert exc.value.missing == ("xhs:write",)

    async def test_the_scope_check_runs_before_the_tool(self, monkeypatch):
        """A refusal must not touch the browser: the tool would fail loudly if run."""

        def _must_not_run(*_a: Any, **_k: Any) -> None:
            raise AssertionError("tool ran despite the missing scope")

        monkeypatch.setattr("backend.tools.xhs.engagement._get_engagement", _must_not_run)
        with pytest.raises(PermissionDeniedError):
            await ToolGateway(build_registry()).invoke(
                COMMENT_REPLY_CAPABILITY, {}, granted_scopes=()
            )


class TestTheServiceDispatchesThroughTheGateway:
    async def test_the_comment_path_passes_capability_thread_and_grant(self):
        gateway = _FakeGateway(
            ToolResult(
                capability=COMMENT_REPLY_CAPABILITY,
                ok=True,
                value=_sent_comment_verdict(),
            )
        )
        engagement = _engagement(gateway=gateway, scopes=("xhs:write", "xhs:outreach"))

        result = await engagement.reply_to_comment(
            "note-1", "comment-1", "谢谢", approval=_approval()
        )

        assert result["status"] == "sent"
        (call,) = gateway.calls
        assert call["capability"] == COMMENT_REPLY_CAPABILITY
        assert call["thread_id"] == "thread-1"
        assert call["granted_scopes"] == ("xhs:write", "xhs:outreach")
        # Payload is shaped for the capability's StructuredTool input.
        assert call["payload"] == {
            "comment_id": "comment-1",
            "post_id": "note-1",
            "reply_content": "谢谢",
            "account_id": "acc-1",
            "approved_by": "operator-1",
            "approved_at": "2026-10-13T00:00:00+00:00",
            "thread_id": "thread-1",
        }

    async def test_the_dm_path_passes_capability_thread_and_grant(self):
        gateway = _FakeGateway(
            ToolResult(
                capability=DM_CAPABILITY,
                ok=False,
                error="domain outcome: risk_control",
                error_kind=ErrorKind.DOMAIN,
                domain=_blocked_verdict(),
            )
        )
        engagement = _engagement(gateway=gateway, scopes=("xhs:write", "xhs:outreach"))

        result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == "blocked"
        assert result["error_code"] == "risk_control"
        (call,) = gateway.calls
        assert call["capability"] == DM_CAPABILITY
        assert call["thread_id"] == ""
        assert call["payload"]["sender_id"] == "user-9"
        assert call["payload"]["account_id"] == "acc-1"

    async def test_the_default_seam_is_the_credential_owner(self, monkeypatch):
        """Production resolution goes through ``granted_scopes(account_id)``."""
        asked: list[str] = []

        async def _granted(account_id: str) -> tuple[str, ...]:
            asked.append(account_id)
            return ("xhs:write", "xhs:outreach")

        monkeypatch.setattr("backend.services.xhs_credentials.granted_scopes", _granted)
        gateway = _FakeGateway(
            ToolResult(
                capability=COMMENT_REPLY_CAPABILITY,
                ok=True,
                value=_sent_comment_verdict(),
            )
        )
        # No ``scope_resolver`` ⇒ the default seam resolves the grant.
        engagement = _engagement(gateway=gateway)

        await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert asked == ["acc-1"]
        assert gateway.calls[0]["granted_scopes"] == ("xhs:write", "xhs:outreach")


class TestTheServiceJudgesTheGrantBeforeTheClaim:
    async def test_a_missing_tier_is_blocked_without_a_gateway_call_or_ledger_row(self):
        gateway = _FakeGateway(
            ToolResult(capability=COMMENT_REPLY_CAPABILITY, ok=True, value=_sent_comment_verdict())
        )
        engagement = _engagement(gateway=gateway, scopes=("xhs:write",))

        result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == "blocked"
        assert result["error_code"] == "permission_denied"
        assert "xhs:outreach" in result["error"]
        assert gateway.calls == []
        engagement._ensure_page.assert_not_awaited()
        assert await EngagementEffectLedger().list("acc-1") == []

    async def test_a_missing_mechanism_is_blocked_without_a_gateway_call(self):
        gateway = _FakeGateway(
            ToolResult(capability=DM_CAPABILITY, ok=True, value=_sent_comment_verdict())
        )
        engagement = _engagement(gateway=gateway, scopes=("xhs:outreach",))

        result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == "blocked"
        assert result["error_code"] == "permission_denied"
        assert "xhs:write" in result["error"]
        assert gateway.calls == []


class TestTheVerdictMappingStaysSafe:
    async def test_a_gateway_timeout_is_unknown_not_failed(self):
        """A cancelled submit may already have happened — never report it failed."""
        gateway = _FakeGateway(
            ToolResult(
                capability=COMMENT_REPLY_CAPABILITY,
                ok=False,
                error="timeout after 300s",
                error_kind=ErrorKind.TIMEOUT,
            )
        )
        engagement = _engagement(gateway=gateway, scopes=("xhs:write", "xhs:outreach"))
        key = effect_idempotency_key(EffectKind.COMMENT_REPLY, "acc-1", "comment-1", "谢谢")

        result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == "unknown"
        assert result["error_code"] == "gateway_timeout"
        assert result["retryable"] is False
        row = await EngagementEffectLedger().get("acc-1", key)
        assert row is not None
        assert row.state == EffectState.UNKNOWN.value

    async def test_a_tool_exception_is_unknown_not_failed(self):
        gateway = _FakeGateway(
            ToolResult(
                capability=DM_CAPABILITY,
                ok=False,
                error="RuntimeError: page crashed",
                error_kind=ErrorKind.EXCEPTION,
            )
        )
        engagement = _engagement(gateway=gateway, scopes=("xhs:write", "xhs:outreach"))
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "user-9", "你好")

        result = await engagement.send_dm("user-9", "你好")

        assert result["status"] == "unknown"
        assert result["error_code"] == "gateway_error"
        row = await EngagementEffectLedger().get("acc-1", key)
        assert row is not None
        assert row.state == EffectState.UNKNOWN.value

    async def test_a_domain_verdict_lands_on_refused(self):
        gateway = _FakeGateway(
            ToolResult(
                capability=DM_CAPABILITY,
                ok=False,
                error="domain outcome: risk_control",
                error_kind=ErrorKind.DOMAIN,
                domain=_blocked_verdict(),
            )
        )
        engagement = _engagement(gateway=gateway, scopes=("xhs:write", "xhs:outreach"))
        key = effect_idempotency_key(EffectKind.DM, "acc-1", "user-9", "你好")

        result = await engagement.send_dm("user-9", "你好")

        assert result["error_code"] == "risk_control"
        row = await EngagementEffectLedger().get("acc-1", key)
        assert row is not None
        assert row.state == EffectState.REFUSED.value

    async def test_a_verified_sent_still_resolves_sent(self):
        gateway = _FakeGateway(
            ToolResult(
                capability=COMMENT_REPLY_CAPABILITY,
                ok=True,
                value=_sent_comment_verdict(),
            )
        )
        engagement = _engagement(gateway=gateway, scopes=("xhs:write", "xhs:outreach"))
        key = effect_idempotency_key(EffectKind.COMMENT_REPLY, "acc-1", "comment-1", "谢谢")

        result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == "sent"
        row = await EngagementEffectLedger().get("acc-1", key)
        assert row is not None
        assert row.state == EffectState.RESOLVED_SENT.value


class TestTheDirectCapabilityPathDoesNotNestTheGateway:
    async def test_inside_capability_runs_the_browser_step_directly(self):
        """Operator → Gateway → tool → service: the outer call *is* the Gateway.

        Nesting a second invocation would wait out its own
        ``max_concurrency=1`` slot, so the capability-side instance must run the
        transport itself — exactly the shape the tool path had before 票 5av.
        """
        from contextlib import asynccontextmanager
        from unittest.mock import AsyncMock

        class _ExplodingGateway:
            async def invoke(self, *_a: Any, **_k: Any) -> ToolResult:
                raise AssertionError("direct capability invocation must not nest the Gateway")

        @asynccontextmanager
        async def _noop_hold(**_kwargs: Any):
            yield "acc-1"

        engagement = XHSEngagement(
            cdp_endpoint="http://127.0.0.1:9224",
            account_id="acc-1",
            cooldown_seconds=0.0,
            gateway=_ExplodingGateway(),
            scope_resolver=_scopes(),  # no grant: direct path must not care
            inside_capability=True,
        )
        seen: list[str] = []

        async def _transport(note_id: str, comment_id: str, reply_content: str, **_kw: Any):
            seen.append(comment_id)
            return {
                "success": True,
                "status": "sent",
                "error_code": "",
                "error": "",
                "receipt_id": "",
                "receipt_source": "none",
                "correlation_id": "comment_reply-direct",
                "verified": True,
                "retryable": False,
            }

        engagement._reply_to_comment_locked = _transport  # type: ignore[method-assign]
        engagement._hold_cdp = AsyncMock(side_effect=lambda: _noop_hold())
        engagement._ensure_page = AsyncMock(return_value=_page())

        result = await engagement.reply_to_comment("note-1", "comment-1", "谢谢")

        assert result["status"] == "sent"
        assert seen == ["comment-1"]
