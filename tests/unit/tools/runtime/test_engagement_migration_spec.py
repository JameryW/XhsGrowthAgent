"""The engagement-migration spec's premises stay true while it is unwritten.

``docs/tool-gateway-engagement-migration.md`` opens by saying it changes no
behaviour and registers no capability. That is a claim about the code, and this
file is what keeps it honest: when someone registers ``xhs.comment_reply`` /
``xhs.dm_send``, or renames the two ``@tool`` functions, these tests go red and
the spec has to be updated in the same commit instead of quietly describing a
state that no longer exists.

Same contract as ``test_docs_capability_table.py``: the document publishes
facts, the test recomputes them from the tree.

``TestTheScopeCheckIsStillOptIn`` pins the fact §7.1 leans on -- a declared
``auth_scope`` is enforced only when the caller passes ``granted_scopes``. That
is why registration, not scoping, is the boundary. If the Gateway ever makes the
check mandatory, the spec's conclusion changes and this file fails, sending its
reader back to §7.1.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from backend.tools.runtime.audit import scan_tool_functions
from backend.tools.runtime.bridge import shared_gateway
from backend.tools.runtime.gateway import PermissionDeniedError, ToolGateway
from backend.tools.runtime.models import LatencyClass, SideEffect, ToolSpec
from backend.tools.runtime.registry import ToolRegistry

DOC = Path(__file__).resolve().parents[4] / "docs" / "tool-gateway-engagement-migration.md"

COMMENT_CAPABILITY = "xhs.comment_reply"
DM_CAPABILITY = "xhs.dm_send"

# ``module:function``, the form scan_tool_functions reports.
COMMENT_TOOL = "backend.tools.xhs.engagement:comment_replier"
DM_TOOL = "backend.tools.xhs.engagement:dm_handler"


class TestTheSpecIsStillUnwired:
    def test_neither_capability_is_registered_yet(self):
        """§状态 — registering them is the moment agents can reach them (§7.1)."""
        registered = set(shared_gateway().registry.capabilities())
        assert COMMENT_CAPABILITY not in registered
        assert DM_CAPABILITY not in registered

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
