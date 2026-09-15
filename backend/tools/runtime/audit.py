"""Static audit of how the agent layer reaches the Tool Runtime (P1c-S5).

Three questions, all answerable from the sources alone:

* **Does any agent module import a tool behind the runtime's back?** Agents
  may import the runtime itself (``backend.tools.runtime.**`` — the types
  they need to read a ``ToolResult``), but a tool *implementation*
  (``backend.tools.xhs.trending`` and friends) hands out an object the
  Gateway never sees. The bridge that builds ``self.tools`` is narrower
  still: only ``backend/agents/base.py`` may import it, so "did this agent
  bypass the runtime?" stays an AST question instead of a review question.
* **Does each agent's ``tool_capabilities`` declaration agree with the
  capability literals it actually passes to ``self.tools.invoke``?** Both
  directions matter. An invocation nobody declared reaches a tool the agent
  never said it needs (and, once L1 is on, one the model is never told
  about); a declaration nobody invokes makes L1 describe a capability the
  agent does not use.
* **Is every capability an agent names present in the catalogue?**

AST, not import: reading agent modules executes their imports and any
module-level wiring, which a gate must never do — the same rule
``backend.context.baseline.scan_declared_prompts`` follows for prompt YAML.

A call this audit cannot read is reported, never skipped. Reporting "0
mismatches" over code the gate never understood is a false pass, and a false
pass is worse than a loud failure.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_AGENTS_DIR",
    "AgentToolUsage",
    "DirectToolImport",
    "ToolRuntimeAudit",
    "UnreadableInvocation",
    "audit_tool_runtime",
    "scan_agent_tool_usage",
    "scan_direct_tool_imports",
]

DEFAULT_AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"
"""``backend/agents``, resolved from this file so callers need pass nothing."""

_RUNTIME_ROOT = "backend.tools"
_RUNTIME_PACKAGE = "backend.tools.runtime"
_ALLOWED_BRIDGE = "backend.tools.runtime.bridge"
_ALLOWED_BRIDGE_MODULES = ("base.py",)
"""Only ``base.py`` may import the bridge — it owns the ``tools`` property.

Every other agent reaches a tool through ``self.tools``. A second import is a
second door, and the point of this gate is that there is exactly one.
"""

_ALLOWED_PREFIX = f"{_RUNTIME_PACKAGE}."
"""Agents may import the runtime itself; they may not import a tool.

``backend.tools.runtime.**`` is the Registry, the Gateway, the result models
and the bridge — types and machinery that *describe* how a tool runs while
handing out no tool. Every other ``backend.tools.**`` module is a tool
implementation, and importing one is exactly the bypass P1c-S3 spent five
slices removing: it yields an object the Gateway never sees, so timeout /
retry / scope / tracing stop applying without a single test noticing.

