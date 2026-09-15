"""P1c-S5: the gate that keeps the agent layer on the runtime's side.

The interesting cases are the violations, not the clean run: a checker that
only ever sees a passing tree has demonstrated nothing. Every rule below is
exercised by a source that breaks it.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from backend.tools.runtime.audit import (
    DEFAULT_AGENTS_DIR,
    audit_tool_runtime,
    scan_agent_tool_usage,
    scan_direct_tool_imports,
)
from backend.tools.runtime.catalog import build_registry

_KNOWN = ("xhs.trending", "xhs.publish")


def _write(root: Path, name: str, body: str) -> Path:
    """Write a source, undoing the indentation of the triple-quoted fixture.

    Not a convenience: without ``dedent`` the fixture keeps the test method's
    indentation, the file stops parsing, and the gate — which used to skip
    unparseable sources — reported "clean" over a tree it never read.
    """
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return path


def _audit(root: Path):
    return audit_tool_runtime(known_capabilities=_KNOWN, agents_dir=root)


class TestDirectToolImports:
    """An agent must not hold a tool object the Gateway never sees."""

    def test_a_tool_implementation_import_is_a_violation(self, tmp_path: Path) -> None:
        _write(tmp_path, "scout.py", "from backend.tools.xhs.trending import xhs_trending\n")
        found = scan_direct_tool_imports(tmp_path)
        assert len(found) == 1
        assert found[0].module == "scout.py"
        assert found[0].line == 1
        assert found[0].imported == "backend.tools.xhs.trending"
        assert not _audit(tmp_path).ok

    def test_a_bare_package_import_is_a_violation(self, tmp_path: Path) -> None:
        """``from backend.tools import xhs`` reaches the same objects."""
        _write(tmp_path, "scout.py", "from backend.tools import xhs\n")
        assert [item.imported for item in scan_direct_tool_imports(tmp_path)] == ["backend.tools"]

    def test_a_plain_import_statement_is_a_violation(self, tmp_path: Path) -> None:
        """``import backend.tools.x`` is the other spelling, same object."""
        _write(tmp_path, "scout.py", "import backend.tools.ripple.integration\n")
        assert [item.imported for item in scan_direct_tool_imports(tmp_path)] == [
            "backend.tools.ripple.integration"
        ]

    def test_violations_in_nested_modules_are_found(self, tmp_path: Path) -> None:
        _write(tmp_path, "nodes/deep.py", "from backend.tools.content.polish import polish\n")
        assert [item.module for item in scan_direct_tool_imports(tmp_path)] == ["nodes/deep.py"]

    def test_runtime_types_are_not_a_violation(self, tmp_path: Path) -> None:
        """Reading a ``ToolResult`` is how a caller learns what happened.

        The rule is "no tool objects", not "no imports from the runtime" —
        the first version of this gate drew the line differently and flagged
        exactly these legitimate imports.
        """
        _write(
            tmp_path,
            "scout.py",
            "from backend.tools.runtime.models import ErrorKind, ToolResult\n"
            "from backend.tools.runtime.gateway import ToolGateway\n",
        )
        assert scan_direct_tool_imports(tmp_path) == ()

    def test_only_base_may_import_the_bridge(self, tmp_path: Path) -> None:
        """The bridge builds ``self.tools``; a second importer is a second door."""
        _write(tmp_path, "base.py", "from backend.tools.runtime.bridge import shared_gateway\n")
        _write(tmp_path, "helper.py", "from backend.tools.runtime.bridge import tracing_to\n")
        found = scan_direct_tool_imports(tmp_path)
        assert [item.module for item in found] == ["helper.py"]

    def test_the_public_scan_matches_the_audit(self, tmp_path: Path) -> None:
        _write(tmp_path, "scout.py", "from backend.tools.xhs.trending import xhs_trending\n")
        assert scan_direct_tool_imports(tmp_path) == _audit(tmp_path).direct_imports


class TestDeclarationAgreement:
    """``tool_capabilities`` and the invocations must say the same thing."""

    _BOTH = """
        class Scout:
            tool_capabilities = ("xhs.trending",)

            async def run(self):
                return await self.tools.invoke("xhs.trending", {})
        """

    def test_a_declared_and_invoked_capability_is_clean(self, tmp_path: Path) -> None:
        _write(tmp_path, "scout.py", self._BOTH)
        audit = _audit(tmp_path)
        assert audit.ok
        assert audit.usages[0].declared == ("xhs.trending",)
        assert audit.usages[0].invoked == ("xhs.trending",)

    def test_invoking_without_declaring_is_a_violation(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "scout.py",
            """
            class Scout:
                async def run(self):
                    return await self.tools.invoke("xhs.trending", {})
            """,
        )
        audit = _audit(tmp_path)
        assert not audit.ok
        assert audit.mismatched[0].undeclared == ("xhs.trending",)

    def test_declaring_without_invoking_is_a_violation(self, tmp_path: Path) -> None:
        """A claim the module does not honour — L1 would describe a dead capability."""
        _write(
            tmp_path,
            "scout.py",
            """
            class Scout:
                tool_capabilities = ("xhs.trending",)
            """,
        )
        audit = _audit(tmp_path)
        assert not audit.ok
        assert audit.mismatched[0].unused == ("xhs.trending",)

    def test_repeated_invocations_are_deduplicated(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "scout.py",
            """
            class Scout:
                tool_capabilities = ("xhs.trending",)

                async def run(self):
                    first = await self.tools.invoke("xhs.trending", {})
                    second = await self.tools.invoke("xhs.trending", {})
                    return first, second
            """,
        )
        assert _audit(tmp_path).usages[0].invoked == ("xhs.trending",)

    def test_a_module_without_tools_is_not_listed(self, tmp_path: Path) -> None:
        """Most of ``backend/agents`` never touches a tool; listing it would bury the rest."""
        _write(
            tmp_path,
            "planner.py",
            """
            class Planner:
                async def run(self):
                    return self.model.invoke("hello")
            """,
        )
        assert scan_agent_tool_usage(tmp_path)[0] == ()
        assert _audit(tmp_path).ok


class TestUnreadableCallsAreFailures:
    """A gate that silently skips what it cannot parse reports false passes."""

    def test_a_non_literal_capability_is_reported(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "scout.py",
            """
            class Scout:
                tool_capabilities = ("xhs.trending",)

                async def run(self, capability):
                    return await self.tools.invoke(capability, {})
            """,
        )
        audit = _audit(tmp_path)
        assert not audit.ok
        assert len(audit.unreadable) == 1
        assert audit.unreadable[0].module == "scout.py"
        assert "not a string literal" in audit.unreadable[0].reason
        # Both halves are true and both are reported: the call could not be
        # read, and the declaration therefore matched no invocation.
        assert audit.mismatched[0].unused == ("xhs.trending",)

    def test_a_non_literal_declaration_is_reported(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "scout.py",
            """
            NAMES = ["xhs.trending"]

            class Scout:
                tool_capabilities = tuple(NAMES)
            """,
        )
        audit = _audit(tmp_path)
        assert not audit.ok
        assert "tool_capabilities" in audit.unreadable[0].reason

    def test_an_invoke_without_arguments_is_reported(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "scout.py",
            """
            class Scout:
                async def run(self):
                    return await self.tools.invoke()
            """,
        )
        assert not _audit(tmp_path).ok

    def test_a_source_that_does_not_parse_is_reported(self, tmp_path: Path) -> None:
        """Skipping it prints a clean run over a tree nobody read."""
        _write(tmp_path, "broken.py", "def run(:\n")
        audit = _audit(tmp_path)
        assert not audit.ok
        assert audit.unreadable[0].module == "broken.py"
        assert audit.unreadable[0].reason == "source does not parse"


class TestCatalogueCoverage:
    """Same split as the prompt-coverage gate: unknown fails, orphan reports."""

    def test_a_capability_absent_from_the_catalogue_fails(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "scout.py",
            """
            class Scout:
                tool_capabilities = ("xhs.telepathy",)

                async def run(self):
                    return await self.tools.invoke("xhs.telepathy", {})
            """,
        )
        audit = _audit(tmp_path)
        assert not audit.ok
        assert audit.unknown == ("xhs.telepathy",)

    def test_an_orphan_is_reported_but_does_not_fail(self, tmp_path: Path) -> None:
        _write(
            tmp_path,
            "scout.py",
            """
            class Scout:
                tool_capabilities = ("xhs.trending",)

                async def run(self):
                    return await self.tools.invoke("xhs.trending", {})
            """,
        )
        audit = _audit(tmp_path)
        assert audit.ok
        assert audit.orphans == ("xhs.publish",)


class TestTheRealAgentLayer:
    """Run against ``backend/agents`` itself — the reason the gate exists."""

    def _audit_repo(self):
        return audit_tool_runtime(known_capabilities=build_registry().capabilities())

    def test_the_agent_layer_is_clean(self) -> None:
        audit = self._audit_repo()
        assert audit.direct_imports == ()
        assert audit.unreadable == ()
        assert audit.unknown == ()
        assert audit.ok

    def test_only_the_four_tool_users_are_listed(self) -> None:
        listed = {usage.module for usage in self._audit_repo().usages}
        assert listed == {
            "analyst.py",
            "content_strategist.py",
            "copywriter.py",
            "trend_scout.py",
        }

    def test_every_declared_capability_matches_its_invocations(self) -> None:
        for usage in self._audit_repo().usages:
            assert usage.ok, f"{usage.module}: undeclared={usage.undeclared} unused={usage.unused}"

    def test_the_only_orphan_is_the_publisher(self) -> None:
        """``xhs.publish`` has no agent caller until P2a.

        Pinned deliberately: when P2a wires a publisher, this test fails and
        the orphan list gets revisited instead of quietly growing.
        """
        assert self._audit_repo().orphans == ("xhs.publish",)

    def test_the_default_directory_is_the_agents_package(self) -> None:
        assert DEFAULT_AGENTS_DIR.name == "agents"
        assert (DEFAULT_AGENTS_DIR / "base.py").is_file()
