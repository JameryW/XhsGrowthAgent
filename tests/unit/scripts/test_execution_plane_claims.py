"""Recompute every claim ``docs/execution-plane.md`` makes, including its own.

This document was the one that looked safe.  Its ``file:line`` anchors are pinned
by ``test_docs_anchors.py`` -- and §0 said so, in one sentence:

    every ``file:line`` in this file is pinned by ``test_docs_anchors.py``

It was not true, and the sentence was the reason nobody looked.  Measured before
this slice: 84 cited line numbers, 51 of them inside a marked table.  The other
33 sat in prose with nothing checking them, and they had already rotted -- §7
cited ``:3008`` for a file that is 371 lines long, twice, while §8's own table
carried the correct line for the same fact.

So this file pins two things the anchor tables cannot:

1. **Values.**  §7's closing section offered "give ``_run_retry`` a registry
   write -- one line, does not change execution semantics" as the cheapest next
   step.  The line count is right; the cost is not.  ``_background_tasks`` is an
   OR-term of ``process_has_active_task()``, whose two consumers both answer
   "don't start work" when they read ``True``, and the window is 1800 s because
   the two ``submit_and_wait`` calls are gathered, not sequenced.  A cost model
   made of prose is how "one line" gets chosen over a ruling.

2. **Every cited line number resolves.**  ``path:line`` against the repo, and a
   bare ``:N`` against the nearest preceding full path *in the same section* --
   which is what a bare reference means to a reader.  The rule is deliberately
   weaker than the table check (no token comparison, because prose does not name
   one) and its limit is published next to the numbers.

3. **Which of the sibling's four properties are copyable.**  §7 offered them as
   four gaps.  Measured, the registry is why three of them are not: it is keyed
   by ``thread_id`` -- one slot per thread -- and three call sites cancel
   whatever sits in that slot, so a retry registering there would not shadow a
   line, it would displace the workflow's own entry and retarget
   ``pause``/``cancel``/``resume`` at the retry.  The counts are published so the
   ruling is re-tested each run instead of re-remembered.

The pattern for "a cited line number" carries **no extension whitelist**: an
earlier version of it listed extensions and silently skipped ``Dockerfile:81``.
A scan that cannot see a reference cannot fail on it, and a whitelist is exactly
where a reference goes to hide.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from docs_citation_rule import _PATH_LINE, _cited

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "execution-plane.md"
BACKEND = REPO / "backend"
RUNNER = BACKEND / "api" / "routes" / "_runner.py"
ACTIONS = BACKEND / "api" / "routes" / "_wf_actions.py"
APP = REPO / "backend" / "api" / "app.py"
MACHINE = BACKEND / "state" / "machine.py"
LEASES = BACKEND / "db" / "execution_leases.py"
EVENTS = BACKEND / "state" / "events.py"

_CLAIM_BLOCK = re.compile(r"<!-- claim-table:begin -->(.*?)<!-- claim-table:end -->", re.DOTALL)
_ANCHOR_TABLES = re.compile(
    r"<!-- (?:anchor-table|anchor-absence):begin -->(.*?)"
    r"<!-- (?:anchor-table|anchor-absence):end -->",
    re.DOTALL,
)
# A row looks like `| `id` | `value` | prose |` -- only the first two cells carry
# meaning.  Header and separator rows have no backticks, so they drop.
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)

# The citation rule lives in ``docs_citation_rule.py``: it stopped being about this
# document when it started sweeping the corpus.  ``_PATH_LINE`` and ``_cited`` come
# from there, so there is exactly one answer to "what counts as a citation".


def _render(value: Any) -> str:
    """The published spelling of a recomputed value."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(sorted(str(item) for item in value))
    return str(value)


# ── code scans ───────────────────────────────────────────────────────────────


def _trees(root: Path) -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"))) for path in sorted(root.rglob("*.py"))
    ]


def _callee(node: ast.Call) -> str | None:
    """The identifier a call goes through: ``f()`` and ``x.f()`` both answer ``f``."""
    func = node.func
    return getattr(func, "id", None) or getattr(func, "attr", None)


def _show(path: Path) -> str:
    """A path as reported in a claim: repo-relative where it can be.

    ``relative_to`` raises for a path outside the repo, and the positive-control
    fixtures are exactly that -- a scan that only worked on paths under the repo
    could not be pointed anywhere, so it could never be proved to work.
    """
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _call_sites(root: Path, callee: str, *, outside: Path | None = None) -> list[str]:
    """``path:line`` for every call of *callee*, optionally skipping one module.

    *outside* is how the two predicates are counted: their own defining module
    calls them too (``_runner.py:91`` is the OR into ``has_active_execution``),
    and counting that as a consumer would overstate the blast radius by exactly
    the link that makes it transitive.
    """
    found: list[str] = []
    for path, tree in _trees(root):
        if outside is not None and path.resolve() == outside.resolve():
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _callee(node) == callee:
                found.append(f"{_show(path)}:{node.lineno}")
    return sorted(found)


def _calls_within(path: Path, callee: str) -> int:
    """Call sites of *callee* inside **one** module.

    ``_call_sites`` walks a directory, and the two numbers §7 hands the next task
    are about a single file: how many ``start_lease`` calls and how many direct
    ``aupdate_state`` writes the two repair paths contain.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1 for node in ast.walk(tree) if isinstance(node, ast.Call) and _callee(node) == callee
    )


def _stores_into(func: ast.AST, name: str) -> bool:
    """Whether *func* assigns into ``name[...]`` -- a store, not a read or a pop."""
    for node in ast.walk(func):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                base = target.value
                attr = getattr(base, "attr", None) or getattr(base, "id", None)
                if attr == name:
                    return True
    return False


def _functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]


def _registrations(path: Path, target: str) -> int:
    """1 when the function starting ``asyncio.create_task(<target>(...))`` also stores it.

    The registration lives in the *route handler*, not inside the coroutine it
    starts, so the question is asked of the enclosing function.  That is the
    shape that differs between the two repair paths: ``retry_publish`` stores at
    ``:363``, ``retry_ripple_analysis`` does not.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for func in _functions(tree):
        starts = [
            node
            for node in ast.walk(func)
            if isinstance(node, ast.Call)
            and _callee(node) == "create_task"
            and node.args
            and _callee(node.args[0]) == target
        ]
        if starts:
            return 1 if _stores_into(func, "_background_tasks") else 0
    raise AssertionError(f"no asyncio.create_task({target}(...)) site in {path.name}")


