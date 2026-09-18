"""Recompute every claim ``docs/outcome-learning.md`` publishes.

``docs/execution-plane.md`` publishes *locations*, so it is pinned with
``file:line`` anchors (``test_docs_anchors.py``).  ``docs/outcome-learning.md``
publishes *facts* -- which keys a weak label is made of, how many writers attach
it, how many sync entries funnel into the one attach point, what the refit
threshold is, and which column the refit window filters on.  A fact does not
drift, it gets *changed*: pinning those by location would build a net that goes
red when a line moves and stays green when a number changes.

The document's markers ("claim blocks") hold ``id -> published value`` rows, and
the four checks are a closed loop:

1. every published claim recomputes to the value next to it;
2. every published claim has a recalculator here (a new row needs one);
3. every recalculator here is published there (a dropped row leaves an orphan,
   which is why no row-count floor is needed);
4. the marker pairs are balanced (a lost marker hides a whole block from 1-3).

Two things are worth calling out about the scans below.

**Two ``label_source`` spellings, two claims.**  The insert paths pass the label
as a keyword argument (``label_source="evaluator"``) and the attach path writes
it inside shared SQL (``ENGAGEMENT_LABEL_SOURCE``).  No single scan covers both,
so each has its own claim rather than one claim pretending to be whole -- the
failure mode P3-S3's mutation self-check caught was exactly a checker answering
for a statement it was not actually reading.

**Claims about an absence need a control.**  ``attach_selector_does_not_skip_
labeled_rows`` and ``count_ignores_when_the_label_arrived`` both publish
``true`` because a condition is *not* there: a scanner gutted to ``return
False`` -- or to returning no constants at all -- would keep both green.  So
those scans read a function's own string constants through ``_sql_omits``,
whose two directions are exercised at the end of this file.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Callable
from dataclasses import fields
from pathlib import Path
from typing import Any

from backend.db.evaluator_config import (
    DEFAULT_DIMENSION_WEIGHTS,
    ENGAGEMENT_LABEL_SOURCE,
    MIN_EVOLVE_SAMPLES,
    WEAK_LABEL_METRIC_KEYS,
    WEIGHTED_DIMENSIONS,
)
from backend.services.creator_stats.types import NoteStats

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "outcome-learning.md"
BACKEND = REPO / "backend"
CONFIG = BACKEND / "db" / "evaluator_config.py"
PIPELINE = BACKEND / "services" / "creator_stats" / "pipeline.py"

_BLOCK = re.compile(r"<!-- claim-table:begin -->(.*?)<!-- claim-table:end -->", re.DOTALL)
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def _render(value: Any) -> str:
    """The published spelling of a recomputed value (sorted, for set-like ones)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(sorted(str(item) for item in value))
    return str(value)


# ── source scans ─────────────────────────────────────────────────────────────
# ``root`` is a parameter on the ones that look for something so the positive
# controls at the end of this file can point the same code somewhere the thing
# *does* exist.


def _trees(root: Path) -> list[ast.Module]:
    """Every parsed module under ``root`` -- the path is not what callers need."""
    return [ast.parse(path.read_text(encoding="utf-8")) for path in sorted(root.rglob("*.py"))]


def _function(path: Path, name: str) -> ast.AST:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in {path.name}")


def _functions_mentioning(path: Path, needle: str) -> frozenset[str]:
    """Names of the functions whose body mentions ``needle``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return frozenset(
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and needle in ast.unparse(node)
    )


def _calls_of(path: Path, name: str, *, inside: str | None = None) -> tuple[str, ...]:
    """``path:line`` for every call to ``name``, optionally only inside a function."""
    scope: ast.AST = _function(path, inside) if inside else ast.parse(path.read_text("utf-8"))
    found = []
    for node in ast.walk(scope):
        func = getattr(node, "func", None)
        if isinstance(func, ast.Name) and func.id == name:
            found.append(f"{path.relative_to(REPO).as_posix()}:{node.lineno}")
    return tuple(sorted(found))


def _body_source(path: Path, name: str) -> str:
    """The function's body as source (comments dropped -- only code counts)."""
    return ast.unparse(_function(path, name))