This boundary was not drawn correctly the first time. The initial version
allowed only the bridge and immediately flagged three legitimate imports —
``ErrorKind`` / ``ToolResult`` for reading Gateway results, ``ToolGateway``
inside a ``TYPE_CHECKING`` block. That is the gate working on its own author:
the rule now names the thing that actually matters ("no tool objects") and
the false positives are gone.
"""


@dataclass(frozen=True)
class DirectToolImport:
    """One agent module importing ``backend.tools`` outside the seam."""

    module: str
    line: int
    imported: str

    def __str__(self) -> str:
        return f"{self.module}:{self.line} imports {self.imported}"


@dataclass(frozen=True)
class UnreadableInvocation:
    """A gateway call this audit could not read — counted as a failure.

    The shapes it knows are ``<x>.tools.invoke("<literal>", ...)`` and
    ``tool_capabilities = ("<literal>", ...)``. Anything else is surfaced
    here instead of being quietly left out of the comparison.
    """

    module: str
    line: int
    reason: str

    def __str__(self) -> str:
        return f"{self.module}:{self.line} {self.reason}"


@dataclass(frozen=True)
class AgentToolUsage:
    """What one agent module declares vs what it invokes."""

    module: str
    declared: tuple[str, ...]
    invoked: tuple[str, ...]

    @property
    def undeclared(self) -> tuple[str, ...]:
        """Invoked without being declared — the runtime cannot describe it."""
        return tuple(name for name in self.invoked if name not in self.declared)

    @property
    def unused(self) -> tuple[str, ...]:
        """Declared but never invoked — a claim the module does not honour."""
        return tuple(name for name in self.declared if name not in self.invoked)

    @property
    def ok(self) -> bool:
        return not self.undeclared and not self.unused

    def to_dict(self) -> dict[str, Any]:
        return {
            "module": self.module,
            "declared": list(self.declared),
            "invoked": list(self.invoked),
            "undeclared": list(self.undeclared),
            "unused": list(self.unused),
        }


@dataclass(frozen=True)
class ToolRuntimeAudit:
    """The whole audit: bypasses, unreadable calls, mismatches, coverage."""

    agents_dir: Path
    modules: tuple[str, ...]
    direct_imports: tuple[DirectToolImport, ...]
    unreadable: tuple[UnreadableInvocation, ...]
    usages: tuple[AgentToolUsage, ...]
    unknown: tuple[str, ...]
    orphans: tuple[str, ...]

    @property
    def mismatched(self) -> tuple[AgentToolUsage, ...]:
        """Modules whose declaration and invocations disagree."""
        return tuple(usage for usage in self.usages if not usage.ok)

    @property
    def ok(self) -> bool:
        """Unknown names and orphans are reported, not failed (see below)."""
        return not (self.mismatched or self.direct_imports or self.unreadable or self.unknown)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "agents_dir": str(self.agents_dir),
            "modules": list(self.modules),
            "direct_imports": [str(item) for item in self.direct_imports],
            "unreadable": [str(item) for item in self.unreadable],
            "usages": [usage.to_dict() for usage in self.usages],
            "unknown": list(self.unknown),
            "orphans": list(self.orphans),
        }


def _parse_sources(
    agents_dir: Path,
) -> tuple[list[tuple[str, ast.Module]], list[UnreadableInvocation]]:
    """``(relative name, tree)`` for every source, plus anything unparseable.

    An unparseable file is reported rather than skipped. CI would fail on its
    import a moment later anyway, but by then this gate has already printed a
    clean run over a tree it never actually read — the one outcome it must
    never produce. (Found the hard way: a test fixture with bad indentation
    was dropped here silently and the gate still reported "clean", which is
    how the fixture bug reached a test run at all.)
    """
    parsed: list[tuple[str, ast.Module]] = []
    failures: list[UnreadableInvocation] = []
    for path in sorted(agents_dir.rglob("*.py")):
        relative = path.relative_to(agents_dir).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            failures.append(
                UnreadableInvocation(
                    module=relative, line=exc.lineno or 0, reason="source does not parse"
                )
            )
            continue
        parsed.append((relative, tree))
    return parsed, failures


def _runtime_import(node: ast.AST) -> Iterable[tuple[str, int]]:
    """The ``backend.tools`` module paths one import statement names, with line.

    The line comes back together with the module name because ``ast.walk``
    hands out base ``AST`` nodes, which have no ``lineno``; narrowing happens
    here, where the node type is already known.
    """
    if isinstance(node, ast.ImportFrom):
        if node.module and (
            node.module == _RUNTIME_ROOT or node.module.startswith(f"{_RUNTIME_ROOT}.")
        ):
            yield node.module, node.lineno
        return
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.name == _RUNTIME_ROOT or alias.name.startswith(f"{_RUNTIME_ROOT}."):
                yield alias.name, node.lineno


def _is_sanctioned(relative: str, imported: str) -> bool:
    """Whether one agent module may import one ``backend.tools`` module."""
    if imported == _ALLOWED_BRIDGE:
        return relative in _ALLOWED_BRIDGE_MODULES
    return imported == _RUNTIME_PACKAGE or imported.startswith(_ALLOWED_PREFIX)


def _direct_tool_imports(
    parsed: Sequence[tuple[str, ast.Module]],
) -> tuple[DirectToolImport, ...]:
    """Direct-import violations across already-parsed sources."""
    found: list[DirectToolImport] = []
    for relative, tree in parsed:
        for node in ast.walk(tree):
            for imported, line in _runtime_import(node):
                if _is_sanctioned(relative, imported):
                    continue
                found.append(DirectToolImport(module=relative, line=line, imported=imported))
    return tuple(found)


def scan_direct_tool_imports(
    agents_dir: Path | str = DEFAULT_AGENTS_DIR,
) -> tuple[DirectToolImport, ...]:
    """Every ``backend.tools`` import under ``agents_dir`` outside the surface.

    Both spellings count — ``import backend.tools.x`` and
    ``from backend.tools.x import y`` — because either one gives a module a
    tool object that no Gateway ever sees.

    Only import violations come back. A source that cannot be parsed is
    invisible to this scan and is reported by ``audit_tool_runtime`` instead.
    """
    return _direct_tool_imports(_parse_sources(Path(agents_dir))[0])


def _is_gateway_invoke(call: ast.Call) -> bool:
    """Whether ``call`` is ``<something>.tools.invoke(...)``.

    Deliberately shape-based rather than object-based: this runs without
    importing anything, so it cannot ask what ``tools`` is. It also has to
    accept ``self.tools`` without insisting on the name ``self``, since a
    helper may hold the agent under another name.
    """
    func = call.func
    if not isinstance(func, ast.Attribute) or func.attr != "invoke":
        return False
    owner = func.value
    return isinstance(owner, ast.Attribute) and owner.attr == "tools"


def _literal_capability(call: ast.Call) -> str | None:
    """The capability a call names, if it is written as a string literal."""
    if not call.args:
        return None
    first = call.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def _declaration_node(tree: ast.Module) -> ast.expr | None:
    """The value assigned to ``tool_capabilities`` anywhere in ``tree``."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "tool_capabilities"
            for target in node.targets
        ):
            return node.value
    return None