def _submits_are_concurrent(path: Path, target: str) -> bool:
    """True when every ``.submit_and_wait`` result is consumed by ONE ``gather``.

    This is the whole difference between a 1800 s window and 3600 s, and it is
    not readable from the two call sites -- both spellings look identical.  A
    sequential pair answers ``False`` here, which is what makes the ``true``
    claim a claim rather than a constant.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for func in _functions(tree):
        if func.name != target:
            continue
        submitted: set[str] = set()
        for node in ast.walk(func):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
                continue
            if _callee(node.value) != "submit_and_wait":
                continue
            for target_node in node.targets:
                if isinstance(target_node, ast.Name):
                    submitted.add(target_node.id)
        if not submitted:
            return False
        gathered: set[str] = set()
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and _callee(node) == "gather":
                for arg in node.args:
                    if isinstance(arg, ast.Name):
                        gathered.add(arg.id)
        return submitted <= gathered
    raise AssertionError(f"no function named {target} in {path.name}")


def _literal_assignment(path: Path, name: str) -> Any:
    """The literal value assigned to *name*, wherever it is assigned.

    ``ripple_timeout`` is a local, not a module constant -- a scan that only read
    module level would answer ``None`` and turn the window into an unverifiable
    sentence.
    """
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == name
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} is never assigned in {path.name}")


# ── the two repair paths, property by property ───────────────────────────────
# §7 used to describe the difference between these two handlers as "one line".
# It is five properties, four of them missing on one side.


def _calls_in(path: Path, handler: str) -> list[ast.Call]:
    """Every call inside one named function -- the handler, not the whole module."""
    for func in _functions(ast.parse(path.read_text(encoding="utf-8"))):
        if func.name == handler:
            return [node for node in ast.walk(func) if isinstance(node, ast.Call)]
    raise AssertionError(f"no function named {handler} in {path.name}")


def _guard_calls(path: Path, handler: str) -> int:
    """Serialization guards in one repair path.

    Both paths write checkpoint state, so both should ask the same question before
    starting.  One does and one does not, and this is that number.
    """
    return sum(1 for call in _calls_in(path, handler) if _callee(call) == "process_has_active_task")


def _done_callback_calls(path: Path, handler: str) -> int:
    """``add_done_callback`` in one repair path -- the DB-facing half of a retry."""
    return sum(1 for call in _calls_in(path, handler) if _callee(call) == "add_done_callback")


def _started_coroutine(path: Path, handler: str) -> str:
    """The coroutine a handler hands to ``asyncio.create_task``."""
    for call in _calls_in(path, handler):
        if _callee(call) == "create_task" and call.args:
            target = call.args[0]
            if isinstance(target, ast.Call) and _callee(target):
                return str(_callee(target))
    raise AssertionError(f"{handler} starts no named coroutine")


def _started_coroutine_cleans_up(path: Path, handler: str) -> int:
    """1 when that coroutine removes its own registry entry from a ``finally``.

    Only ``finalbody`` is walked: a ``pop`` on the happy path would leave the entry
    behind on cancellation -- the one case the cleanup exists for.
    """
    name = _started_coroutine(path, handler)
    for func in _functions(ast.parse(path.read_text(encoding="utf-8"))):
        if func.name != name:
            continue
        for node in ast.walk(func):
            if not isinstance(node, ast.Try) or not node.finalbody:
                continue
            for statement in node.finalbody:
                for sub in ast.walk(statement):
                    if isinstance(sub, ast.Call) and _callee(sub) in {"pop", "discard", "remove"}:
                        return 1
    return 0


# ── the ruling: what the registry can and cannot absorb ──────────────────────
# §7's closing section offered "give ``_run_retry`` a registry write" as part of
# closing the gap.  These three numbers are why it is not a write, it is a
# trade: the registry holds one task per thread_id, and three functions cancel
# whoever is in the slot.

_SERIALIZATION_SENTENCE = "工作流正在运行，无法重试。"


def _registry_declared_value_type(path: Path) -> str:
    """The declared type of one entry in the task registry.

    The ruling in §7 turns on the registry holding **one** task per ``thread_id``:
    that is what makes a second writer displace the first instead of adding to it.
    Read from the annotation rather than from the prose, so turning the value into
    a list would show up as a changed claim instead of a stale paragraph.
    """
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "_background_tasks":
            continue
        annotation = node.annotation
        if not isinstance(annotation, ast.Subscript):
            raise AssertionError(f"_background_tasks is annotated as {ast.unparse(annotation)}")
        inner = annotation.slice
        if not isinstance(inner, ast.Tuple) or len(inner.elts) != 2:
            raise AssertionError("expected a two-parameter mapping")
        return ast.unparse(inner.elts[1])
    raise AssertionError(f"no annotated _background_tasks in {path.name}")


def _registry_task_writes(root: Path) -> int:
    """``_background_tasks[...] = task`` sites across *root*."""
    total = 0
    for _path, tree in _trees(root):
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if not isinstance(target, ast.Subscript):
                    continue
                base = getattr(target.value, "attr", None) or getattr(target.value, "id", None)
                if base == "_background_tasks":
                    total += 1
    return total


def _registry_readers_that_cancel(root: Path) -> int:
    """Functions that read the registry's occupant and then cancel it.

    ``bg = _background_tasks.get(thread_id)`` followed by ``bg.cancel()`` -- in
    ``pause_workflow``, ``cancel_workflow`` and ``_start_resume_task``.  They act
    on whoever is in the slot, which is the whole cost of a second writer.
    """
    total = 0
    for _path, tree in _trees(root):
        for func in _functions(tree):
            reads = any(
                isinstance(sub, ast.Call)
                and _callee(sub) == "get"
                and isinstance(sub.func, ast.Attribute)
                and (getattr(sub.func.value, "attr", None) or getattr(sub.func.value, "id", None))
                == "_background_tasks"
                for sub in ast.walk(func)
            )
            cancels = any(
                isinstance(sub, ast.Call) and _callee(sub) == "cancel" for sub in ast.walk(func)
            )
            if reads and cancels:
                total += 1
    return total


def _paths_saying_the_serialization_sentence() -> int:
    """How many of the two repair paths carry the shared refusal sentence.

    The ruling is that both answer the *same* question, so they answer it in the
    same words -- a sentence that drifted apart is the cheapest observable sign
    that the rule did too.  Published as 2.
    """
    wanted = {"retry_ripple_analysis", "retry_publish"}
    tree = ast.parse(ACTIONS.read_text(encoding="utf-8"))
    saying = 0
    for func in _functions(tree):
        if func.name not in wanted:
            continue
        if any(
            isinstance(sub, ast.Constant)
            and isinstance(sub.value, str)
            and _SERIALIZATION_SENTENCE in sub.value
            for sub in ast.walk(func)
        ):
            saying += 1
    return saying


# ── the census behind §7's criterion ─────────────────────────────────────────
# §7 used to call the two repair paths "the ones that write checkpoints without a
# lease".  That describes twenty call sites in seven files, so it pinpoints
# nothing.  The criterion that does is "the handler hands a nested coroutine to
# create_task and that coroutine writes".  The scans below are what keeps the set
# from being restated by hand.


def _owner_map(tree: ast.Module) -> dict[int, str]:
    """Call node -> the dotted name of its enclosing function (``h.nested``)."""

    owner: dict[int, str] = {}
    stack: list[str] = []

    def walk(node: ast.AST) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.append(node.name)
            for child in ast.iter_child_nodes(node):
                walk(child)
            stack.pop()
            return
        if isinstance(node, ast.Call):
            owner[id(node)] = ".".join(stack) or "<module>"
        for child in ast.iter_child_nodes(node):
            walk(child)

    walk(tree)
    return owner


def _writers_outside_the_entry(path: Path, entry: str) -> list[str]:
    """``path:line`` of checkpoint writes whose host function is not *entry*."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    owner = _owner_map(tree)
    return sorted(
        f"{_show(path)}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _callee(node) == "aupdate_state"
        and owner.get(id(node)) != entry
    )


