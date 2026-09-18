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

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "execution-plane.md"
BACKEND = REPO / "backend"
RUNNER = BACKEND / "api" / "routes" / "_runner.py"
ACTIONS = BACKEND / "api" / "routes" / "_wf_actions.py"

_CLAIM_BLOCK = re.compile(r"<!-- claim-table:begin -->(.*?)<!-- claim-table:end -->", re.DOTALL)
_ANCHOR_TABLES = re.compile(
    r"<!-- (?:anchor-table|anchor-absence):begin -->(.*?)"
    r"<!-- (?:anchor-table|anchor-absence):end -->",
    re.DOTALL,
)
# A row looks like `| `id` | `value` | prose |` -- only the first two cells carry
# meaning.  Header and separator rows have no backticks, so they drop.
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)

# The two shapes a cited line number takes.  They are disjoint: the first needs
# at least one path character before the colon, the second has none.  The first
# also accepts a range (`path:357-359`), because prose uses ranges and a pattern
# that cannot see one would silently skip both ends -- the same hole an extension
# whitelist made for `Dockerfile:81`.
_PATH_LINE = re.compile(r"`([A-Za-z0-9_./-]+):(\d+)(?:-(\d+))?`")
_BARE_LINE = re.compile(r"`:(\d+)`")


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


# ── document scans ───────────────────────────────────────────────────────────


def _cited(text: str) -> tuple[list[tuple[str, str, str | None]], list[int]]:
    """Every cited line number in *text*: ``path``/start/end triples, and bare lines.

    A range counts as one citation here and as two checked ends in :func:`_rot` --
    the count answers "how much prose cites the tree", the check answers "does it
    still point there".
    """
    return _PATH_LINE.findall(text), [int(n) for n in _BARE_LINE.findall(text)]


def _size(root: Path, relative: str) -> int | None:
    target = root / relative
    if not target.is_file():
        return None
    return len(target.read_text(encoding="utf-8", errors="replace").splitlines())


def _citations(line: str) -> list[tuple[int, str, re.Match[str]]]:
    """Every citation on one line, **in the order it appears**.

    Order is the whole semantics of a bare ``:N``: it means the path that precedes
    it *in the line*.  A line can cite two files -- §0 does, ``..._wf_application.py:271
    ... :275 ... _wf_models.py:31`` -- so collecting every path first and every
    bare number second attributes the bare one to the wrong file.  (This test
    caught exactly that in its own first version: it reported ``:275`` as past the
    end of a 195-line file that the line only mentions *after* it.)
    """
    items = [(match.start(), "path", match) for match in _PATH_LINE.finditer(line)]
    items += [(match.start(), "bare", match) for match in _BARE_LINE.finditer(line)]
    return sorted(items, key=lambda item: item[0])


