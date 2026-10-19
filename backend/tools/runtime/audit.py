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
    "CATALOGUE_PATH",
    "DEFAULT_AGENTS_DIR",
    "TOOLS_ROOT",
    "UNGATED_TOOLS",
    "AgentToolUsage",
    "CatalogueAudit",
    "DirectToolImport",
    "SilentFallback",
    "ToolRuntimeAudit",
    "UngatedTool",
    "UnreadableInvocation",
    "audit_tool_catalogue",
    "audit_tool_runtime",
    "scan_agent_tool_usage",
    "scan_catalogue_refs",
    "scan_direct_tool_imports",
    "scan_function_refs",
    "scan_silent_fallbacks",
    "scan_tool_functions",
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


# ── Catalogue completeness: what can write outside, and is it behind the Gateway? ──

TOOLS_ROOT = Path(__file__).resolve().parents[1]
"""``backend/tools`` — every tool implementation, registered or not."""

CATALOGUE_PATH = Path(__file__).resolve().parent / "catalog.py"
"""The declaration file. Its ``tool_ref("...")`` literals are the register."""

#: An unregistered tool that writes to **the XHS platform**. This is the class
#: §4.1 of the upgrade note is about: a second one reaching an agent would make
#: node-internal retries able to repeat a real-world action.
PLATFORM_WRITE = "platform_write"
#: Writes to a service of ours (Ripple), not to the platform.
SERVICE_WRITE = "service_write"
#: Sends a notification outside the process (webhook).
NOTIFICATION = "notification"
#: Returns a canned success payload and touches nothing — a stub. The danger is
#: not the tool, it is a later reader assuming the stub already works.
STUB = "stub"
#: Reads only.
READ_ONLY = "read_only"
#: Left in the tree but superseded by a registered capability.
SUPERSEDED = "superseded"


@dataclass(frozen=True)
class UngatedTool:
    """A ``@tool`` the catalogue does not know about, with what it can do.

    The catalogue is the set of capabilities an agent may reach. A tool outside
    it is not automatically wrong (``backend/tools`` holds every implementation,
    including ones no agent should ever call), but it *is* a door: importing it
    hands out an object the Gateway never sees. This table is the deliberate
    classification of those doors — the audit fails when a new one appears
    without an entry, so the surface cannot grow by accident.
    """

    ref: str
    kind: str
    note: str


UNGATED_TOOLS: tuple[UngatedTool, ...] = (
    UngatedTool(
        "backend.tools.xhs.engagement:escalation_flagger",
        NOTIFICATION,
        "人工升级标记；配置了 webhook 时会向外部发通知，不写平台",
    ),
    UngatedTool(
        "backend.tools.xhs.engagement:fetch_pending_comments",
        READ_ONLY,
        "读取待处理评论。空列表只表示'读到了、确实没有'：无身份与读失败都抛"
        "（`require_readable` + `get_comments` 不再吞异常），见 "
        "`scan_silent_fallbacks`",
    ),
    UngatedTool(
        "backend.tools.xhs.publisher:post_scheduler",
        STUB,
        "只返回 canned 结果（注释写明需接 APScheduler）。**若实现真实调度，"
        "必须迁入目录并声明 SIDE_EFFECTING**",
    ),
    UngatedTool(
        "backend.tools.xhs.publisher:ab_test_manager",
        STUB,
        "只返回 canned 配置，不触达平台",
    ),
    UngatedTool(
        "backend.tools.xhs.analytics:report_generator",
        READ_ONLY,
        "只读 creator_stats 并拼文本，无写入",
    ),
    UngatedTool(
        "backend.tools.xhs.analytics:analytics_reader",
        READ_ONLY,
        "读平台分析数据",
    ),
    UngatedTool(
        "backend.tools.xhs.analytics:pattern_detector",
        READ_ONLY,
        "读平台分析数据",
    ),
    UngatedTool(
        "backend.tools.ripple.client:ripple_cancel_simulation",
        SERVICE_WRITE,
        "取消 Ripple 服务上的任务（改的是本仓服务的状态，不是平台）",
    ),
    UngatedTool(
        "backend.tools.ripple.client:ripple_generate_report",
        SERVICE_WRITE,
        "在 Ripple 服务上生成报告",
    ),
    UngatedTool(
        "backend.tools.ripple.client:ripple_get_simulation_status",
        READ_ONLY,
        "低层 client 包装；目录走 ripple.integration 的三个能力",
    ),
    UngatedTool(
        "backend.tools.ripple.client:ripple_get_simulation_result",
        READ_ONLY,
        "同上",
    ),
    UngatedTool(
        "backend.tools.ripple.client:ripple_get_simulation_log",
        READ_ONLY,
        "同上",
    ),
    UngatedTool(
        "backend.tools.ripple.client:ripple_predict_content_spread",
        READ_ONLY,
        "同上；目录里对应 ripple.predict_spread",
    ),
    UngatedTool(
        "backend.tools.ripple.client:ripple_validate_pmf",
        READ_ONLY,
        "同上；目录里对应 ripple.validate_pmf",
    ),
    UngatedTool(
        "backend.tools.content.de_ai_taste:de_ai_taste",
        SUPERSEDED,
        "旧单入口；目录拆成 algorithmic_de_ai / polish_copy 两个能力",
    ),
    UngatedTool(
        "backend.tools.content.layout:layout_recommender",
        READ_ONLY,
        "无导入者；纯本地推荐，无外部 I/O",
    ),
    UngatedTool(
        "backend.tools.content.style:style_library",
        READ_ONLY,
        "无导入者；纯本地样式库",
    ),
)