def _own_task_writers(path: Path) -> int:
    """Handlers that start a nested coroutine *and* let that coroutine write.

    The criterion, as code: the call handed to ``create_task`` must name a
    function defined in the same handler's body, and that function must contain a
    checkpoint write.  A handler that writes inline, or that starts a task which
    routes through ``_run_graph_and_persist``, is not one of these.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = 0
    for handler in _functions(tree):
        for node in ast.walk(handler):
            if not (isinstance(node, ast.Call) and _callee(node) == "create_task"):
                continue
            if not node.args:
                continue
            started = getattr(getattr(node.args[0], "func", None), "id", None)
            if started is None:
                continue
            target = next(
                (
                    stmt
                    for stmt in handler.body
                    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and stmt.name == started
                ),
                None,
            )
            if target is None:
                continue
            if any(
                isinstance(x, ast.Call) and _callee(x) == "aupdate_state" for x in ast.walk(target)
            ):
                found += 1
    return found


def _definitions(path: Path, name: str) -> int:
    """How many times *name* is defined in one module."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def _enum_members(path: Path, name: str) -> int:
    """How many members an enum declared in one module has.

    Members are the names assigned in the class body.  Published as 3 for
    ``AcquireOutcome``: a refusal is one of three answers, and the number is what
    keeps "three spellings of ``False``" from being a figure of speech.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = next(
        (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and node.name == name),
        None,
    )
    assert target is not None, f"{name} not found in {path}"
    return sum(
        1
        for stmt in target.body
        if isinstance(stmt, ast.Assign) and all(isinstance(t, ast.Name) for t in stmt.targets)
    )


def _tests_for_a_member(path: Path, enum: str, member: str) -> int:
    """How many comparisons test ``<enum>.<member>`` in one module.

    Counted over ``Compare`` nodes rather than attributes because what the claim
    is about is "how many call sites branch on this value".  The same member also
    appears as ``AcquireOutcome.HELD_BY_LIVE_OWNER.value`` where it is written
    into an event, so an attribute scan would report 3 branches where there are 2.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for side in (node.left, *node.comparators):
            if (
                isinstance(side, ast.Attribute)
                and side.attr == member
                and isinstance(side.value, ast.Name)
                and side.value.id == enum
            ):
                total += 1
    return total


def _refusal_reason_names(path: Path) -> int:
    """Module-level ``ACTION_*`` string constants that are reasons, not kinds.

    Derived from the shape rather than from a list: the prefix says the name is
    part of the action vocabulary, a string value says it names something, and the
    absence of ``KIND`` separates a reason (``ACTION_POLICY_DENIED``) from the
    event kind reasons are filed under (``ACTION_EVENT_KIND``).  A hand-kept list
    would have made this claim blind to the next reason added -- which is exactly
    the reason this slice added.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for stmt in tree.body
        if isinstance(stmt, ast.Assign)
        and len(stmt.targets) == 1
        and isinstance(stmt.targets[0], ast.Name)
        and stmt.targets[0].id.startswith("ACTION_")
        and "KIND" not in stmt.targets[0].id
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _if_tests_mentioning(path: Path, func: str, name: str) -> int:
    """How many ``if`` tests inside *func* name *name*.

    Published as 1: §7 says the change is visible only across priorities 9/10 of
    ``derive_status``, and those two outcomes are decided by a **single** mention
    -- priority 10 is reached because priority 9 fell through, not because it
    tests the flag again.
    """

    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = next((f for f in _functions(tree) if f.name == func), None)
    assert target is not None, f"{func} not found in {path}"
    return sum(
        1 for node in ast.walk(target) if isinstance(node, ast.If) and name in ast.dump(node.test)
    )


def _create_task_targets(path: Path, callee: str) -> int:
    """``create_task(<callee>(...))`` call sites in one module."""

    tree = ast.parse(path.read_text(encoding="utf-8"))
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and _callee(node) == "create_task"
        and node.args
        and getattr(getattr(node.args[0], "func", None), "id", None) == callee
    )


# ── the ruling table: the slice's deliverable, read back ─────────────────────
# §7's four verdicts are what this slice decided, and their values were pinned one
# at a time without pinning the verdicts themselves: a document that flipped 采纳
# to 不采纳, leaving the code alone, would have stayed green.  Each row is now
# paired with the claim that has to agree with it.

_RULING_HEADER = "| 性质 | 裁定 | 依据 |"

# Verdict spellings the table may use -> whether the paired property must exist.
# An unregistered spelling raises rather than being skipped: a verdict no reader
# can interpret is the same as no verdict.
_RULING_VERDICTS: dict[str, bool] = {"采纳": True, "不采纳": False, "连带不采纳": False}

# The 性质 cell, markdown stripped -> the claim id whose value decides the verdict
_RULING_FACTS: dict[str, str] = {
    "串行化守卫": "ripple_retry_serialization_guards",
    "add_done_callback": "ripple_retry_done_callbacks",
    "_background_tasks[...] =": "ripple_retry_task_registrations",
    "被起协程的自身清理": "ripple_retry_self_cleanups",
}


def _plain(cell: str) -> str:
    """A table cell with its markdown emphasis and code ticks removed."""
    return cell.replace("**", "").replace("`", "").strip()


def _ruling_verdicts() -> dict[str, str]:
    """``性质 -> 裁定``, read from §7's ruling table in document order.

    Anchored on the header row rather than on a marked block: the table is prose
    (it has no ``path:line`` first cell, so the anchor tables would reject it).
    """
    lines = _DOC_TEXT.splitlines()
    assert lines.count(_RULING_HEADER) == 1, "expected exactly one ruling table"
    start = lines.index(_RULING_HEADER) + 2  # skip the header and its separator
    verdicts: dict[str, str] = {}
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        cells = line.strip().strip("|").split("|")
        assert len(cells) == 3, f"the ruling table changed shape: {line!r}"
        verdicts[_plain(cells[0])] = _plain(cells[1])
    assert verdicts, "the ruling table is empty"
    return verdicts


# ── the marked tables ─------------------------------------------------------------


def _pinned_rows(text: str) -> list[str]:
    """First cells of the marked tables that are themselves ``path:line``."""
    found: list[str] = []
    for block in _ANCHOR_TABLES.findall(text):
        for anchor, _token in _ROW.findall(block):
            if _PATH_LINE.fullmatch(f"`{anchor}`"):
                found.append(anchor)
    return found


# ── the recalculators, one per published claim ───────────────────────────────

_DOC_TEXT = DOC.read_text(encoding="utf-8")


def _published() -> dict[str, str]:
    """The ``id -> value`` rows of every claim block in the document."""
    rows: dict[str, str] = {}
    for block in _CLAIM_BLOCK.findall(_DOC_TEXT):
        for claim_id, value in _ROW.findall(block):
            assert claim_id not in rows, f"docs/execution-plane.md publishes {claim_id} twice"
            rows[claim_id] = value
    return rows


def _paired_claim_ids(published: Mapping[str, str]) -> list[tuple[str, str]]:
    """The properties the document presents on **both** repair paths.

    The pairing is read *from the document*, so a row dropped on one side shrinks
    this list silently -- which is why the caller pins its length instead of
    trusting it.  The lease is not a pair either, but for a different reason than it
    used to be: §7 states it once, as the number of executors that take it (three),
    so there is no left/right pair to compare -- the convergence is in the claim.
    Neither is the guard any more
    -- see ``_CONVERGED_PROPERTIES`` -- so a convergence is not just tolerated,
    it is asserted on its own below.
    """
    ids = set(published)
    pairs: list[tuple[str, str]] = []
    for name in sorted(ids):
        if not name.startswith("ripple_retry_"):
            continue
        tail = name[len("ripple_retry_") :]
        if tail in _CONVERGED_PROPERTIES:
            continue
        twin = "publish_retry_" + tail
        if twin in ids:
            pairs.append((name, twin))
    return pairs


# Properties the two paths used to differ on and no longer do.  The guard is the
# one this slice adopted on the ripple-retry side: §7's table stops being a list
# of gaps and becomes a ruling.  Named explicitly -- and pinned by its own test --
# so that excluding it does not also excuse it from being checked ever again.
_CONVERGED_PROPERTIES = {"serialization_guards"}


_BUDGET_CONSTANT = "HEARTBEAT_TRANSIENT_FAILURES_TOLERATED"


def _misses_the_scanner_tolerates(path: Path) -> int:
    """How many failed renews the scanner tolerates before it presumes death.

    A named function rather than arithmetic inside a lambda, because the mutation
    that matters is dropping the ``- 1`` -- and a control that performs the
    subtraction itself would keep passing while the published value moved.
    """
    return _literal_assignment(path, "HEARTBEAT_MISSES_BEFORE_EXPIRY") - 1


def _transient_failures_the_owner_tolerates(path: Path) -> int:
    """How many consecutive misses the owner tolerates before it stops.

    Recomputed from the *derivation* rather than read off a literal, because being
    derived is the whole point of the constant: a mutation that replaced
    ``HEARTBEAT_MISSES_BEFORE_EXPIRY - 2`` with a hard-coded ``1`` would keep every
    value assertion green -- the published value is also 1 -- while breaking exactly
    the property the constant exists for.  So the shape is asserted as well as the
    number, and the positive control runs against a fixture whose ``M`` is not 3.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == _BUDGET_CONSTANT
        ):
            value = node.value
            assert isinstance(value, ast.BinOp), (
                f"{_BUDGET_CONSTANT} is not derived from anything: {ast.dump(value)}"
            )
            assert isinstance(value.op, ast.Sub), ast.dump(value.op)
            assert isinstance(value.left, ast.Name), ast.dump(value.left)
            assert isinstance(value.right, ast.Constant), ast.dump(value.right)
            return _literal_assignment(path, value.left.id) - value.right.value
    raise AssertionError(f"{_BUDGET_CONSTANT} is never assigned in {path.name}")


