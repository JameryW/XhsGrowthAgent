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

Why it exists: eight of twelve capabilities declared a scope, and when this file
was written exactly one call site applied one. That was invisible until this file
counted it.

Why one of the registers has two halves: "a call site passes no scopes" and "the
declaration is worth nothing there" are not the same fact. A capability that
declares nothing has nothing to check — counting its call site as debt inflates
the number §9.6 quotes. So the unchecked surface is split by whether the
capability promised anything, and the debt figure is the first half only.

Five / not eight: ``ripple:read`` was removed rather than wired, because no grant
this system can compute would ever satisfy it. See ``catalog.py``.
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
    "xhs.comment_reply": ("xhs:write",),
    "xhs.competitor_analyzer": ("xhs:read",),
    "xhs.dm_send": ("xhs:write",),
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

# The debt proper: invocation sites that pass no ``granted_scopes`` **and whose
# capability declares one**. These are the sites where the declaration buys
# nothing today. Ordered so a new one is an obvious diff rather than a silent
# widening.
UNCHECKED_CALL_SITES: dict[str, tuple[str, ...]] = {
    "analysis.topic_scorer": ("backend/agents/content_strategist.py",),
    "xhs.competitor_analyzer": ("backend/agents/trend_scout.py",),
    "xhs.keyword_monitor": ("backend/agents/trend_scout.py",),
    "xhs.trending": ("backend/agents/trend_scout.py",),
}

# The other half, pinned for a different reason: these sites also pass no
# scopes, but their capabilities declare none, so there is nothing being
# skipped. They are listed so that "eleven unchecked sites" cannot be quoted as
# "eleven debts", and so that adding a scope to any of these capabilities has to
# move its call sites across rather than leave them silently uncounted.
UNSCOPED_CALL_SITES: dict[str, tuple[str, ...]] = {
    "content.algorithmic_de_ai": ("backend/agents/copywriter.py",),
    "content.polish_copy": ("backend/agents/copywriter.py",),
    "ripple.get_report": ("backend/agents/analyst.py",),
    "ripple.predict_spread": ("backend/agents/content_strategist.py",),
    "ripple.validate_pmf": ("backend/agents/content_strategist.py",),
    "search.fetch": ("backend/agents/trend_scout.py",),
    "search.web": ("backend/agents/trend_scout.py",),
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

    def test_seven_of_fourteen_capabilities_declare_a_scope(self):
        """The denominator matters: "some capabilities are scoped" hides the ratio.

        Seven of fourteen after Phase B (票 5f): the two engagement
        capabilities joined with ``xhs:write``. Five was not eight for the
        ripple three earlier -- removing a declaration is the one change this
        file is meant to *allow*, see ``test_no_declared_scope_is_unsatisfiable``.
        """
        specs = build_registry().specs()
        assert len(specs) == 14
        assert len([spec for spec in specs if spec.auth_scope]) == 7

    def test_no_declared_scope_is_unsatisfiable(self):
        """Every declared scope must be one :func:`granted_scopes` can emit.

        The point of a declaration is that some caller can satisfy it. A scope
        outside this set is unsatisfiable by construction, which makes the
        declaration a trap: the mechanical fix (passing ``granted_scopes`` at the
        call site) denies the capability forever and blames the caller's
        identity for what is really a missing deployment secret.

        Read from :func:`build_registry`, **not** from ``DECLARED_SCOPES``: the
        register is the thing a hurried change would update alongside the code,
        and a guard that only compares two registers fires on nothing.
        """
        from backend.services.xhs_credentials import XHS_READ_SCOPE, XHS_WRITE_SCOPE

        grantable = {XHS_READ_SCOPE, XHS_WRITE_SCOPE}
        declared = {scope for spec in build_registry().specs() for scope in spec.auth_scope}
        assert declared - grantable == set(), (
            "A capability declares a scope that granted_scopes() can never "
            "produce. Either teach the grant about the new mechanism, or drop "
            "the declaration -- declaring it is the one option that cannot work."
        )


class TestWhereTheCheckIsApplied:
    def test_exactly_two_call_sites_apply_a_scope(self):
        checked = _group(_call_sites(), checked=True)
        assert checked == CHECKED_CALL_SITES, (
            "The set of scope-checking call sites changed. If you just wired one, "
            "move it out of UNCHECKED_CALL_SITES below and update §9.6."
        )

    def test_the_unchecked_surface_is_pinned(self):
        """Both halves, measured together and then split.

        ``_group`` recomputes every site that passes no ``granted_scopes`` from
        the tree. The split is *derived* from the declaration, not asserted
        twice: a site belongs to the debt half exactly when its capability
        declares a scope. So the two registers cannot disagree with the code or
        with each other.
        """
        unchecked = _group(_call_sites(), checked=False)
        debt = {name: files for name, files in unchecked.items() if name in DECLARED_SCOPES}
        nothing_to_check = {
            name: files for name, files in unchecked.items() if name not in DECLARED_SCOPES
        }
        assert debt == UNCHECKED_CALL_SITES, (
            "An invocation site gained or lost its ``granted_scopes`` argument, "
            "or a capability gained/lost its declaration. This register is the "
            "honest count of where the declaration buys nothing; update it "
            "deliberately rather than letting it drift."
        )
        assert nothing_to_check == UNSCOPED_CALL_SITES, (
            "A capability without a declaration gained or lost a call site. "
            "These are not debts -- but they are the places a *new* declaration "
            "would immediately be unpaid, so they stay pinned."
        )

    def test_six_scoped_capabilities_have_no_checked_caller(self):
        """The number §9.6 quotes. It is a debt figure, not a target.

        Was seven while ripple declared ``ripple:read``; was four before 票 5f.
        Removing a declaration retires the debt honestly -- those three
        capabilities are not "partly protected", they are not identity-scoped
        at all. Unchanged by the earlier S5c wiring on purpose: both checked
        call sites serve ``xhs.publish``, and a capability with one checked
        caller is not "partly protected", so the debt is counted per
        capability, not per site.

        The two engagement capabilities (票 5f) declare ``xhs:write`` and have
        **no call site at all** yet -- registered means reachable, not
        invoked. They join this figure but not ``UNCHECKED_CALL_SITES``: that
        register counts *sites where the declaration buys nothing*, and an
        uninvoked capability has no site to count. When one first gets an
        ``.invoke(...)``, either pass ``granted_scopes`` (checked) or record
        the site (debt) -- there is no third option.
        """
        unscoped_but_declared = set(DECLARED_SCOPES) - set(CHECKED_CALL_SITES)
        assert len(unscoped_but_declared) == 6
        assert "xhs.publish" not in unscoped_but_declared  # the one that is covered
        assert set(UNCHECKED_CALL_SITES) <= unscoped_but_declared
        assert unscoped_but_declared - set(UNCHECKED_CALL_SITES) == {
            "xhs.comment_reply",
            "xhs.dm_send",
        }
