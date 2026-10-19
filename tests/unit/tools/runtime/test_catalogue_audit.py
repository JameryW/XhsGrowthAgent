"""Catalogue completeness — every tool is either reachable or written down.

The audit answers one question from the tree alone: **is there a ``@tool``
nobody has decided about?** Before it, the answer was "yes, nineteen of them,
and nobody knew which could write".
"""

from __future__ import annotations

from pathlib import Path

from backend.tools.runtime.audit import (
    PLATFORM_WRITE,
    UNGATED_TOOLS,
    audit_tool_catalogue,
    scan_catalogue_refs,
    scan_function_refs,
    scan_tool_functions,
)


class TestTheRealTree:
    """Run against ``backend/tools`` and ``catalog.py`` — the reason it exists."""

    def test_every_tool_is_classified(self):
        report = audit_tool_catalogue()
        assert report.unclassified == (), (
            "a new @tool must be registered in the catalogue or declared in UNGATED_TOOLS "
            f"with what it can do; unclassified: {report.unclassified}"
        )

    def test_no_declaration_outlived_its_tool(self):
        report = audit_tool_catalogue()
        assert report.stale == (), f"a name that no longer resolves: {report.stale}"

    def test_the_audit_is_clean(self):
        assert audit_tool_catalogue().ok

    def test_no_platform_write_stays_outside_the_catalogue(self):
        # §4.1 of the upgrade note turned on this number while the two manual
        # engagement tools were unregistered doors. 票 5f moved them into the
        # catalogue (Gateway + Effect ledger + approval gate), so the ungated
        # platform-write surface is now empty -- and an unregistered platform
        # write arriving again is exactly the regression this pins.
        report = audit_tool_catalogue()
        assert report.platform_writes == ()

    def test_the_catalogue_only_names_functions_that_exist(self):
        report = audit_tool_catalogue()
        missing = sorted(set(report.registered) - set(report.functions))
        assert missing == [], f"catalogue points at absent functions: {missing}"

    def test_registered_capabilities_are_not_all_decorated_tools(self):
        # Five registered refs are plain callables, not LangChain tools. A
        # scanner that looked only at ``@tool`` would call them stale; the two
        # scans must stay distinct for that reason.
        report = audit_tool_catalogue()
        plain = set(report.registered) - set(report.decorated)
        assert plain == {
            "backend.tools.content.de_ai_taste:algorithmic_de_ai",
            "backend.tools.content.de_ai_taste:polish_copy",
            "backend.tools.ripple.integration:get_report",
            "backend.tools.ripple.integration:predict_spread",
            "backend.tools.ripple.integration:validate_pmf",
        }

    def test_the_catalogue_is_read_from_literals(self):
        refs = scan_catalogue_refs()
        assert "backend.tools.xhs.publisher:xhs_publisher" in refs
        assert len(refs) >= 12

    def test_declared_tools_carry_what_they_can_do(self):
        # An empty note would turn the table into a list of names and the
        # classification into a formality.
        assert all(item.note.strip() for item in UNGATED_TOOLS)
        kinds = {item.kind for item in UNGATED_TOOLS}
        # 票 5f: the platform writes are registered now, so none may linger
        # ungated. A PLATFORM_WRITE entry reappearing here means a new door
        # to the platform opened outside the catalogue.
        assert PLATFORM_WRITE not in kinds


def _write(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


TOOL = """
from langchain_core.tools import tool


@tool
def {name}() -> str:
    \"\"\"{name}.\"\"\"
    return "{name}"
"""


class TestPositiveControls:
    """The gate must fail on the shapes it claims to catch."""

    def _audit(self, root: Path, catalogue: Path):
        # ``declared=()``: a temporary tree must not inherit this repo's table,
        # otherwise every real declaration would report as stale.
        return audit_tool_catalogue(root / "backend/tools", catalogue, declared=())

    def test_a_registered_tool_is_clean(self, tmp_path: Path):
        _write(tmp_path, "backend/tools/xhs/one.py", TOOL.format(name="one"))
        catalogue = _write(
            tmp_path,
            "backend/tools/runtime/catalog.py",
            'X = tool_ref("backend.tools.xhs.one:one")\n',
        )
        assert self._audit(tmp_path, catalogue).ok

    def test_a_new_tool_without_a_decision_is_unclassified(self, tmp_path: Path):
        _write(tmp_path, "backend/tools/xhs/one.py", TOOL.format(name="one"))
        catalogue = _write(
            tmp_path,
            "backend/tools/runtime/catalog.py",
            'X = tool_ref("backend.tools.xhs.one:one")\n',
        )
        _write(tmp_path, "backend/tools/xhs/two.py", TOOL.format(name="two"))
        report = self._audit(tmp_path, catalogue)
        assert report.unclassified == ("backend.tools.xhs.two:two",)
        assert not report.ok

    def test_a_registered_tool_that_vanished_is_stale(self, tmp_path: Path):
        _write(tmp_path, "backend/tools/xhs/one.py", TOOL.format(name="one"))
        catalogue = _write(
            tmp_path,
            "backend/tools/runtime/catalog.py",
            'X = tool_ref("backend.tools.xhs.gone:gone")\n',
        )
        report = self._audit(tmp_path, catalogue)
        assert report.stale == ("backend.tools.xhs.gone:gone",)
        assert not report.ok

    def test_a_plain_callable_can_be_registered_too(self, tmp_path: Path):
        _write(
            tmp_path,
            "backend/tools/content/plain.py",
            "def polish() -> str:\n    return 'x'\n",
        )
        catalogue = _write(
            tmp_path,
            "backend/tools/runtime/catalog.py",
            'X = tool_ref("backend.tools.content.plain:polish")\n',
        )
        report = self._audit(tmp_path, catalogue)
        assert report.stale == ()
        assert report.decorated == ()

    def test_a_file_that_does_not_parse_is_unreadable_not_clean(self, tmp_path: Path):
        _write(tmp_path, "backend/tools/xhs/broken.py", "def f(:\n")
        catalogue = _write(tmp_path, "backend/tools/runtime/catalog.py", "")
        report = self._audit(tmp_path, catalogue)
        assert report.unreadable
        assert not report.ok

    def test_both_scanners_agree_on_the_decorated_subset(self, tmp_path: Path):
        _write(
            tmp_path,
            "backend/tools/xhs/mixed.py",
            "def helper() -> str:\n    return 'x'\n" + TOOL.format(name="real"),
        )
        assert scan_tool_functions(tmp_path / "backend/tools") == ("backend.tools.xhs.mixed:real",)
        assert scan_function_refs(tmp_path / "backend/tools") == (
            "backend.tools.xhs.mixed:helper",
            "backend.tools.xhs.mixed:real",
        )