def _mentions_attr(expr: ast.expr, attr: str) -> bool:
    """Whether an expression compares against ``<something>.attr``."""
    return any(isinstance(node, ast.Attribute) and node.attr == attr for node in ast.walk(expr))


def _the_budget_never_covers_the_evidenced_answer(path: Path, func: str) -> bool:
    """Whether the loop decides ``LOST`` *before* it consults the tolerance budget.

    This replaces a claim that read the operator of the comparison against
    ``RENEWED`` -- "every non-answer stops".  That reading is dead: the loop is a
    three-row table now, and the row that matters is the one that must stay
    unreachable by the budget.  Ordering is where that lives.  A budget spent on
    the member that is *evidence about the row* would be the ruling backwards:
    silence is what there is to be patient with, not a fact.

    ``False`` when the budget is consulted first, when the loop never mentions it
    (over-conservative, but not this ruling), and when there is no ``LOST`` branch
    to find -- a loop with neither is not the shape this claim names.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func
        ),
        None,
    )
    assert target is not None, f"{func} not found in {path}"
    evidence_at: int | None = None
    budget_at: int | None = None
    for node in ast.walk(target):
        if isinstance(node, ast.If) and _mentions_attr(node.test, "LOST"):
            evidence_at = node.lineno if evidence_at is None else min(evidence_at, node.lineno)
        if isinstance(node, ast.Name) and node.id == _BUDGET_CONSTANT:
            budget_at = node.lineno if budget_at is None else min(budget_at, node.lineno)
    if evidence_at is None or budget_at is None:
        return False
    return evidence_at < budget_at


_CLAIMS: dict[str, Callable[[], Any]] = {
    # §7 -- the cost of "one line"
    "process_has_active_task_consumers_outside_the_runner": lambda: len(
        _call_sites(BACKEND, "process_has_active_task", outside=RUNNER)
    ),
    "status_consumers_of_has_active_execution": lambda: len(
        _call_sites(BACKEND, "has_active_execution", outside=RUNNER)
    ),
    "run_graph_and_persist_call_sites": lambda: len(_call_sites(BACKEND, "_run_graph_and_persist")),
    "start_lease_call_sites_under_backend": lambda: len(_call_sites(BACKEND, "start_lease")),
    "ripple_retry_max_wait_seconds": lambda: _literal_assignment(ACTIONS, "ripple_timeout"),
    "ripple_retry_task_registrations": lambda: _registrations(ACTIONS, "_run_retry"),
    "publish_retry_task_registrations": lambda: _registrations(ACTIONS, "_run_publish_retry"),
    "ripple_retry_submits_are_concurrent": lambda: _submits_are_concurrent(ACTIONS, "_run_retry"),
    # §7 -- the shape: the same five properties on both repair paths
    "ripple_retry_serialization_guards": lambda: _guard_calls(ACTIONS, "retry_ripple_analysis"),
    "publish_retry_serialization_guards": lambda: _guard_calls(ACTIONS, "retry_publish"),
    "ripple_retry_done_callbacks": lambda: _done_callback_calls(ACTIONS, "retry_ripple_analysis"),
    "publish_retry_done_callbacks": lambda: _done_callback_calls(ACTIONS, "retry_publish"),
    "ripple_retry_self_cleanups": lambda: _started_coroutine_cleans_up(
        ACTIONS, "retry_ripple_analysis"
    ),
    "publish_retry_self_cleanups": lambda: _started_coroutine_cleans_up(ACTIONS, "retry_publish"),
    # §7 -- the ruling: which of the sibling's four properties are copyable
    "registry_task_write_sites_under_backend": lambda: _registry_task_writes(BACKEND),
    "registry_declared_value_type": lambda: _registry_declared_value_type(RUNNER),
    "registry_readers_that_cancel_the_occupant": lambda: _registry_readers_that_cancel(BACKEND),
    "repair_paths_using_the_shared_serialization_sentence": lambda: (
        _paths_saying_the_serialization_sentence()
    ),
    "start_lease_call_sites_in_wf_actions": lambda: _calls_within(ACTIONS, "start_lease"),
    "direct_aupdate_state_call_sites_in_wf_actions": lambda: _calls_within(
        ACTIONS, "aupdate_state"
    ),
    # §7 -- the criterion, and the lease that now covers all three executors
    "repair_paths_taking_the_lease": lambda: _calls_within(ACTIONS, "_execution_lease"),
    "lease_helper_definitions_in_the_runner": lambda: _definitions(RUNNER, "_execution_lease"),
    "end_lease_call_sites_under_backend": lambda: len(_call_sites(BACKEND, "end_lease")),
    "aupdate_state_call_sites_outside_the_unified_entry": lambda: sum(
        len(_writers_outside_the_entry(path, "_run_graph_and_persist"))
        for path, _tree in _trees(BACKEND)
    ),
    "checkpoint_writer_files_outside_the_unified_entry": lambda: sum(
        1
        for path, _tree in _trees(BACKEND)
        if _writers_outside_the_entry(path, "_run_graph_and_persist")
    ),
    "repair_paths_that_own_their_own_task": lambda: _own_task_writers(ACTIONS),
    "expire_scan_call_sites_under_backend": lambda: len(_call_sites(BACKEND, "expire_scan")),
    "takeover_scheduler_start_sites": lambda: _create_task_targets(APP, "takeover_scheduler"),
    "derive_status_mentions_of_has_active_task": lambda: _if_tests_mentioning(
        MACHINE, "derive_status", "has_active_task"
    ),
    # §2 / §7 -- a refusal that says which refusal, and the callers that read it
    "acquire_outcome_members": lambda: _enum_members(LEASES, "AcquireOutcome"),
    "acquire_outcome_definitions_in_the_lease_module": lambda: _definitions(
        LEASES, "acquire_outcome"
    ),
    "execution_lease_call_sites_under_backend": lambda: len(
        _call_sites(BACKEND, "_execution_lease")
    ),
    "repair_paths_that_stand_down_on_a_live_owner": lambda: _tests_for_a_member(
        ACTIONS, "AcquireOutcome", "HELD_BY_LIVE_OWNER"
    ),
    "lease_refusal_reasons_in_the_action_vocabulary": lambda: _refusal_reason_names(EVENTS),
    # §2 -- the answer a lost lease gives, and who reads it
    "renew_outcome_members": lambda: _enum_members(LEASES, "RenewOutcome"),
    "renew_outcome_definitions_in_the_lease_module": lambda: _definitions(LEASES, "renew_outcome"),
    "renew_call_sites_under_backend": lambda: len(_call_sites(BACKEND, "renew")),
    "renew_outcome_call_sites_under_backend": lambda: len(_call_sites(BACKEND, "renew_outcome")),
    "transient_failures_the_owner_tolerates": lambda: _transient_failures_the_owner_tolerates(
        LEASES
    ),
    "the_budget_never_covers_the_evidenced_answer": lambda: (
        _the_budget_never_covers_the_evidenced_answer(LEASES, "_heartbeat_until_cancelled")
    ),
    "misses_the_scanner_tolerates": lambda: _misses_the_scanner_tolerates(LEASES),
    # §8 -- how much of this document its own tables actually cover
    "line_number_references_in_this_document": lambda: sum(
        len(part) for part in _cited(_DOC_TEXT, REPO)
    ),
    "line_numbers_pinned_by_marked_tables": lambda: len(_pinned_rows(_DOC_TEXT)),
    "bare_line_number_references_in_this_document": lambda: len(_cited(_DOC_TEXT, REPO)[1]),
}


def test_the_claim_markers_are_balanced_and_carry_rows():
    """A lost marker would silently hide rows from every check below."""
    begins = _DOC_TEXT.count("<!-- claim-table:begin -->")
    ends = _DOC_TEXT.count("<!-- claim-table:end -->")
    assert begins == ends, f"{begins} begin marker(s) vs {ends} end marker(s)"
    assert begins > 0, "no claim block -- every check below would be vacuous"
    assert _published(), "the claim blocks hold no `id | value` rows"


def test_every_published_claim_recomputes_to_the_value_it_publishes():
    complaints = []
    for claim_id, published in _published().items():
        recalculate = _CLAIMS.get(claim_id)
        if recalculate is None:
            continue  # reported by the next test, with a better message
        actual = _render(recalculate())
        if actual != published:
            complaints.append(f"{claim_id} publishes {published!r} but recomputes to {actual!r}")
    detail = "\n  ".join(complaints)
    assert not complaints, (
        "docs/execution-plane.md publishes a claim that no longer holds. Either the tree "
        f"moved -- then update the document -- or the scan is wrong:\n  {detail}"
    )


def test_no_claim_is_published_without_a_recalculator():
    """A row without a checker is a number nobody re-tests -- the whole point."""
    orphans = sorted(set(_published()) - set(_CLAIMS))
    assert not orphans, (
        "these claims are published but nothing recomputes them; add them to "
        f"_CLAIMS or drop them from the document: {orphans}"
    )


def test_no_recalculator_is_left_behind_by_the_document():
    """The backward direction: a dropped row shows up as an orphaned checker."""
    missing = sorted(set(_CLAIMS) - set(_published()))
    assert not missing, f"these claims have a recalculator but are published nowhere: {missing}"


# ── the difference itself ────────────────────────────────────────────────────
# Everything above pins each property's value one at a time.  None of it says the
# two paths *differ*: six independent value claims would all still hold if the tree
# moved to 1 / 1, and the document would be left applying the word 差异 to two
# handlers that are the same.  This is the assertion that makes the word true.


def test_the_two_repair_paths_differ_on_every_property_the_document_pairs():
    pairs = _paired_claim_ids(_published())
    assert len(pairs) == 3, (
        "§7 shows three properties that still differ on both repair paths; the document "
        f"currently pairs {len(pairs)} of them: {pairs}"
    )
    same = [f"{left} == {right}" for left, right in pairs if _same_value(left, right)]
    assert not same, (
        "§7 exists to say these two handlers are not the same shape, but the document "
        f"pairs properties that recompute to equal values: {same}. Either the tree "
        "changed -- then §7's table is wrong -- or the pairing is."
    )


def test_the_pair_that_converged_is_the_one_the_slice_ruled_on():
    """The retired pair, kept as its own claim.

    Dropping a pair from the check above would otherwise also drop it out of
    every future run: a tree that reverted the adopted guard would look exactly
    like a tree that never had it.
    """
    assert len(_CONVERGED_PROPERTIES) == 1, _CONVERGED_PROPERTIES
    assert "serialization_guards" in _CONVERGED_PROPERTIES, _CONVERGED_PROPERTIES
    for name in sorted(_CONVERGED_PROPERTIES):
        left, right = f"ripple_retry_{name}", f"publish_retry_{name}"
        assert _same_value(left, right), (
            f"§7 presents {left} and {right} as the same rule; they recompute to "
            f"{_render(_CLAIMS[left]())} and {_render(_CLAIMS[right]())}"
        )


def test_the_ruling_table_agrees_with_the_four_published_values():
    """The verdicts are this slice's deliverable, so they get a reader too.

    Each row pairs a property with the value that decides it: an adopted property
    has to be there (a non-zero claim), a refused one has to be gone (zero).  The
    two directions are different edits -- flipping a word here is how the document
    lies, moving the code is how it goes stale -- so both are pinned, one test
    each.  A verdict is also required to round-trip through the registered
    spellings, because a third word would otherwise be silently ignored.
    """
    verdicts = _ruling_verdicts()
    assert set(verdicts) == set(_RULING_FACTS), (
        "the ruling table and its readers disagree about which properties §7 rules on: "
        f"{sorted(set(verdicts) ^ set(_RULING_FACTS))}"
    )
    for property_name, verdict in verdicts.items():
        assert verdict in _RULING_VERDICTS, (
            f"§7 rules {property_name!r} {verdict!r}, which no reader can interpret; "
            f"registered verdicts: {sorted(_RULING_VERDICTS)}"
        )
        claim_id = _RULING_FACTS[property_name]
        adopted = _RULING_VERDICTS[verdict]
        value = _CLAIMS[claim_id]()
        assert bool(value) == adopted, (
            f"§7 rules {property_name!r} {verdict!r}, so {claim_id} should be "
            f"{'non-zero' if adopted else 'zero'}; it recomputes to {_render(value)!r}"
        )


# The second ruling table: same discipline, a different question.  Its header is
# deliberately not §7's -- that one is asserted to occur exactly once, and a
# second table wearing the same header would merge two vocabularies into one.

_LEASE_RULING_HEADER = "| 问题 | 裁定 | 依据（可重算） |"

_LEASE_RULING_FACTS: dict[str, str] = {
    "两条修复路径取租约": "repair_paths_taking_the_lease",
    "取租约只保留一处实现": "lease_helper_definitions_in_the_runner",
    "给 ripple-retry 一个自己的键": "ripple_retry_task_registrations",
}


def _lease_ruling_verdicts() -> dict[str, str]:
    """``问题 -> 裁定``, read from §7's lease table in document order."""
    lines = _DOC_TEXT.splitlines()
    assert lines.count(_LEASE_RULING_HEADER) == 1, "expected exactly one lease ruling table"
    start = lines.index(_LEASE_RULING_HEADER) + 2  # skip the header and its separator
    verdicts: dict[str, str] = {}
    for line in lines[start:]:
        if not line.startswith("|"):
            break
        cells = line.strip().strip("|").split("|")
        assert len(cells) == 3, f"the lease ruling table changed shape: {line!r}"
        verdicts[_plain(cells[0])] = _plain(cells[1])
    assert verdicts, "the lease ruling table is empty"
    return verdicts