def _string_constants(path: Path, name: str) -> str:
    """Every string literal in the function's body, concatenated.

    Used for the SQL claims: reading the constants rather than the raw text means
    a comment (or this file's own prose) cannot satisfy a scan for a condition.
    """
    parts: list[str] = []
    for node in ast.walk(_function(path, name)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            parts.append(node.value)
    return "\n".join(parts)


def _keyword_values(root: Path, keyword: str) -> frozenset[str]:
    """Literal values passed as ``keyword=<str>`` anywhere under ``root``."""
    values: set[str] = set()
    for tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == keyword and isinstance(kw.value, ast.Constant):
                        values.add(str(kw.value.value))
    return frozenset(values)


def _action_values(path: Path, name: str) -> frozenset[str]:
    """Every value ``report["action"]`` can take, in *both* spellings.

    A dict literal (``{"action": "skip"}``) and a subscript assignment
    (``report["action"] = "evolved"``) are the same statement written two ways,
    and the function uses both.  Scanning one shape would report a subset that
    looks complete.
    """
    values: set[str] = set()
    for node in ast.walk(_function(path, name)):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "action"
                and isinstance(node.value, ast.Constant)
            ):
                values.add(str(node.value.value))
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "action"
                    and isinstance(value, ast.Constant)
                ):
                    values.add(str(value.value))
    return frozenset(values)


def _sql_mentions(path: Path, name: str, needle: str) -> bool:
    """Whether the function's own string literals mention ``needle``."""
    return needle in _string_constants(path, name)


def _sql_omits(path: Path, name: str, needle: str) -> bool:
    """The absence direction, named so the polarity stays readable.

    Two claims below assert that a condition is **not** there.
    Negating in place at the call site would read the same as the
    positive form in the claim table, so the direction gets a name:
    the id, the published value and the scan then all point the same
    way, and a scanner gutted to answer ``False`` shows up as the
    opposite value instead of hiding behind a ``not``.
    """
    return not _sql_mentions(path, name, needle)


# ── the recalculators, one per published claim ───────────────────────────────