@dataclass(frozen=True)
class CatalogueAudit:
    """Every tool in the tree, sorted into registered / declared / unknown."""

    functions: tuple[str, ...]
    """Every module-level function — the set a ``tool_ref`` may resolve to."""
    decorated: tuple[str, ...]
    """The ``@tool`` subset: what an agent could import as a callable."""
    registered: tuple[str, ...]
    declared: tuple[str, ...]
    unclassified: tuple[str, ...]
    """A ``@tool`` that is neither registered nor declared — the failure."""
    stale: tuple[str, ...]
    """Named by the catalogue or the table, but absent from the tree."""
    platform_writes: tuple[str, ...]
    """Unregistered tools that write to the platform (the §4.1 set)."""
    unreadable: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.unclassified and not self.stale and not self.unreadable

    def to_dict(self) -> dict[str, Any]:
        return {
            "functions": list(self.functions),
            "decorated": list(self.decorated),
            "registered": list(self.registered),
            "declared": list(self.declared),
            "unclassified": list(self.unclassified),
            "stale": list(self.stale),
            "platform_writes": list(self.platform_writes),
            "unreadable": list(self.unreadable),
        }


def _module_ref(path: Path) -> str:
    """``.../backend/tools/xhs/engagement.py`` → ``backend.tools.xhs.engagement``."""
    parts = list(path.with_suffix("").parts)
    if "backend" not in parts:
        raise ValueError(f"{path}: not under a 'backend' package")
    return ".".join(parts[parts.index("backend") :])


def _is_tool_decorated(node: ast.AST) -> bool:
    """Whether ``node`` is a function carrying a ``@tool`` decorator.

    ``@tool``, ``@tool(...)`` and ``@lc_tool(...)`` all count: the decorator is
    read by its *name*, which is what ``_scan_defs`` did before this helper
    existed. Kept as one function so the catalogue scan and the fallback scan
    cannot disagree about what a tool is.
    """
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = getattr(target, "id", None) or getattr(target, "attr", None)
        if name == "tool":
            return True
    return False