def test_the_lease_ruling_table_agrees_with_the_values_it_rules_on():
    """The adopted/refused halves of the lease ruling, both pinned.

    Same shape as the guard ruling above, one table over: an adopted property has
    to be present (non-zero), a refused one has to be absent (zero).  Without
    this, §7 could flip 采纳 to 不采纳 while the tree stayed put.
    """
    verdicts = _lease_ruling_verdicts()
    assert set(verdicts) == set(_LEASE_RULING_FACTS), (
        "the lease ruling table and its readers disagree about which questions it rules on: "
        f"{sorted(set(verdicts) ^ set(_LEASE_RULING_FACTS))}"
    )
    for question, verdict in verdicts.items():
        assert verdict in _RULING_VERDICTS, (
            f"§7 rules {question!r} {verdict!r}, which no reader can interpret; "
            f"registered verdicts: {sorted(_RULING_VERDICTS)}"
        )
        claim_id = _LEASE_RULING_FACTS[question]
        adopted = _RULING_VERDICTS[verdict]
        value = _CLAIMS[claim_id]()
        assert bool(value) == adopted, (
            f"§7 rules {question!r} {verdict!r}, so {claim_id} should be "
            f"{'non-zero' if adopted else 'zero'}; it recomputes to {_render(value)!r}"
        )