def _weights_sum_to_one() -> bool:
    return abs(sum(DEFAULT_DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9


def _note_stats_fields() -> frozenset[str]:
    return frozenset(f.name for f in fields(NoteStats))


_CLAIMS: dict[str, Callable[[], Any]] = {
    # §1 -- the two signals and the bridge between them.
    "weak_label_metric_keys": lambda: tuple(sorted(WEAK_LABEL_METRIC_KEYS)),
    "weak_label_key_count": lambda: len(WEAK_LABEL_METRIC_KEYS),
    "offline_quality_dimensions": lambda: tuple(sorted(WEIGHTED_DIMENSIONS)),
    "offline_quality_dimension_count": lambda: len(WEIGHTED_DIMENSIONS),
    "offline_quality_weights_sum_to_one": _weights_sum_to_one,
    # The producer must be able to supply what the contract asks for; this is the
    # exact opposite of the gap S1 registered (metrics the publisher never wrote).
    "online_reward_source_exposes_every_contract_key": lambda: (
        set(WEAK_LABEL_METRIC_KEYS) <= _note_stats_fields()
    ),
    "engagement_label_source": lambda: ENGAGEMENT_LABEL_SOURCE,
    "evaluator_label_source_writers": lambda: _keyword_values(BACKEND, "label_source"),
    # §2 -- the write conditions.
    "attach_writers": lambda: _functions_mentioning(CONFIG, "_ATTACH_WEAK_LABEL_SQL"),
    "import_bundle_call_sites": lambda: len(_calls_of(PIPELINE, "import_bundle")),
    "attach_calls_in_import_bundle": lambda: len(
        _calls_of(PIPELINE, "_attach_real_weak_labels", inside="import_bundle")
    ),
    "attach_normalizes_on_the_producer_side": lambda: (
        "normalize_platform_post_id(note.note_id)"
        in _body_source(PIPELINE, "_attach_real_weak_labels")
    ),
    "attach_asks_the_shared_selector": lambda: (
        "build_weak_label(note.to_dict())" in _body_source(PIPELINE, "_attach_real_weak_labels")
    ),
    "evolution_asked_only_when_rows_updated": lambda: (
        "if updated" in _body_source(PIPELINE, "_attach_real_weak_labels")
    ),
    "attach_selector_does_not_skip_labeled_rows": lambda: _sql_omits(
        CONFIG, "backfill_engagement_for_posts", "engagement IS NULL"
    ),
    # §3 -- the evolution gate.
    "min_evolve_samples": lambda: MIN_EVOLVE_SAMPLES,
    "evolution_outcomes": lambda: _action_values(CONFIG, "maybe_evolve"),
    "maybe_evolve_has_a_reentry_guard": lambda: (
        "if account_id in _EVOLVING" in _body_source(CONFIG, "maybe_evolve")
    ),
    "count_window_is_the_samples_creation_time": lambda: _sql_mentions(
        CONFIG, "count_labeled_since", "engagement IS NOT NULL AND created_at > %s"
    ),
    "count_ignores_when_the_label_arrived": lambda: _sql_omits(
        CONFIG, "count_labeled_since", "label_source"
    ),
}


def _published() -> dict[str, str]:
    """The ``id -> value`` rows of every claim block, in document order."""
    rows: dict[str, str] = {}
    for block in _BLOCK.findall(DOC.read_text(encoding="utf-8")):
        for claim_id, value in _ROW.findall(block):
            assert claim_id not in rows, f"{claim_id} is published twice"
            rows[claim_id] = value
    return rows


def test_the_doc_is_here_and_its_marker_pairs_are_balanced():
    """A lost marker would silently hide a whole block from the checks below."""
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
    assert not complaints, f"docs/outcome-learning.md has drifted from the code:\n  {detail}"


def test_no_claim_is_published_without_a_recalculator():
    """A row without a checker is a number nobody re-tests -- the whole point."""
    orphans = sorted(set(_published()) - set(_CLAIMS))
    assert not orphans, (
        "these claims are published but nothing recomputes them; add them to "
        f"_CLAIMS or drop them from docs/outcome-learning.md: {orphans}"
    )


def test_no_recalculator_is_left_behind_by_the_document():
    """The backward direction -- and why no row-count floor is needed here.

    ``test_docs_anchors.py`` needs a floor because its rows are only ever
    *checked*, never *enumerated*: a deleted row is invisible.  Here the set of
    recalculators is itself the enumeration, so a dropped row shows up as an
    orphaned checker and this assertion fires.
    """
    missing = sorted(set(_CLAIMS) - set(_published()))
    assert not missing, (
        f"these claims have a recalculator but are not published in {DOC.name}: {missing}"
    )


# ── positive controls for the claims about an absence ────────────────────────


def test_the_label_keyword_scanner_sees_a_writer_that_is_there(tmp_path: Path):
    """Control for ``evaluator_label_source_writers``.

    Its published value is a single-element set, which any *keyword* scanner will
    report -- but the point of this control is the other direction: the scanner
    must see a writer, i.e. it must not be a ``return set()`` that happens to
    match.  The fixture passes a value the real tree does not use.
    """
    (tmp_path / "writer.py").write_text(
        "async def save(conn, sample):\n"
        '    await conn.execute("insert", sample, label_source="human_review")\n',
        encoding="utf-8",
    )
    assert _keyword_values(tmp_path, "label_source") == {"human_review"}


def test_the_shared_clause_scanner_sees_both_writers(tmp_path: Path):
    """Control for ``attach_writers``: the scan is by mention, not by name."""
    (tmp_path / "writers.py").write_text(
        "async def first(conn):\n"
        '    return f"SET {_ATTACH_WEAK_LABEL_SQL}"\n'
        "\n"
        "\n"
        "async def second(conn):\n"
        '    return f"SET {_ATTACH_WEAK_LABEL_SQL}"\n'
        "\n"
        "\n"
        "async def unrelated(conn):\n"
        '    return "SET engagement = %s"\n',
        encoding="utf-8",
    )
    assert _functions_mentioning(tmp_path / "writers.py", "_ATTACH_WEAK_LABEL_SQL") == {
        "first",
        "second",
    }


def test_the_sql_scan_discriminates_between_a_condition_and_its_absence(tmp_path: Path):
    """Control for the two claims that say a condition is **not** there.

    ``count_ignores_when_the_label_arrived`` and
    ``attach_selector_does_not_skip_labeled_rows`` both publish a boolean derived
    from a *missing* substring, so a scanner gutted to answer ``False`` would keep
    both green.  The fixture carries both substrings, in one function, so the same
    scan has to answer ``True`` for each -- and ``_sql_omits`` has to answer
    ``False`` there, which is the value these claims do *not* publish.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        "async def query(conn):\n"
        '    await conn.execute("SELECT 1 WHERE engagement IS NULL")\n'
        '    await conn.execute("SELECT 1 WHERE label_source = %s")\n',
        encoding="utf-8",
    )
    assert _sql_mentions(sample, "query", "engagement IS NULL")
    assert _sql_mentions(sample, "query", "label_source")
    # The two claims publish ``true`` through ``_sql_omits``; on a target
    # where the substring *is* present the same helper must answer
    # ``False`` -- that is what keeps them a check rather than a constant.
    assert not _sql_omits(sample, "query", "engagement IS NULL")
    assert not _sql_omits(sample, "query", "label_source")
    # And the absence side, so the helper is not a `return False` either.
    assert _sql_omits(sample, "query", "NOT NULL")


def test_the_call_scanner_finds_a_call_in_its_own_directory():
    """Control for the two call-count claims, from this file's own directory.

    This file calls ``_function``/``_calls_of`` and imports the contract, so the
    scanners have something local to see: pointing them here must not answer an
    empty collection, which is what a gutted scanner would do.
    """
    here = Path(__file__).resolve()
    found = _calls_of(here, "_functions_mentioning")
    assert found, f"the call scanner cannot see a call in its own file: {found}"