def _scan_defs(root: Path | str, *, only_tool: bool) -> tuple[str, ...]:
    """Every module-level-ish ``def`` under ``root``, optionally ``@tool`` only.

    AST, for the reason the rest of this module is AST: importing the tree runs
    module-level wiring, and a gate must never do that.
    """
    refs: list[str] = []
    for path in sorted(Path(root).rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            # Surfaced by the caller as unreadable rather than skipped: a gate
            # that reports "clean" over a file it could not parse is a lie.
            raise
        module = _module_ref(path)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if only_tool and not _is_tool_decorated(node):
                continue
            refs.append(f"{module}:{node.name}")
    return tuple(sorted(set(refs)))


def scan_function_refs(root: Path | str = TOOLS_ROOT) -> tuple[str, ...]:
    """Every function a ``tool_ref`` could resolve to, as ``module:function``.

    The catalogue does not only bind LangChain tools: ``content.algorithmic_de_ai``
    and ``content.polish_copy`` are plain callables reached with ``PassStyle.KWARGS``.
    Scanning ``@tool`` alone would call those two "stale" — a false alarm that
    would have taught the next reader to ignore the gate.
    """
    return _scan_defs(root, only_tool=False)


def scan_tool_functions(root: Path | str = TOOLS_ROOT) -> tuple[str, ...]:
    """The ``@tool``-decorated subset — what an agent could import directly."""
    return _scan_defs(root, only_tool=True)


@dataclass(frozen=True)
class SilentFallback:
    """A ``@tool`` that answers a raised exception with a written-down value.

    The tell is the *literal*. ``return []`` says "the platform had no
    comments"; ``return {"heat_score": 50, ...}`` says "heat is 50". Both are
    transcription, not measurement — the handler was reached because the call
    failed, so the value it hands back cannot be an answer to the question that
    was asked. A handler returning a *name* or a *call* is not flagged: the
    value came from somewhere, which is a different and inspectable question.
    """

    ref: str
    handler_line: int
    returned: str
    """The literal, unparsed — so a review reads the value, not a verdict."""


_LITERAL = (ast.Constant, ast.List, ast.Dict, ast.Tuple, ast.Set, ast.JoinedStr)


def _literal_returns(handler: ast.ExceptHandler) -> list[ast.Return]:
    """The handler's own ``return <literal>`` statements.

    Nested ``def``/``lambda`` bodies are skipped: a literal returned by a
    function *defined* inside the handler is that function's answer, not the
    handler's. Walking one level matters here because the target shape is
    exactly "handler swallows, wrapper function reports".
    """
    found: list[ast.Return] = []
    stack: list[ast.AST] = list(handler.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Return) and isinstance(node.value, _LITERAL):
            found.append(node)
            continue
        stack.extend(ast.iter_child_nodes(node))
    return found


def _walk_defs(node: ast.AST, prefix: str = "") -> list[tuple[str, ast.AST]]:
    """Every function/method under ``node`` with its dotted qualname.

    Classes contribute a prefix; a function does not — its nested ``def``s are
    closures whose failures belong to the enclosing call, so reporting them
    separately would double-count one fact. The prefix is what keeps two
    classes' ``get_comments`` apart, which is not hypothetical:
    ``backend/services/xhs_client.py`` has exactly that pair.
    """
    found: list[tuple[str, ast.AST]] = []
    for child in ast.iter_child_nodes(node):
        if isinstance(child, ast.ClassDef):
            found.extend(_walk_defs(child, f"{prefix}{child.name}."))
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            found.append((f"{prefix}{child.name}", child))
        else:
            found.extend(_walk_defs(child, prefix))
    return found


def _except_handlers(node: ast.AST) -> list[ast.ExceptHandler]:
    """Handlers belonging to ``node``, not to a function defined inside it."""
    found: list[ast.ExceptHandler] = []
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        current = stack.pop()
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(current, ast.ExceptHandler):
            found.append(current)
        stack.extend(ast.iter_child_nodes(current))
    return found


def scan_silent_fallbacks(
    root: Path | str = TOOLS_ROOT, *, tool_only: bool = True
) -> tuple[SilentFallback, ...]:
    """Every function whose ``except`` hands back a literal.

    ``tool_only`` (the default) restricts the scan to ``@tool`` — the surface an
    agent reads directly. ``False`` widens it to every function under ``root``,
    which is how the *service* layer's remaining instances are counted: those
    are less dangerous (a caller can still inspect, and the tool above may
    enforce its own precondition) but they are the same shape, and an uncounted
    one is the one that comes back.

    The service layer degrades by design in places (``RippleService`` returns a
    zeroed body beside ``ripple_fallback`` for the *integration* layer to
    reject), and those degradations carry a visible sentinel. A literal returned
    from an ``except`` carries nothing: the handler was reached *because* the
    call failed, so the value cannot be an answer to the question asked.
    """
    found: list[SilentFallback] = []
    paths = _python_files(root)
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        module = _module_ref(path)
        for qualname, node in _walk_defs(tree):
            if tool_only and not _is_tool_decorated(node):
                continue
            for handler in _except_handlers(node):
                for ret in _literal_returns(handler):
                    found.append(
                        SilentFallback(
                            ref=f"{module}:{qualname}",
                            handler_line=handler.lineno,
                            returned=ast.unparse(ret.value),  # type: ignore[arg-type]
                        )
                    )
    return tuple(sorted(found, key=lambda item: (item.ref, item.handler_line)))


def _python_files(root: Path | str) -> list[Path]:
    """``root`` may be a tree or a single file — and never silently neither.

    ``Path("backend/x.py").rglob("*.py")`` yields nothing: ``rglob`` treats a
    file as a directory that contains nothing. A scan handed a file would then
    report "clean" over code it never read, which is the one outcome this
    module refuses to produce.
    """
    path = Path(root)
    if path.is_file():
        return [path]
    if not path.is_dir():
        raise FileNotFoundError(f"nothing to scan at {path}")
    return sorted(path.rglob("*.py"))


def scan_catalogue_refs(path: Path | str = CATALOGUE_PATH) -> tuple[str, ...]:
    """The ``tool_ref("module:function")`` literals the catalogue declares.

    Deliberately literal-driven: a capability registered some other way is not
    invisible to the *runtime*, but it is invisible to *this* audit — and the
    tool behind it then shows up as unclassified, which is the loud direction.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    refs: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Name) and node.func.id == "tool_ref"):
            continue
        if node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str):
                refs.append(value)
    return tuple(sorted(set(refs)))


def audit_tool_catalogue(
    tools_root: Path | str = TOOLS_ROOT,
    catalogue_path: Path | str = CATALOGUE_PATH,
    declared: Iterable[UngatedTool] = UNGATED_TOOLS,
) -> CatalogueAudit:
    """Sort every tool into registered / declared / unclassified.

    ``unclassified`` fails the gate: a new ``@tool`` must be either reachable
    through the Gateway or explicitly written down as one that is not, with
    what it can do. ``stale`` fails too — a name in the catalogue or in the
    table that no longer resolves describes a surface that has moved.

    ``declared`` is a parameter (not a closed-over constant) so a temporary
    tree can be audited without inheriting this repository's declarations —
    the same reason ``audit_tool_runtime`` takes ``known_capabilities``.
    """
    try:
        functions = scan_function_refs(tools_root)
        decorated = scan_tool_functions(tools_root)
    except (SyntaxError, UnicodeDecodeError) as exc:
        return CatalogueAudit(
            functions=(),
            decorated=(),
            registered=(),
            declared=tuple(item.ref for item in declared),
            unclassified=(),
            stale=(),
            platform_writes=(),
            unreadable=(f"{tools_root}: {exc}",),
        )

    registered = scan_catalogue_refs(catalogue_path)
    declared_refs = {item.ref for item in declared}
    known = set(registered) | declared_refs
    return CatalogueAudit(
        functions=functions,
        decorated=decorated,
        registered=registered,
        declared=tuple(sorted(declared_refs)),
        unclassified=tuple(ref for ref in decorated if ref not in known),
        stale=tuple(sorted(ref for ref in known if ref not in functions)),
        platform_writes=tuple(sorted(item.ref for item in declared if item.kind == PLATFORM_WRITE)),
    )