def _same_value(left: str, right: str) -> bool:
    return _render(_CLAIMS[left]()) == _render(_CLAIMS[right]())


# ── positive controls ────────────────────────────────────────────────────────
# ``ripple_retry_task_registrations`` is 0 and ``ripple_retry_submits_are_concurrent``
# is a bool: from the published value alone, "the scan is broken" and "the answer
# really is 0/false" look identical.  Each is therefore pointed at a fixture where
# it must answer the other way.


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _pkg(tmp_path: Path) -> Path:
    """A throwaway tree shaped like ``backend/`` so ``relative_to(REPO)`` is not asked."""
    (tmp_path / "api" / "routes").mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_the_consumer_scan_counts_a_call_and_not_a_docstring(tmp_path: Path):
    """Positive control for the two consumer counts.

    The fixture **discriminates**: one module names the predicate in a docstring
    and then calls it, one only calls it, and the defining module calls it too.
    A text scan answers 3, a scan that forgot *outside* answers 3, the real one
    answers 2.
    """
    root = _pkg(tmp_path)
    _write(
        root,
        "api/routes/_runner.py",
        "def process_has_active_task(thread_id):\n"
        '    """callers ask process_has_active_task before starting work"""\n'
        "    return False\n"
        "\n"
        "def has_active_execution(thread_id):\n"
        "    return process_has_active_task(thread_id)\n",
    )
    _write(
        root,
        "api/routes/_wf_actions.py",
        '"""process_has_active_task is mentioned here and that is not a call."""\n'
        "def guard(thread_id):\n"
        "    return process_has_active_task(thread_id)\n",
    )
    _write(
        root,
        "api/routes/_wf_application.py",
        "def upload(thread_id):\n    has_active = process_has_active_task(thread_id)\n",
    )
    outside = _call_sites(
        root, "process_has_active_task", outside=root / "api" / "routes" / "_runner.py"
    )
    assert len(outside) == 2, f"expected two consumers outside the defining module: {outside}"
    assert all("_runner.py" not in site for site in outside), outside
    assert outside[0].endswith("_wf_actions.py:3"), outside


def test_the_registration_scan_discriminates_registered_from_unregistered(tmp_path: Path):
    """Positive control for ``ripple_retry_task_registrations`` (published as 0).

    The fixture holds both shapes side by side, exactly as the real file does: a
    handler that stores the task it starts, and one that starts a task and drops
    it.  A scanner that always answers 1 fails on the first, one that always
    answers 0 fails on the second.
    """
    root = _pkg(tmp_path)
    module = _write(
        root,
        "api/routes/_wf_actions.py",
        "async def _run_retry() -> None:\n"
        "    return None\n"
        "\n"
        "async def _run_publish_retry() -> None:\n"
        "    return None\n"
        "\n"
        "def retry_ripple_analysis(thread_id):\n"
        "    task = asyncio.create_task(_run_retry())\n"
        "    return task\n"
        "\n"
        "def retry_publish(thread_id):\n"
        "    task = asyncio.create_task(_run_publish_retry())\n"
        "    _runner._background_tasks[thread_id] = task\n",
    )
    assert _registrations(module, "_run_retry") == 0
    assert _registrations(module, "_run_publish_retry") == 1


def test_the_concurrency_scan_answers_false_for_sequential_submits(tmp_path: Path):
    """Positive control for ``ripple_retry_submits_are_concurrent`` (published as ``true``).

    Without this fixture the claim could be a constant: a scan hard-wired to
    ``return True`` would publish the same value.  The sequential sample is the
    discriminating half -- same two ``submit_and_wait`` calls, awaited one after
    the other, which is a 3600 s window rather than an 1800 s one.
    """
    root = _pkg(tmp_path)
    gathered = _write(
        root,
        "gathered.py",
        "async def _run_retry():\n"
        "    pred_task = ripple.submit_and_wait({})\n"
        "    pmf_task = ripple.submit_and_wait({})\n"
        "    raw_pred, raw_pmf = await asyncio.gather(pred_task, pmf_task)\n",
    )
    sequential = _write(
        root,
        "sequential.py",
        "async def _run_retry():\n"
        "    pred_task = ripple.submit_and_wait({})\n"
        "    pmf_task = ripple.submit_and_wait({})\n"
        "    raw_pred = await pred_task\n"
        "    raw_pmf = await pmf_task\n",
    )
    assert _submits_are_concurrent(gathered, "_run_retry") is True
    assert _submits_are_concurrent(sequential, "_run_retry") is False


def test_the_done_callback_scan_can_see_a_callback(tmp_path: Path):
    """Positive control for ``ripple_retry_done_callbacks`` (published as 0).

    A scan that cannot see ``add_done_callback`` publishes 0 on the ripple path for
    the wrong reason, and from the value alone that is indistinguishable from the
    real answer.  The fixture holds both shapes side by side, as the real module
    does: the ripple handler starts a task and drops it, the publish handler starts
    a task and hangs a callback on it.  A scan hard-wired to either answer fails on
    the other half.
    """
    root = _pkg(tmp_path)
    module = _write(
        root,
        "api/routes/_wf_actions.py",
        "async def _run_retry() -> None:\n"
        "    return None\n"
        "\n"
        "async def _run_publish_retry() -> None:\n"
        "    return None\n"
        "\n"
        "def retry_ripple_analysis(thread_id):\n"
        "    return asyncio.create_task(_run_retry())\n"
        "\n"
        "def retry_publish(thread_id):\n"
        "    task = asyncio.create_task(_run_publish_retry())\n"
        "    task.add_done_callback(_on_task_done(thread_id))\n",
    )
    assert _done_callback_calls(module, "retry_ripple_analysis") == 0
    assert _done_callback_calls(module, "retry_publish") == 1


