"""Recompute every claim ``docs/planning.md`` publishes.

``docs/execution-plane.md`` publishes *locations*, so it is pinned with
``file:line`` anchors (``test_docs_anchors.py``).  ``docs/planning.md`` publishes
*facts* -- how many nodes the graph has, how far the two modes' plans differ,
how many readers the plan has -- and a fact does not drift, it gets *changed*.
Pinning those by location would build a net that goes red when a line moves and
stays green when a number changes; recomputing them pins the thing the argument
actually rests on.

The document's markers ("claim blocks") hold ``id -> published value`` rows.  The
first four checks are a closed loop:

1. every published claim recomputes to the value next to it;
2. every published claim has a recalculator here (a new row cannot be added
   without one);
3. every recalculator here is published there (a dropped row cannot leave an
   orphan -- which is why no row-count floor is needed, unlike the anchor test).

The last two are positive controls for the source scans.  Two of the published
claims are **zero** ("nothing imports the plan", "nothing outside the registry
reads the mode key"), and a claim whose value is zero has no built-in control:
gutting its scanner still yields zero.  So each scan is pointed at a directory
where the thing it looks for *is* present.

Same direction as ``TAKEOVER_HAZARDS``: the registry is the document, and this
test is what makes it non-optional.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.graph.builder import build_graph
from backend.graph.plan import (
    PLAN_TEMPLATES,
    export_plan,
    graph_nodes,
    plan_registry_complaints,
    reachable_nodes,
)
from backend.graph.wiring import CONDITIONAL_EDGES, ROUTERS_WITHOUT_AN_EDGE
from backend.state.enums import WorkflowMode
from backend.state.goal import Goal

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "planning.md"
BACKEND = REPO / "backend"
#: The one module allowed to read the state key.  Absence of readers elsewhere
#: is the fact the document publishes, so the path is compared as a path --
#: ``"state/modes.py" in str(path)`` would be false on Windows and quietly
#: report every reader as an outside one.
REGISTRY = BACKEND / "state" / "modes.py"

_CLAIM_BLOCK = re.compile(r"<!-- claim-table:begin -->(.*?)<!-- claim-table:end -->", re.DOTALL)
# A row looks like `| `id` | `value` | prose |` -- only the first two cells carry
# meaning.  Header and separator rows have no backticks, so they drop.
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def _render(value: Any) -> str:
    """The published spelling of a recomputed value.

    Sets and tuples are sorted and joined, so a claim about *which* things are
    in a collection can be published (and compared) without depending on
    iteration order that nothing guarantees.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(sorted(str(item) for item in value))
    return str(value)


# ── source scans ─────────────────────────────────────────────────────────────
# Scanned over ``backend/`` by default: a test importing the plan is expected and
# is not a "production reader".  ``root`` is a parameter so the positive controls
# below can point the same code at somewhere the thing *does* exist.


def _trees(root: Path) -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"))) for path in sorted(root.rglob("*.py"))
    ]


def _importers_of_the_plan(root: Path = BACKEND) -> list[Path]:
    """Modules that import the plan, in any of the three import shapes."""
    found: list[Path] = []
    for path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module.startswith("backend.graph.plan") or (
                    module == "backend.graph" and any(a.name == "plan" for a in node.names)
                ):
                    found.append(path)
            elif isinstance(node, ast.Import) and any(
                a.name.startswith("backend.graph.plan") for a in node.names
            ):
                found.append(path)
    return sorted(set(found))


def _mode_key_reads(root: Path = BACKEND) -> list[Path]:
    """Every place that *reads* the state key, in either shape.

    Both shapes on purpose: the ticket's S3a criterion was
    ``grep -rn 'get("workflow_mode"'``, which cannot see a subscript read.  A
    write is not a read and is excluded by the subscript's ``Load`` context --
    ``update_fields["workflow_mode"] = ...`` names a DB column, not a decision.
    """
    found: list[Path] = []
    for path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "get"
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and node.args[0].value == "workflow_mode"
                ):
                    found.append(path)
            elif (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "workflow_mode"
                and isinstance(node.ctx, ast.Load)
            ):
                found.append(path)
    return sorted(found)