def _rot(text: str, root: Path) -> list[str]:
    """Every way a cited line number can fail to resolve, as readable complaints.

    Five forms, all of them real: a path that is not there (``_takeover.py:136`` --
    a basename where the line above it has the full path), a line past the end
    (``:3008`` in a 371-line file), a bare reference attributed past the end, a
    bare reference with no path before it to attribute it to, and a range whose
    ends disagree with the file.
    """
    problems: list[str] = []
    section = ""
    last: str | None = None
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("## "):
            section, last = line.strip(), None
        for _, kind, match in _citations(line):
            if kind == "path":
                path, start, end = match.group(1), int(match.group(2)), match.group(3)
                last = path
                size = _size(root, path)
                if size is None:
                    problems.append(f":{number} {path}:{start} -> no such file")
                    continue
                if end is None:
                    if not 0 < start <= size:
                        problems.append(f":{number} {path}:{start} -> past the end ({size} lines)")
                    continue
                stop = int(end)
                if start > stop:
                    problems.append(f":{number} {path}:{start}-{stop} -> the range runs backwards")
                    continue
                for cited in (start, stop):
                    if not 0 < cited <= size:
                        problems.append(
                            f":{number} {path}:{start}-{stop} -> {cited} is past the end "
                            f"({size} lines)"
                        )
                        break
                continue
            bare = int(match.group(1))
            if last is None:
                problems.append(f":{number} :{bare} -> bare, no path before it in {section!r}")
                continue
            size = _size(root, last)
            if size is not None and not 0 < bare <= size:
                problems.append(f":{number} :{bare} -> {last} past the end ({size} lines)")
    return problems


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
    trusting it.  The lease is deliberately not a pair: §7 shows it as two zeros,
    and zeros on both sides are not a difference.
    """
    ids = set(published)
    pairs: list[tuple[str, str]] = []
    for name in sorted(ids):
        if not name.startswith("ripple_retry_"):
            continue
        twin = "publish_retry_" + name[len("ripple_retry_") :]
        if twin in ids:
            pairs.append((name, twin))
    return pairs


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
    # §8 -- how much of this document its own tables actually cover
    "line_number_references_in_this_document": lambda: sum(len(part) for part in _cited(_DOC_TEXT)),
    "line_numbers_pinned_by_marked_tables": lambda: len(_pinned_rows(_DOC_TEXT)),
    "bare_line_number_references_in_this_document": lambda: len(_cited(_DOC_TEXT)[1]),
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


def test_every_cited_line_number_in_this_document_resolves():
    """The second tier: resolvable and in range, for every reference in the document.

    The count itself is not repeated here: the document publishes it, and a copy in
    a docstring is a second writer that nobody recomputes.
    """
    problems = _rot(_DOC_TEXT, REPO)
    detail = "\n  ".join(problems)
    assert not problems, (
        "docs/execution-plane.md cites line numbers that do not resolve. Write the full "
        f"repo-relative path -- a bare basename resolves against nothing:\n  {detail}"
    )


# ── the difference itself ────────────────────────────────────────────────────
# Everything above pins each property's value one at a time.  None of it says the
# two paths *differ*: six independent value claims would all still hold if the tree
# moved to 1 / 1, and the document would be left applying the word 差异 to two
# handlers that are the same.  This is the assertion that makes the word true.


def test_the_two_repair_paths_differ_on_every_property_the_document_pairs():
    pairs = _paired_claim_ids(_published())
    assert len(pairs) == 4, (
        "§7 shows four properties on both repair paths; the document currently pairs "
        f"{len(pairs)} of them: {pairs}"
    )
    same = [f"{left} == {right}" for left, right in pairs if _same_value(left, right)]
    assert not same, (
        "§7 exists to say these two handlers are not the same shape, but the document "
        f"pairs properties that recompute to equal values: {same}. Either the tree "
        "changed -- then §7's table is wrong -- or the pairing is."
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


def test_the_line_number_rule_reports_all_four_ways_a_reference_rots(tmp_path: Path):
    """Positive control for the resolvability rule itself.

    A rule that returned ``[]`` would keep every reference in the document "fine".  The fixture
    is a miniature of the real document's damage, one section per failure mode:
    a basename with no directory, a line past the end, a bare reference past the
    end, and a bare reference with nothing before it to attribute it to.
    """
    root = _pkg(tmp_path)
    _write(root, "backend/api/routes/_takeover.py", "x = 1\ny = 2\n")
    _write(root, "backend/api/routes/_wf_actions.py", "\n".join(f"line {n}" for n in range(1, 12)))
    text = (
        "## 1. first\n"
        "\n"
        "`_takeover.py:2` is a basename\n"
        "\n"
        "## 2. second\n"
        "\n"
        "`backend/api/routes/_takeover.py:9` is past the end\n"
        "\n"
        "## 3. third\n"
        "\n"
        "`backend/api/routes/_wf_actions.py:4` is fine, then `:99` is not\n"
        "\n"
        "## 4. fourth\n"
        "\n"
        "`:3` has nothing before it\n"
    )
    problems = _rot(text, root)
    assert len(problems) == 4, f"every failure mode must be reported: {problems}"
    assert any("no such file" in p for p in problems), problems
    assert any("past the end (2 lines)" in p for p in problems), problems
    assert any("_wf_actions.py past the end (11 lines)" in p for p in problems), problems
    assert any("no path before it" in p for p in problems), problems
    # and the healthy half of the same fixture is silent -- a rule that flagged
    # every reference would satisfy the four assertions above and prove nothing
    healthy = _rot("## 1. first\n\n`backend/api/routes/_takeover.py:2` is fine\n", root)
    assert healthy == [], healthy


def test_a_bare_reference_belongs_to_the_path_before_it_on_its_own_line(tmp_path: Path):
    """A line can cite two files; the bare number belongs to the first one.

    This is the rule's own first bug, and it was found by running it against the
    real document: §0 cites ``_wf_application.py:271`` then ``:275`` then
    ``_wf_models.py:31`` on one line, and a version that collected every path
    first and every bare number second attributed ``:275`` to the 195-line file
    the line only mentions *afterwards*.

    The fixture **discriminates**: ``:9`` resolves inside the 11-line file but is
    past the end of the 3-line one, so a misattributing rule cannot stay silent
    here.  The second half pins the direction -- the complaint must name the file
    the number actually follows.
    """
    root = _pkg(tmp_path)
    _write(root, "backend/api/routes/_wf_application.py", "\n".join(f"l{n}" for n in range(1, 12)))
    _write(root, "backend/api/routes/_wf_models.py", "\n".join(f"l{n}" for n in range(1, 4)))
    line = (
        "`backend/api/routes/_wf_application.py:4` then `:9` "
        "then `backend/api/routes/_wf_models.py:2`\n"
    )
    assert _rot("## 1. one line, two files\n\n" + line, root) == [], "both references resolve"

    past = line.replace("`:9`", "`:99`")
    problems = _rot("## 1. one line, two files\n\n" + past, root)
    assert len(problems) == 1, problems
    assert "_wf_application.py past the end (11 lines)" in problems[0], problems[0]


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
