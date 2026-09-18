"""Recompute every claim the two ``## 已知残留`` sections publish.

Three registries in this repo pin what they assert, each in the shape that fits it:
``docs/execution-plane.md`` publishes *locations* and is pinned by ``file:line``
anchors (``test_docs_anchors.py``); ``docs/planning.md`` and
``docs/outcome-learning.md`` publish *values* and are pinned by claim tables; a
few facts are pinned by a plain assertion where they live (the two JSON parsers,
``ROUTERS_WITHOUT_AN_EDGE``).

Residue lists were the one shape with no pin at all. ``docs/publish-action-protocol.md``
and ``docs/tool-runtime.md`` each end with a ``## 已知残留`` section whose every
line is a fact about the tree -- *how many call sites still bypass the control
plane, how many readers a declared set still lacks, how many writers a table
still lacks* -- and nothing went red when one of them stopped being true. That is
the same failure this repo already paid for once: an item registered as open was
resolved inside its own ticket and the record kept claiming it was open (see
``test_brief_mode_creating_routes_to_the_copywriter``). Prose is not a pin.

The closed loop is the one ``test_planning_claims.py`` established:

1. every published claim recomputes to the value next to it;
2. every published claim has a recalculator here;
3. every recalculator here is published in at least one of the two documents.

One rule is added, because half the claims here are **zero**: a claim whose value
is 0 has no built-in control -- a scanner gutted to ``return []`` keeps publishing
0 and stays green. So every zero-valued scan is pointed, in a fixture, at a tree
where the thing it looks for *is* present. Two of those fixtures are built to
**discriminate**: one contains a comment mentioning ``EVENT_KINDS`` as well as a
real import, the other a ``SELECT`` as well as an ``INSERT``, so a scanner that
counted text instead of syntax answers 2 and the fixture catches it.

Deliberately absent from the table: the L1 parameter-normalisation item in
``docs/tool-runtime.md``. It is a design judgement, not a shape of the tree, so it
gets no predicate -- a predicate that cannot fail is a receipt for a check nobody
ran.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.tools.runtime.audit import _ALLOWED_PREFIX

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
API_ROUTES = BACKEND / "api" / "routes"
CONTROL_PLANE = BACKEND / "creator_agent"
EVENT_KINDS_MODULE = BACKEND / "db" / "workflow_events.py"

DOCS: tuple[Path, ...] = (
    REPO / "docs" / "publish-action-protocol.md",
    REPO / "docs" / "tool-runtime.md",
)

_CLAIM_BLOCK = re.compile(r"<!-- claim-table:begin -->(.*?)<!-- claim-table:end -->", re.DOTALL)
# A row looks like `| `id` | `value` | prose |` -- only the first two cells carry
# meaning.  Header and separator rows have no backticks, so they drop.
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def _render(value: Any) -> str:
    """The published spelling of a recomputed value.

    Sets, lists and tuples are sorted and joined so a claim about *which* things
    are in a collection can be published without depending on iteration order
    that nothing guarantees.
    """
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(sorted(str(item) for item in value))
    return str(value)


# ── source scans ─────────────────────────────────────────────────────────────
# Every scan takes ``root`` so the positive controls below can point the same
# code at a tree where the thing it looks for exists.  A scan that cannot be
# pointed anywhere is a scan nobody can prove is working.


def _trees(root: Path) -> list[tuple[Path, ast.Module]]:
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"))) for path in sorted(root.rglob("*.py"))
    ]


def _show(path: Path) -> str:
    """A path as reported in a claim: repo-relative where it can be.

    ``relative_to`` raises for a path outside the repo, and the positive-control
    fixtures are exactly that -- a scanner that only worked on paths under the
    repo could not be pointed anywhere, so it could never be proved to work.
    """
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _run_publish_calls(root: Path = BACKEND) -> list[Path]:
    """Call sites of ``run_publish`` as bare names or attributes.

    The ``async def run_publish`` header is not a ``Call`` node, so the one
    definition in the tree excludes itself -- no special case needed, which is
    exactly what makes this a shape and not a guess.
    """
    found: list[Path] = []
    for path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
                if name == "run_publish":
                    found.append(path)
    return sorted(found)


def _action_intent_constructions(root: Path = BACKEND) -> list[Path]:
    """Every place that builds an ``ActionIntent``.

    The plan row called this object ``PublishIntent``; the realised name is
    ``ActionIntent`` and ``PublishIntent`` does not occur in ``backend/`` at all.
    A claim that names an object the tree does not have is worth less than no
    claim, so this scan answers for the realised name.
    """
    found: list[Path] = []
    for path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ActionIntent":
                found.append(path)
    return sorted(found)


def _outside(control_plane: Path, paths: list[Path]) -> list[Path]:
    """Paths not under ``control_plane``.

    Compared as paths -- ``str(path).startswith(...)`` would be false on Windows
    for a differently-cased or slash-shaped prefix and would silently report
    every producer as an outside one.
    """
    return [path for path in paths if control_plane not in path.parents]


def _names_event_kinds(node: ast.AST) -> bool:
    """Whether ``node`` mentions the constant in one of the two shapes that count.

    ``from ... import EVENT_KINDS`` and a bare ``EVENT_KINDS`` reference are both
    reads; a string that happens to spell it is neither, and neither is the
    module it is defined in (the caller excludes that one).
    """
    if isinstance(node, ast.ImportFrom):
        return any(alias.name == "EVENT_KINDS" for alias in node.names)
    return isinstance(node, ast.Name) and node.id == "EVENT_KINDS"


def _event_kinds_readers(
    root: Path = BACKEND, defining: Path | None = EVENT_KINDS_MODULE
) -> list[Path]:
    """Modules that import or name ``EVENT_KINDS``, minus the module defining it.

    Syntax, not text: a docstring or comment that mentions the constant is not a
    reader, and the one place in the tree that mentions it in prose
    (``backend/state/events.py``) is a docstring.  Counting mentions would answer
    a different question than the document asks.
    """
    found: list[Path] = []
    for path, tree in _trees(root):
        if defining is not None and path.resolve() == defining.resolve():
            continue
        if any(_names_event_kinds(node) for node in ast.walk(tree)):
            found.append(path)
    return sorted(set(found))


_INSERT_INTO_CREDENTIALS = re.compile(r"INSERT\s+INTO\s+(?:public\.)?account_credentials", re.I)


def _credential_inserts(root: Path = BACKEND) -> list[str]:
    """``path:line`` for every ``INSERT INTO account_credentials``.

    The table is used three other ways in the tree -- a ``CREATE TABLE``, a
    ``SELECT``, and a ``DELETE`` that strips system keys -- and none of them is a
    writer of credentials.  A scan for the table name alone would answer 3 and
    turn a true claim into a false one.
    """
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _INSERT_INTO_CREDENTIALS.finditer(text):
            line = text[: match.start()].count("\n") + 1
            found.append(f"{_show(path)}:{line}")
    return sorted(found)


def _ripple_service_importers(root: Path = API_ROUTES) -> list[Path]:
    """API-route modules that import ``RippleService``."""
    found: list[Path] = []
    for path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and any(
                a.name == "RippleService" for a in node.names
            ):
                found.append(path)
    return sorted(set(found))


_DIRECT_SUBMIT = re.compile(r"\.submit_and_wait\(")


def _ripple_direct_call_sites(root: Path = API_ROUTES) -> list[str]:
    """``path:line`` for direct ``.submit_and_wait(`` calls in the API routes.

    The service's own internal calls (``ripple_service.py``) are a different
    question and live in a different directory, so they are out of scope by
    construction rather than by an exclusion list.
    """
    found: list[str] = []
    for path in sorted(root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in _DIRECT_SUBMIT.finditer(text):
            line = text[: match.start()].count("\n") + 1
            found.append(f"{_show(path)}:{line}")
    return sorted(found)


# ── the recalculators, one per published claim ───────────────────────────────

_CLAIMS: dict[str, Callable[[], Any]] = {
    # docs/publish-action-protocol.md -- "主链仍不经控制面"
    "mainline_run_publish_direct_call_sites": lambda: len(_run_publish_calls()),
    "action_intent_construction_sites": lambda: len(_action_intent_constructions()),
    "mainline_action_intent_producers": lambda: len(
        _outside(CONTROL_PLANE, _action_intent_constructions())
    ),
    # docs/publish-action-protocol.md -- "EVENT_KINDS 仍没有读者"
    "event_kinds_readers_outside_its_defining_module": lambda: len(_event_kinds_readers()),
    # both documents -- "account_credentials 仍无写入者"
    "account_credentials_inserts": lambda: len(_credential_inserts()),
    # docs/tool-runtime.md -- the ripple-retry route bypasses the Gateway
    "api_route_modules_importing_ripple_service": lambda: len(_ripple_service_importers()),
    "ripple_service_direct_call_sites_in_api_routes": lambda: len(_ripple_direct_call_sites()),
    "tool_gate_allowed_prefix": lambda: _ALLOWED_PREFIX,
}


def _published(doc: Path) -> dict[str, str]:
    """The ``id -> value`` rows of every claim block in one document."""
    rows: dict[str, str] = {}
    for block in _CLAIM_BLOCK.findall(doc.read_text(encoding="utf-8")):
        for claim_id, value in _ROW.findall(block):
            assert claim_id not in rows, f"{doc.name} publishes {claim_id} twice"
            rows[claim_id] = value
    return rows


def _published_anywhere() -> dict[str, str]:
    """``id -> value`` across both documents, refusing a disagreement.

    ``account_credentials_inserts`` is published in both on purpose -- each
    document has to be readable on its own -- so the two rows have to agree or
    the duplication has already rotted.
    """
    rows: dict[str, str] = {}
    for doc in DOCS:
        for claim_id, value in _published(doc).items():
            if claim_id in rows:
                assert rows[claim_id] == value, (
                    f"{claim_id} is published as {rows[claim_id]!r} in one document and "
                    f"{value!r} in another"
                )
            rows[claim_id] = value
    return rows


def test_both_documents_have_balanced_markers_and_carry_rows():
    """A lost marker would silently hide rows from every check below."""
    for doc in DOCS:
        text = doc.read_text(encoding="utf-8")
        begins = text.count("<!-- claim-table:begin -->")
        ends = text.count("<!-- claim-table:end -->")
        assert begins == ends, f"{doc.name}: {begins} begin marker(s) vs {ends} end marker(s)"
        assert begins > 0, f"{doc.name}: no claim block -- every check below would be vacuous"
        assert _published(doc), f"{doc.name}: the claim block holds no `id | value` rows"


def test_every_published_claim_recomputes_to_the_value_it_publishes():
    complaints = []
    for doc in DOCS:
        for claim_id, published in _published(doc).items():
            recalculate = _CLAIMS.get(claim_id)
            if recalculate is None:
                continue  # reported by the next test, with a better message
            actual = _render(recalculate())
            if actual != published:
                complaints.append(
                    f"{doc.name}: {claim_id} publishes {published!r} but recomputes to {actual!r}"
                )
    detail = "\n  ".join(complaints)
    assert not complaints, (
        "a residue claim no longer holds. Either the residue was fixed -- in which case "
        f"update the document and this table -- or the scan is wrong:\n  {detail}"
    )


def test_no_claim_is_published_without_a_recalculator():
    """A row without a checker is a number nobody re-tests -- the whole point."""
    orphans = sorted(set(_published_anywhere()) - set(_CLAIMS))
    assert not orphans, (
        "these claims are published but nothing recomputes them; add them to "
        f"_CLAIMS or drop them from the documents: {orphans}"
    )


def test_no_recalculator_is_left_behind_by_the_documents():
    """The backward direction: a dropped row shows up as an orphaned checker."""
    missing = sorted(set(_CLAIMS) - set(_published_anywhere()))
    assert not missing, (
        f"these claims have a recalculator but are published in neither document: {missing}"
    )


# ── positive controls ────────────────────────────────────────────────────────
# Three of the claims above answer 0.  For those, "the scanner is broken" and "the
# scan found nothing" are indistinguishable from the published value alone, so
# each one is pointed at a fixture where the answer is 1.  The remaining claims
# (3, 1, 2, and a prefix string) cannot be 0 in a working scanner, so a gutted
# scanner makes them disagree with their published value -- they control
# themselves, and a fixture for them would prove nothing extra.


def _write(root: Path, name: str, body: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_the_mainline_producer_scan_finds_one_outside_the_control_plane(tmp_path: Path):
    """Positive control for ``mainline_action_intent_producers``.

    The fixture **discriminates**: it holds one construction inside a control
    plane and one outside, so a scan that forgot the ``_outside`` filter answers
    2, and one that only looked at the control plane answers 0.
    """
    inside = _write(tmp_path, "control/advisor.py", "action = ActionIntent()\n")
    outside = _write(tmp_path, "mainline/publisher.py", "action = ActionIntent()\n")
    constructions = _action_intent_constructions(tmp_path)
    assert len(constructions) == 2, f"expected both constructions: {constructions}"
    producers = _outside(tmp_path / "control", constructions)
    assert producers == [outside], f"expected only the one outside the control plane: {producers}"
    assert inside not in producers


def test_the_event_kinds_scanner_counts_an_import_and_not_a_comment(tmp_path: Path):
    """Positive control for ``event_kinds_readers_outside_its_defining_module``.

    The fixture **discriminates**: it mentions the constant in a docstring *and*
    imports it. A scanner that counted text answers 2; the AST scan answers 1.
    """
    importer = _write(
        tmp_path,
        "reader.py",
        '"""EVENT_KINDS is mentioned right here and that is not a read."""\n'
        "from backend.db.workflow_events import EVENT_KINDS\n"
        "\n"
        "def kinds() -> frozenset[str]:\n"
        "    return EVENT_KINDS\n",
    )
    readers = _event_kinds_readers(tmp_path, defining=None)
    assert readers == [importer], f"expected the one importer and not the docstring: {readers}"


def test_the_credential_scanner_counts_an_insert_and_not_a_read(tmp_path: Path):
    """Positive control for ``account_credentials_inserts``.

    The fixture **discriminates**: one ``INSERT``, one ``SELECT`` and one
    ``CREATE TABLE`` against the same table. A scanner matching the *table name*
    answers 3; the scan asks the question the document asks and answers 1.
    """
    writer = _write(
        tmp_path,
        "store.py",
        "DDL = 'CREATE TABLE IF NOT EXISTS account_credentials (account_id text)'\n"
        "READ = 'SELECT cookie FROM account_credentials WHERE account_id = %s'\n"
        "WRITE = 'INSERT INTO account_credentials (account_id, key_name) VALUES (%s, %s)'\n",
    )
    inserts = _credential_inserts(tmp_path)
    assert len(inserts) == 1, f"expected only the INSERT: {inserts}"
    assert inserts[0].endswith("store.py:3"), f"expected line 3 -- the INSERT: {inserts}"
    assert writer.exists()