def _literal_str_tuple(node: ast.expr) -> tuple[str, ...] | None:
    """A tuple/list of string literals, or ``None`` if it is anything else."""
    if not isinstance(node, (ast.Tuple, ast.List)):
        return None
    out: list[str] = []
    for element in node.elts:
        if not (isinstance(element, ast.Constant) and isinstance(element.value, str)):
            return None
        out.append(element.value)
    return tuple(out)


def _agent_tool_usage(
    parsed: Sequence[tuple[str, ast.Module]],
) -> tuple[tuple[AgentToolUsage, ...], tuple[UnreadableInvocation, ...]]:
    """Declarations vs invocations across already-parsed sources."""
    usages: list[AgentToolUsage] = []
    unreadable: list[UnreadableInvocation] = []
    for relative, tree in parsed:
        declared: tuple[str, ...] = ()
        declaration = _declaration_node(tree)
        if declaration is not None:
            # Deliberately not named ``parsed``: that one holds the sources
            # this loop iterates. Rebinding it here would still work — the
            # iterator is created before the first assignment — which is
            # exactly why the name collision is worth refusing.
            names = _literal_str_tuple(declaration)
            if names is None:
                unreadable.append(
                    UnreadableInvocation(
                        module=relative,
                        line=declaration.lineno,
                        reason="tool_capabilities is not a tuple of string literals",
                    )
                )
            else:
                declared = names

        invoked: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_gateway_invoke(node):
                continue
            capability = _literal_capability(node)
            if capability is None:
                unreadable.append(
                    UnreadableInvocation(
                        module=relative,
                        line=node.lineno,
                        reason="gateway invoke capability is not a string literal",
                    )
                )
            else:
                invoked.append(capability)

        if not declared and not invoked:
            continue
        usages.append(
            AgentToolUsage(
                module=relative,
                declared=tuple(dict.fromkeys(declared)),
                invoked=tuple(dict.fromkeys(invoked)),
            )
        )
    return tuple(usages), tuple(unreadable)


def scan_agent_tool_usage(
    agents_dir: Path | str = DEFAULT_AGENTS_DIR,
) -> tuple[tuple[AgentToolUsage, ...], tuple[UnreadableInvocation, ...]]:
    """Per-module declarations vs invocations, plus whatever could not be read.

    Modules that neither declare nor invoke anything are left out: most of
    ``backend/agents`` never touches a tool, and listing them would bury the
    four that do.
    """
    parsed, failures = _parse_sources(Path(agents_dir))
    usages, unreadable = _agent_tool_usage(parsed)
    return usages, (*failures, *unreadable)


def audit_tool_runtime(
    *,
    known_capabilities: Sequence[str],
    agents_dir: Path | str = DEFAULT_AGENTS_DIR,
) -> ToolRuntimeAudit:
    """Run every check against ``agents_dir``.

    ``known_capabilities`` is the catalogue's name list, passed in rather than
    imported: keeping this module import-free lets the gate run against any
    tree (tests hand it a temporary one), and means a catalogue that fails to
    build cannot take the gate down with it.

    ``unknown`` (named by an agent, absent from the catalogue) fails the gate.
    ``orphans`` (in the catalogue, used by no agent) is reported only — the
    same split the prompt-coverage gate draws, and for the same reason:
    ``xhs.publish`` has no caller until P2a, and a gate that fails on planned
    work gets switched off.
    """
    root = Path(agents_dir)
    parsed, failures = _parse_sources(root)
    usages, unreadable = _agent_tool_usage(parsed)
    named = {name for usage in usages for name in (*usage.declared, *usage.invoked)}
    known = set(known_capabilities)
    return ToolRuntimeAudit(
        agents_dir=root,
        modules=tuple(relative for relative, _ in parsed),
        direct_imports=_direct_tool_imports(parsed),
        unreadable=(*failures, *unreadable),
        usages=usages,
        unknown=tuple(sorted(named - known)),
        orphans=tuple(sorted(known - named)),
    )
