"""The engagement-migration spec's claims stay true against the tree.

``docs/tool-gateway-engagement-migration.md`` publishes facts about the code
(the Phase A contracts, the §3.0 spec draft, the registration boundary), and
this file recomputes them. It used to pin the *unwired* state; 票 5f
registered ``xhs.comment_reply`` / ``xhs.dm_send`` (Phase B — §9.4 was
decided "yes"), so the pins below now describe what registration must keep
true: the §3.0 spec fields, and §8 item 9 — the trace carries the fact,
never the body.

Same contract as ``test_docs_capability_table.py``: the document publishes
facts, the test recomputes them from the tree.

``TestTheScopeCheckIsStillOptIn`` pins the fact §7.1 leans on -- a declared
``auth_scope`` is enforced only when the caller passes ``granted_scopes``.
That is why registration, not scoping, is the boundary. If the Gateway ever
makes the check mandatory, the spec's conclusion changes and this file fails,
sending its reader back to §7.1.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.runtime.audit import scan_tool_functions
from backend.tools.runtime.bridge import shared_gateway
from backend.tools.runtime.catalog import build_registry
from backend.tools.runtime.gateway import PermissionDeniedError, ToolGateway
from backend.tools.runtime.models import (
    ErrorKind,
    LatencyClass,
    SideEffect,
    ToolSpec,
)
from backend.tools.runtime.registry import ToolRegistry

DOC = Path(__file__).resolve().parents[4] / "docs" / "tool-gateway-engagement-migration.md"

COMMENT_CAPABILITY = "xhs.comment_reply"
DM_CAPABILITY = "xhs.dm_send"

# ``module:function``, the form scan_tool_functions reports.
COMMENT_TOOL = "backend.tools.xhs.engagement:comment_replier"
DM_TOOL = "backend.tools.xhs.engagement:dm_handler"

_MODULE = "backend.tools.xhs.engagement"
_SECRET_BODY = "SECRET-正文-外发内容-8f3a"


class TestTheSpecIsNowWired:
    """§3.0/§状态 — registration is the moment agents can reach them (§7.1)."""

    def test_both_capabilities_are_registered(self):
        registered = set(shared_gateway().registry.capabilities())
        assert COMMENT_CAPABILITY in registered
        assert DM_CAPABILITY in registered

    @pytest.mark.parametrize("capability", [COMMENT_CAPABILITY, DM_CAPABILITY])
    def test_the_registration_matches_the_spec_draft(self, capability: str):
        """Every §3.0 field, recomputed — a drift here is a safety change."""
        spec = shared_gateway().registry.spec(capability)
        assert spec.side_effect is SideEffect.SIDE_EFFECTING
        assert spec.latency is LatencyClass.SLOW
        assert spec.retry_policy.max_attempts == 1, "§3.3: a retry double-sends"
        assert spec.effective_timeout_s == 300, "§6: _ENGAGEMENT_SAFETY_NET_S"
        assert spec.auth_scope == ("xhs:write",), "§3.1: xhs:outreach stays undeclared"
        assert spec.max_concurrency == 1, "§3.2: one in-flight per account"

    def test_both_tools_still_exist_as_tool_decorated_functions(self):
        """The migration renames nothing silently: these are the two it moves.

        Read off the AST rather than by import — a gate must not run the tree.
        """
        tools = scan_tool_functions()
        assert COMMENT_TOOL in tools
        assert DM_TOOL in tools

    def test_the_spec_names_the_same_two_capability_ids(self):
        """Doc ↔ declaration: the ids a reader plans around must be the live ones."""
        text = DOC.read_text(encoding="utf-8")
        assert COMMENT_CAPABILITY in text
        assert DM_CAPABILITY in text


class TestTheTraceCarriesNoBodies:
    """§8 item 9 — ``side_effecting`` is recorded; what was *said* never is."""

    @staticmethod
    def _fake_engagement(verdict: dict[str, Any]) -> MagicMock:
        engagement = MagicMock()
        engagement.close = AsyncMock()
        engagement.reply_to_comment = AsyncMock(return_value=verdict)
        return engagement

    async def test_a_registered_engagement_call_leaks_no_reply_body(self):
        events: list[dict[str, Any]] = []

        async def trace(event: Mapping[str, Any]) -> None:
            events.append(dict(event))

        engagement = self._fake_engagement(
            {
                "success": False,
                "status": "failed",
                "error_code": "send_button_missing",
                "error": "未找到发送按钮：回复未提交",
                "receipt_id": "",
                "receipt_source": "none",
                "correlation_id": "comment_reply-abc123",
                "verified": False,
                "retryable": False,
            }
        )
        gateway = ToolGateway(build_registry(), trace=trace)
        with (
            patch(f"{_MODULE}._get_engagement", return_value=engagement),
            patch(f"{_MODULE}._resolve_engagement_cdp_endpoint", AsyncMock(return_value="")),
        ):
            result = await gateway.invoke(
                COMMENT_CAPABILITY,
                {
                    "comment_id": "c-1",
                    "post_id": "p-1",
                    "reply_content": _SECRET_BODY,
                    "approved_by": "operator-1",
                    "approved_at": "2026-10-20T00:00:00+00:00",
                    "thread_id": "thread-1",
                },
            )

        assert result.ok is False
        assert result.error_kind is ErrorKind.DOMAIN
        event = events[-1]
        assert event["side_effect"] == "side_effecting"
        assert event["domain_reason"], "the verdict reason travels"
        assert _SECRET_BODY not in repr(event), (
            "the trace is a fact log, not a transcript — the body belongs to "
            "ToolResult.domain (the caller's own payload), never to telemetry"
        )


class TestTheScopeCheckIsStillOptIn:
    """§7.1 — ``granted_scopes=None`` means *unchecked*, not *denied*.

    Built from a local spec rather than a catalogue capability, so this does not
    depend on — or accidentally pin — what the catalogue happens to declare.
    """

    @staticmethod
    def _gateway() -> ToolGateway:
        async def _call(payload: Mapping[str, Any]) -> dict[str, Any]:
            return {"reached": True}

        registry = ToolRegistry()
        registry.register(
            ToolSpec(
                capability="test.scoped_write",
                summary="a write guarded by a scope",
                side_effect=SideEffect.SIDE_EFFECTING,
                latency=LatencyClass.FAST,
                auth_scope=("test:write",),
            ),
            _call,
        )
        return ToolGateway(registry)

    async def test_a_declared_scope_is_not_enforced_without_granted_scopes(self):
        result = await self._gateway().invoke("test.scoped_write", {})
        assert result.ok is True

    async def test_the_same_scope_is_enforced_once_scopes_are_passed(self):
        """The contrast that makes the test above mean something."""
        with pytest.raises(PermissionDeniedError):
            await self._gateway().invoke("test.scoped_write", {}, granted_scopes=())
