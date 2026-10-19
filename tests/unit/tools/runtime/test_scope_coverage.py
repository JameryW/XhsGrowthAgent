"""How much of the declared auth_scope surface is actually applied.

The Gateway's scope check is *opt-in* (:meth:`ToolGateway._check_scopes`):
``granted_scopes=None`` means "not checked here", not "denied". So a capability
can declare ``auth_scope`` and be reachable from a call site that never passes
one — the declaration then costs nothing and looks like protection.

This file turns that sentence into numbers, recomputed from the tree: which
capabilities declare a scope, which literal ``.invoke(...)`` call sites check
it, and which do not. It is a **ratchet**, not an endorsement — every set below
is today's state, and any change (a new capability, a new unchecked call site, a
site that starts passing scopes) fails here until the register and
``docs/tool-gateway-engagement-migration.md`` §9.6 are updated together.

Why it exists: eight of twelve capabilities declare a scope, and when this file
was written exactly one call site applied one. That was invisible until this file
counted it.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from backend.tools.runtime.catalog import build_registry

REPO = Path(__file__).resolve().parents[4]
BACKEND = REPO / "backend"

# Recomputed from ``build_registry()`` -- declared, whether or not anyone applies it.
DECLARED_SCOPES: dict[str, tuple[str, ...]] = {
    "analysis.topic_scorer": ("xhs:read",),
    "ripple.get_report": ("ripple:read",),
    "ripple.predict_spread": ("ripple:read",),
    "ripple.validate_pmf": ("ripple:read",),
    "xhs.competitor_analyzer": ("xhs:read",),
    "xhs.keyword_monitor": ("xhs:read",),
    "xhs.publish": ("xhs:write",),
    "xhs.trending": ("xhs:read",),
}

# The places a capability is invoked *with* its requirement applied. Both
# publish paths: the control plane (an action the user confirmed) and the
# mainline (a workflow run). Two paths, one rule.
CHECKED_CALL_SITES: dict[str, tuple[str, ...]] = {
    "xhs.publish": (
        "backend/agents/publisher.py",
        "backend/creator_agent/execution.py",
    ),
}

# The debt: invocation sites that pass no ``granted_scopes``. Ordered so a new
# one is an obvious diff rather than a silent widening.
UNCHECKED_CALL_SITES: dict[str, tuple[str, ...]] = {
    "analysis.topic_scorer": ("backend/agents/content_strategist.py",),
    "content.algorithmic_de_ai": ("backend/agents/copywriter.py",),
    "content.polish_copy": ("backend/agents/copywriter.py",),
    "ripple.get_report": ("backend/agents/analyst.py",),
    "ripple.predict_spread": ("backend/agents/content_strategist.py",),
    "ripple.validate_pmf": ("backend/agents/content_strategist.py",),
    "search.fetch": ("backend/agents/trend_scout.py",),
    "search.web": ("backend/agents/trend_scout.py",),
    "xhs.competitor_analyzer": ("backend/agents/trend_scout.py",),
    "xhs.keyword_monitor": ("backend/agents/trend_scout.py",),
    "xhs.trending": ("backend/agents/trend_scout.py",),
}


@dataclass(frozen=True)
class CallSite:
    file: str
    capability: str
    checks_scopes: bool


def _module_constants(tree: ast.Module) -> dict[str, str]:
    """``PUBLISH_CAPABILITY = "xhs.publish"`` → ``{"PUBLISH_CAPABILITY": ...}``.

    Needed because the one site that *does* check scopes names its capability
    through a module constant. A literal-only scan would report that capability
    as entirely unchecked — under-reporting coverage is how the gap would look
    bigger than it is, which is its own kind of wrong answer.
    """
    constants: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Name)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            ):
                constants[target.id] = node.value.value
    return constants


def _capability_of(node: ast.Call, constants: dict[str, str]) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        value = first.value
    elif isinstance(first, ast.Name):
        value = constants.get(first.id, "")
    else:
        return None
    # A capability id is dotted; this also filters out ``.invoke(method_name)``.
    return value if "." in value else None


def _call_sites() -> list[CallSite]:
    sites: list[CallSite] = []
    for path in sorted(BACKEND.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        constants = _module_constants(tree)
        rel = path.relative_to(REPO).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute) or node.func.attr != "invoke":
                continue
            capability = _capability_of(node, constants)
            if capability is None:
                continue
            # ``granted_scopes=None`` is the unchecked form; only a non-None
            # value applies the requirement.
            checked = False
            for keyword in node.keywords:
                if keyword.arg != "granted_scopes":
                    continue
                value = keyword.value
                checked = not (isinstance(value, ast.Constant) and value.value is None)
            sites.append(CallSite(rel, capability, checked))
    return sites


def _group(sites: list[CallSite], *, checked: bool) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for site in sites:
        if site.checks_scopes is checked:
            grouped.setdefault(site.capability, []).append(site.file)
    return {name: tuple(sorted(files)) for name, files in grouped.items()}


class TestDeclaredScopes:
    def test_the_catalogue_declares_exactly_these_scopes(self):
        declared = {
            spec.capability: spec.auth_scope for spec in build_registry().specs() if spec.auth_scope
        }
        assert declared == DECLARED_SCOPES, (
            "A capability's auth_scope changed. Update DECLARED_SCOPES here and "
            "docs/tool-gateway-engagement-migration.md §9.6 -- a new declaration "
            "is a new promise that something has to keep."
        )

    def test_eight_of_twelve_capabilities_declare_a_scope(self):
        """The denominator matters: "some capabilities are scoped" hides the ratio."""
        specs = build_registry().specs()
        assert len(specs) == 12
        assert len([spec for spec in specs if spec.auth_scope]) == 8


class TestWhereTheCheckIsApplied:
    def test_exactly_two_call_sites_apply_a_scope(self):
        checked = _group(_call_sites(), checked=True)
        assert checked == CHECKED_CALL_SITES, (
            "The set of scope-checking call sites changed. If you just wired one, "
            "move it out of UNCHECKED_CALL_SITES below and update §9.6."
        )

    def test_the_unchecked_surface_is_pinned(self):
        unchecked = _group(_call_sites(), checked=False)
        assert unchecked == UNCHECKED_CALL_SITES, (
            "An invocation site gained or lost its ``granted_scopes`` argument. "
            "This register is the honest count of where the declaration buys "
            "nothing; update it deliberately rather than letting it drift."
        )

    def test_seven_scoped_capabilities_have_no_checked_caller(self):
        """The number §9.6 quotes. It is a debt figure, not a target.

        Unchanged by S5c on purpose: both new checked call sites serve
        ``xhs.publish``, which was already the one covered capability. Two
        call sites, one capability — the debt is counted per capability, not per
        site, because a capability with one checked caller is not "partly
        protected".
        """
        unscoped_but_declared = set(DECLARED_SCOPES) - set(CHECKED_CALL_SITES)
        assert len(unscoped_but_declared) == 7
        assert "xhs.publish" not in unscoped_but_declared  # the one that is covered