def test_the_self_cleanup_scan_only_counts_a_pop_inside_a_finally(tmp_path: Path):
    """Positive control for ``ripple_retry_self_cleanups`` (published as 0).

    The rule reads ``finalbody`` and nothing else, and this fixture is what makes
    that choice visible rather than arbitrary: both halves **contain** a ``pop``,
    and only one of them is a cleanup.  The other pops on the happy path and leaves
    the registry entry behind whenever the task is cancelled -- the single case the
    cleanup exists for.  A scan that walked the whole coroutine would answer 1 / 1.
    """
    root = _pkg(tmp_path)
    module = _write(
        root,
        "api/routes/_wf_actions.py",
        "def retry_publish(thread_id):\n"
        "    return asyncio.create_task(_run_publish_retry())\n"
        "\n"
        "def retry_ripple_analysis(thread_id):\n"
        "    return asyncio.create_task(_run_retry())\n"
        "\n"
        "async def _run_publish_retry():\n"
        "    try:\n"
        "        await work()\n"
        "    finally:\n"
        "        _background_tasks.pop(thread_id, None)\n"
        "\n"
        "async def _run_retry():\n"
        "    await work()\n"
        "    _background_tasks.pop(thread_id, None)\n",
    )
    assert _started_coroutine_cleans_up(module, "retry_publish") == 1
    assert _started_coroutine_cleans_up(module, "retry_ripple_analysis") == 0


def test_the_pairing_scan_finds_both_sides_and_ignores_unpaired_properties():
    """Positive control for the pairing itself.

    If ``_paired_claim_ids`` answered ``[]``, the difference assertion would pass
    over an empty set -- the shape of vacuity this file keeps running into.  The
    sample carries one paired property, two that §7 shows on one path only (the
    window and the concurrency answer), and one that is a §8 self-coverage row, so
    a scan that paired by prefix alone, or that invented a twin, is caught here.
    """
    sample = {
        "ripple_retry_done_callbacks": "0",
        "publish_retry_done_callbacks": "1",
        "ripple_retry_max_wait_seconds": "1800.0",
        "ripple_retry_submits_are_concurrent": "true",
        "line_number_references_in_this_document": "114",
    }
    assert _paired_claim_ids(sample) == [
        ("ripple_retry_done_callbacks", "publish_retry_done_callbacks")
    ]


def test_the_registry_scans_read_the_tree_they_are_pointed_at(tmp_path: Path):
    """Positive control for the three scans §7's ruling rests on.

    All three answer from ``BACKEND`` in production, so "the scan ignores its
    argument and reads the real tree" is indistinguishable from the published
    numbers -- and it would hand every later ruling today's counts.  The fixture
    therefore disagrees with the repository on all three answers: one write site
    instead of three, one reader-that-cancels instead of three (with a reader that
    only reads beside it, which a scan missing the ``cancel()`` half would count),
    and a list-valued registry instead of a single task.
    """
    root = _pkg(tmp_path)
    runner = _write(
        root,
        "api/routes/_runner.py",
        "_background_tasks: dict[str, list[asyncio.Task[Any]]] = {}\n"
        "\n"
        "def pause_workflow(thread_id):\n"
        "    bg = _background_tasks.get(thread_id)\n"
        "    if bg is not None:\n"
        "        bg.cancel()\n"
        "\n"
        "def status_of(thread_id):\n"
        "    return _background_tasks.get(thread_id)\n",
    )
    actions = _write(
        root,
        "api/routes/_wf_actions.py",
        "async def retry(thread_id, task, graph, config):\n"
        "    _background_tasks[thread_id] = asyncio.create_task(task)\n"
        "    await graph.aupdate_state(config, {})\n",
    )
    assert _registry_task_writes(root) == 1, "the write scan did not read its argument"
    assert _registry_readers_that_cancel(root) == 1, "the reader scan counts a reader"
    assert _registry_declared_value_type(runner) == "list[asyncio.Task[Any]]", (
        "the annotation scan did not read the file it was handed"
    )
    # The 0-claim beside them needs a control too: one call must be countable.
    assert _calls_within(actions, "aupdate_state") == 1
    assert _calls_within(actions, "start_lease") == 0


def test_the_criterion_and_pinning_scans_read_the_tree_they_are_pointed_at(tmp_path: Path):
    """Positive control for the five scans §7's criterion and its rows rest on.

    ``_writers_outside_the_entry`` and ``_own_task_writers`` both take a path and
    answer 20 / 2 from ``BACKEND`` in production; a version that ignored its
    argument would reproduce both numbers while pinning nothing -- and it would
    hand every later ruling today's counts.  The same is true of ``_definitions``,
    ``_if_tests_mentioning`` and ``_create_task_targets``, whose published values
    are 1 / 1 / 1 and would survive a hard-wired ``return 1``.  As with the
    registry scans above, the fixture is built to **disagree** with the repository
    on every answer, so "the scan read its argument" is what is being tested.

    Each scan has to answer more than one way:

    - ``_writers_outside_the_entry`` drops the entry's own write and keeps the
      three others -- one inline, one nested in a handler, one orphan.
    - ``_own_task_writers`` counts the handler whose nested coroutine writes and
      does **not** count the handler whose nested coroutine routes through the
      unified entry.  That difference *is* the criterion.  It answers 1 here and 2
      on the real module, which is the point.
    - ``_definitions`` separates a name defined twice from one defined once, and
      reaches a nested definition.
    - ``_if_tests_mentioning`` answers 2 where two branches test the flag, which is
      how we know the published 1 is measured rather than assumed.
    - ``_create_task_targets`` separates its callee from a second one, and answers
      0 for a callee that is only ever wrapped.
    """
    root = _pkg(tmp_path)
    module = _write(
        root,
        "api/routes/mixed.py",
        "async def _run_graph_and_persist(thread_id):\n"
        "    await graph.aupdate_state(config, {})\n"
        "\n"
        "async def inline_writer(thread_id):\n"
        "    await graph.aupdate_state(config, {})\n"
        "\n"
        "def _start_resume_task(thread_id):\n"
        "    async def _resume_async() -> None:\n"
        "        await _run_graph_and_persist(thread_id)\n"
        "    return asyncio.create_task(_resume_async())\n"
        "\n"
        "def retry_ripple_analysis(thread_id):\n"
        "    async def _run_retry() -> None:\n"
        "        await graph.aupdate_state(config, {})\n"
        "    return asyncio.create_task(_run_retry())\n"
        "\n"
        "async def _run_retry_orphan() -> None:\n"
        "    await graph.aupdate_state(config, {})\n"
        "\n"
        "def retry_publish(thread_id):\n"
        "    return asyncio.create_task(_execution_lease(_run_retry_orphan()))\n"
        "\n"
        "async def derive_status(thread_id):\n"
        "    if has_active_task(thread_id):\n"
        "        return 10\n"
        "    if not has_active_task(thread_id):\n"
        "        return 9\n"
        "    return 0\n"
        "\n"
        "def helper(thread_id):\n"
        "    return 1\n"
        "\n"
        "def helper(thread_id):\n"
        "    return 2\n",
    )
    # the three writes that are not the entry's own: :5 inline, :14 nested, :18 orphan
    outside = _writers_outside_the_entry(module, "_run_graph_and_persist")
    assert sorted(site.rsplit(":", 1)[1] for site in outside) == ["14", "18", "5"], outside
    ledger = _own_task_writers(module)
    assert ledger == 1, f"the criterion scan counted {ledger} handlers, not just the writer"
    assert _definitions(module, "helper") == 2
    assert _definitions(module, "_run_retry") == 1
    assert _if_tests_mentioning(module, "derive_status", "has_active_task") == 2
    assert _create_task_targets(module, "_run_retry") == 1
    assert _create_task_targets(module, "_run_retry_orphan") == 0