def _run_graph_call_sites(root: Path = BACKEND) -> list[str]:
    """Every call to the one execution entry point, as ``path:line``."""
    found: list[str] = []
    for path, tree in _trees(root):
        for node in ast.walk(tree):
            func = getattr(node, "func", None)
            if isinstance(func, ast.Attribute) and func.attr == "_run_graph_and_persist":
                found.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
    return sorted(found)


# ── the recalculators, one per published claim ───────────────────────────────


def _plans() -> dict[str, frozenset[str]]:
    return {
        str(mode): frozenset(export_plan(mode).nodes)
        for mode in (WorkflowMode.TREND, WorkflowMode.BRIEF)
    }


def _a_goal() -> Goal:
    """Any goal -- every field is required, and the initial state reads most of them."""
    return Goal(
        account_id="claim",
        thread_id="claim",
        mode=WorkflowMode.TREND,
        topic="claim",
        niche="claim",
        niche_resolution={},
        execution_mode="single",
        dry_run=False,
        auto_publish=False,
        brief=None,
        created_at="2026-09-17T00:00:00",
    )


def _steps_are_sorted_by_node_name() -> bool:
    """``Plan.steps`` is ordered by node name, i.e. the plan states no order."""
    names = [step.node for step in export_plan(WorkflowMode.TREND).steps]
    return names == sorted(names)


_CLAIMS: dict[str, Callable[[], Any]] = {
    # §1.3 -- the topology, the templates and the plans.
    "graph_nodes": lambda: len(graph_nodes()),
    "graph_direct_edges": lambda: len(build_graph().edges),
    "graph_conditional_edges": lambda: len(CONDITIONAL_EDGES),
    "reachable_from_root": lambda: len(reachable_nodes("orchestrator")),
    "reachable_from_trend_entry": lambda: len(reachable_nodes("trend_scout")),
    "reachable_from_brief_entry": lambda: len(reachable_nodes("brief_analyzer")),
    "entry_reachability_is_mode_blind": lambda: (
        reachable_nodes("trend_scout") == reachable_nodes("brief_analyzer")
    ),
    "trend_plan_nodes": lambda: len(export_plan(WorkflowMode.TREND).nodes),
    "brief_plan_nodes": lambda: len(export_plan(WorkflowMode.BRIEF).nodes),
    "plan_symmetric_difference": lambda: tuple(sorted(_plans()["trend"] ^ _plans()["brief"])),
    "trend_plan_is_a_subset_of_brief_plan": lambda: _plans()["trend"] <= _plans()["brief"],
    # Published because gate shape E3 ("a goal that needs an order the plan
    # cannot express") is only meaningful while this holds.
    "plan_steps_are_sorted_by_node_name": _steps_are_sorted_by_node_name,
    "trend_exclusions": lambda: len(PLAN_TEMPLATES[WorkflowMode.TREND].excludes),
    "brief_exclusions": lambda: len(PLAN_TEMPLATES[WorkflowMode.BRIEF].excludes),
    "workflow_modes": lambda: tuple(str(mode) for mode in WorkflowMode),
    "plan_templates": lambda: tuple(str(mode) for mode in PLAN_TEMPLATES),
    "goal_initial_state_keys": lambda: len(_a_goal().compile_initial_state()),
    # §1.5 -- the readers that do not exist yet.
    "production_importers_of_the_plan": lambda: len(_importers_of_the_plan()),
    "workflow_mode_reads_total": lambda: len(_mode_key_reads()),
    "workflow_mode_reads_outside_the_registry": lambda: len(
        [path for path in _mode_key_reads() if path != REGISTRY]
    ),
    "run_graph_and_persist_call_sites": lambda: len(_run_graph_call_sites()),
    "routers_without_an_edge": lambda: tuple(sorted(ROUTERS_WITHOUT_AN_EDGE)),
    "plan_registry_complaints_is_empty": lambda: plan_registry_complaints() == {},
}