def test_the_lease_reason_scans_can_answer_something_other_than_their_value(
    tmp_path: Path,
):
    """Positive control for the five scans the refusal claims rest on.

    Their published values are 3 / 1 / 3 / 2 / 3 -- every one small enough to be
    hard-wired.  A ``return 3`` would keep the document green forever while pinning
    nothing, and the document is the only reader these scans have.  So each is
    pointed at a module built to **disagree** with the repository and, where it
    matters, to hold the shape a careless scan would confuse with the one it wants.

    - ``_enum_members`` sees a fourth member: it counts names, so a non-name target
      in the class body is not a member.
    - ``_tests_for_a_member`` counts the **branch**, not the attribute.
      ``HELD_BY_LIVE_OWNER`` appears twice in this fixture and only one occurrence
      is a comparison -- which is the whole difference between 2 and 3 on the real
      module.
    - ``_refusal_reason_names`` drops a non-string constant and drops the kind
      (``ACTION_EVENT_KIND``), leaving the one reason.
    - ``_definitions`` separates a name defined twice from a name defined never.
    """
    root = _pkg(tmp_path)
    module = _write(
        root,
        "lease_like.py",
        "class AcquireOutcome(StrEnum):\n"
        "    GRANTED = 'granted'\n"
        "    HELD_BY_LIVE_OWNER = 'held_by_live_owner'\n"
        "    UNKNOWN = 'unknown'\n"
        "    EXTRA = 'extra'\n"
        "\n"
        "async def acquire_outcome(thread_id):\n"
        "    if lease.outcome is AcquireOutcome.HELD_BY_LIVE_OWNER:\n"
        "        return AcquireOutcome.HELD_BY_LIVE_OWNER.value\n"
        "    return None\n"
        "\n"
        "async def acquire_outcome(thread_id):\n"
        "    return None\n"
        "\n"
        "ACTION_EVENT_KIND = 'action'\n"
        "ACTION_POLICY_DENIED = 'policy_denied'\n"
        "ACTION_NOT_A_STRING = 1\n",
    )
    assert _enum_members(module, "AcquireOutcome") == 4
    assert _tests_for_a_member(module, "AcquireOutcome", "HELD_BY_LIVE_OWNER") == 1
    assert _refusal_reason_names(module) == 1
    assert _definitions(module, "acquire_outcome") == 2
    assert _definitions(module, "acquire") == 0


def test_the_renew_scans_can_answer_something_other_than_their_value(tmp_path: Path):
    """Positive control for the scans the renewal claims rest on.

    Three of them are the shapes this file exists to distrust, and each is what a
    careless scan answers by accident:

    - ``renew_call_sites_under_backend`` is 0, so the fixture has to contain a
      ``renew(`` call for the scan to be shown answering anything at all -- and
      the ``renew_outcome(`` calls next to it are there to catch the opposite
      mistake, a prefix match that would report a larger number.
    - ``transient_failures_the_owner_tolerates`` is recomputed from a *derivation*,
      so it runs against a fixture whose ``HEARTBEAT_MISSES_BEFORE_EXPIRY`` is 5
      and must answer 3: the real tree's 1 cannot tell a recomputation from a
      hard-coded ``1``, which is exactly the mutation worth catching.
    - ``the_budget_never_covers_the_evidenced_answer`` reads *ordering*, so the
      fixture has to hold the wrong order (budget consulted first -- the ruling
      backwards) and a loop that never mentions the budget at all, both of which
      must answer ``False``, **and** the right order, which must answer ``True``.
      Two definitions of that name again, so the scan has to take the first.
    - ``misses_the_scanner_tolerates`` performs the ``- 1`` itself, so the control
      has to call the same function rather than repeat the arithmetic.
    """
    root = _pkg(tmp_path)
    module = _write(
        root,
        "lease_like.py",
        "HEARTBEAT_MISSES_BEFORE_EXPIRY = 5\n"
        "HEARTBEAT_TRANSIENT_FAILURES_TOLERATED = HEARTBEAT_MISSES_BEFORE_EXPIRY - 2\n"
        "\n"
        "class RenewOutcome(StrEnum):\n"
        "    RENEWED = 'renewed'\n"
        "    LOST = 'lost'\n"
        "    UNKNOWN = 'unknown'\n"
        "\n"
        "async def someone_else(thread_id):\n"
        "    return await renew(thread_id)\n"
        "\n"
        "async def _heartbeat_wrong_direction(thread_id):\n"
        "    outcome = await renew_outcome(thread_id)\n"
        "    if outcome is RenewOutcome.LOST:\n"
        "        return outcome\n"
        "\n"
        "async def _heartbeat_budget_covers_everything(thread_id):\n"
        "    misses = 0\n"
        "    while True:\n"
        "        outcome = await renew_outcome(thread_id)\n"
        "        misses += 1\n"
        "        if misses > HEARTBEAT_TRANSIENT_FAILURES_TOLERATED:\n"
        "            return outcome\n"
        "        if outcome is RenewOutcome.LOST:\n"
        "            return outcome\n"
        "\n"
        "async def _heartbeat_until_cancelled(thread_id):\n"
        "    misses = 0\n"
        "    while True:\n"
        "        outcome = await renew_outcome(thread_id)\n"
        "        if outcome is RenewOutcome.LOST:\n"
        "            return outcome\n"
        "        misses += 1\n"
        "        if misses > HEARTBEAT_TRANSIENT_FAILURES_TOLERATED:\n"
        "            return outcome\n"
        "\n"
        "async def _heartbeat_until_cancelled(thread_id):\n"
        "    outcome = await renew_outcome(thread_id)\n"
        "    return outcome\n",
    )
    assert _enum_members(module, "RenewOutcome") == 3
    assert _misses_the_scanner_tolerates(module) == 4
    assert _transient_failures_the_owner_tolerates(module) == 3
    assert (
        _the_budget_never_covers_the_evidenced_answer(module, "_heartbeat_budget_covers_everything")
        is False
    )
    assert (
        _the_budget_never_covers_the_evidenced_answer(module, "_heartbeat_wrong_direction") is False
    )
    # The right order, under the name the claim points at -- and the second
    # definition of that name is the shape that must answer False, so this also
    # proves the scan takes the first one.
    assert (
        _the_budget_never_covers_the_evidenced_answer(module, "_heartbeat_until_cancelled") is True
    )
    assert _definitions(module, "_heartbeat_until_cancelled") == 2
    assert _definitions(module, "renew_outcome") == 0
    # The prefix trap, both ways round: the boolean scan does not see the named
    # question's calls, and the named scan does not see the boolean one.
    assert len(_call_sites(root, "renew")) == 1
    assert len(_call_sites(root, "renew_outcome")) == 4