def _published() -> dict[str, str]:
    """The ``id -> value`` rows of every claim block, in document order."""
    text = DOC.read_text(encoding="utf-8")
    rows: dict[str, str] = {}
    for block in _CLAIM_BLOCK.findall(text):
        for claim_id, value in _ROW.findall(block):
            assert claim_id not in rows, f"{claim_id} is published twice"
            rows[claim_id] = value
    return rows


def test_the_doc_is_here_and_its_marker_pairs_are_balanced():
    """A lost marker would silently hide rows from all four checks below."""
    text = DOC.read_text(encoding="utf-8")
    begins = text.count("<!-- claim-table:begin -->")
    ends = text.count("<!-- claim-table:end -->")
    assert begins == ends, f"{begins} begin marker(s) vs {ends} end marker(s)"
    assert begins > 0, "no claim block found -- every check below would be vacuous"
    assert _published(), "the claim blocks hold no `id | value` rows"


def test_every_published_claim_recomputes_to_the_value_it_publishes():
    complaints = []
    for claim_id, published in _published().items():
        recalculate = _CLAIMS.get(claim_id)
        if recalculate is None:
            continue  # reported by the next test, with a better message
        actual = _render(recalculate())
        if actual != published:
            complaints.append(f"{claim_id}: publishes {published!r} but recomputes to {actual!r}")
    detail = "\n  ".join(complaints)
    assert not complaints, f"docs/planning.md has drifted from the code:\n  {detail}"


def test_no_claim_is_published_without_a_recalculator():
    """A row without a checker is a number nobody re-tests -- the whole point."""
    orphans = sorted(set(_published()) - set(_CLAIMS))
    assert not orphans, (
        "these claims are published but nothing recomputes them; add them to "
        f"_CLAIMS or drop them from docs/planning.md: {orphans}"
    )


def test_no_recalculator_is_left_behind_by_the_document():
    """The backward direction -- and why no row-count floor is needed here.

    ``test_docs_anchors.py`` needs ``len(rows) >= N`` because its rows are only
    ever *checked*, never *enumerated*: a deleted row is invisible.  Here the set
    of recalculators is itself the enumeration, so a dropped row shows up as an
    orphaned checker and this assertion fires.
    """
    missing = sorted(set(_CLAIMS) - set(_published()))
    assert not missing, (
        f"these claims have a recalculator but are not published in {DOC.name}: {missing}"
    )


def test_the_import_scanner_finds_an_importer_that_is_there():
    """Positive control for ``production_importers_of_the_plan``.

    That claim's value is 0, so nothing in ``backend/`` can show the scanner is
    working -- a scanner gutted to ``return []`` would keep the whole file green.
    This file imports the plan, so pointing the *same* scanner at its own
    directory has to find it.
    """
    here = Path(__file__).resolve()
    found = _importers_of_the_plan(here.parent)
    assert here in found, f"the scanner cannot see an importer in its own directory: {found}"


def test_the_mode_key_scanner_counts_reads_and_not_writes(tmp_path: Path):
    """Positive control for both mode-key claims, and for the ``Load`` filter.

    Two reads and one write, because a scanner that counted every subscript
    would answer 3 -- i.e. this fixture **discriminates**, which a fixture with
    only reads would not.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def handler(state, update_fields):\n"
        '    read_one = state.get("workflow_mode")\n'
        '    read_two = state["workflow_mode"]\n'
        '    update_fields["workflow_mode"] = read_two\n'
        "    return read_one\n",
        encoding="utf-8",
    )
    reads = _mode_key_reads(tmp_path)
    assert len(reads) == 2, f"expected the two reads and not the write: {reads}"
