"""Pin the weak-label ingest to the producer that is supposed to feed it.

The path the parent ticket calls "online reward" is wired end to end and has
never carried a value:

* ``analyst`` reads engagement out of ``publish_result`` and hands it to
  ``backfill_engagement`` (``backend/agents/analyst.py``), which is the only
  thing that fills ``evaluator_samples.engagement``;
* ``count_labeled_since`` counts rows with a non-null ``engagement`` and
  ``maybe_evolve`` refuses to refit below ``MIN_EVOLVE_SAMPLES``;
* ``publisher`` never writes a metric key, so the hand-off is always skipped and
  the counter is always 0.  The closed loop is complete, its tests pass, and it
  has never once run.

All of that is real code a reader would take for working code, so the gap is
*registered* here instead of being left to be rediscovered.  Four ends are
pinned:

1. ``WEAK_LABEL_METRIC_KEYS`` and the payload keys ``_engagement_rate`` reads are
   the same five -- a "declared once" contract is only worth having if the
   consumer cannot drift from it;
2. ``build_weak_label`` selects exactly the keys a payload carries, and nothing
   at all when it carries none;
3. ``analyst`` asks that contract instead of repeating it, so the requirement
   reaches its only consumer by construction;
4. the keys ``publish_result`` can carry do not intersect the contract, and the
   shortfall is asserted to be all five.

Checks 1 and 4 are claims of the form "nothing does X", and a claim whose value
is zero has no built-in control: a scanner gutted to ``return set()`` would keep
both green forever.  So every scanner here is a function of the ``root`` it reads
and has a test that points it at a place where the thing *is* present --
``build_weak_label`` taking its payload as an argument exists for the same
reason.  ``tests/unit/scripts/test_planning_claims.py`` is the same shape for the
same reason.

P3-S3 closed the gap -- from the *import* side, not through ``publish_result``.
The prediction above ("check 4 goes red on purpose") therefore did not come true:
the creator-stats sync never builds a publish result, it writes the metrics
straight onto the matching sample (``backfill_engagement_for_posts``), so a
publish-time payload still carries identity and status only and check 4 is still
true and still green.  What did change is the third declared value of
``label_source``: it has a writer at last, and
``test_each_label_writer_is_accounted_for`` below replaces the claim that it
never would.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from backend.agents.publisher import _with_publish_link_metadata
from backend.db import evaluator_config
from backend.db.evaluator_config import (
    _ATTACH_WEAK_LABEL_SQL,
    ENGAGEMENT_LABEL_SOURCE,
    WEAK_LABEL_METRIC_KEYS,
    build_weak_label,
)

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
EVALUATOR_CONFIG = BACKEND / "db" / "evaluator_config.py"

#: The five keys the contract is about, as a plain set for set arithmetic.  Read
#: from the module rather than repeated, so the assertion below cannot be
#: satisfied by editing the test.
CONTRACT = set(WEAK_LABEL_METRIC_KEYS)


# ── source scans ─────────────────────────────────────────────────────────────
# ``root`` is a parameter on every scanner so the positive controls can point the
# same code at somewhere the thing it looks for does exist.


def _trees(root: Path) -> list[tuple[Path, ast.Module]]:
    """Parse every module under ``root``.

    Parsed, never imported: string literals that appear in a comment or a
    docstring are not constants, so a comment describing the gap cannot satisfy
    a scan for the gap -- and ``evaluator_config`` documents
    ``label_source="engagement"`` in exactly such a comment.
    """
    return [
        (path, ast.parse(path.read_text(encoding="utf-8"))) for path in sorted(root.rglob("*.py"))
    ]


def _dict_str_keys(node: ast.Dict) -> set[str]:
    return {k.value for k in node.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)}


def _is_name(node: ast.expr, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


#: The one function whose argument *is* a publish result: it copies one and adds
#: the identity keys, so a dict literal handed to it is a publish result by
#: definition.  Named here rather than inlined so the fixture in the positive
#: control below can be checked against the same string.
PUBLISH_METADATA_HELPER = "_with_publish_link_metadata"


def _is_publish_metadata_call(node: ast.Call) -> bool:
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    return name == PUBLISH_METADATA_HELPER


def _publish_result_keys(root: Path = BACKEND) -> set[str]:
    """Every key ``publish_result`` can carry, in the four shapes the source uses.

    * a dict bound to the name -- ``publish_result = {...}``, annotated or not;
    * a dict stored under the key -- ``cal_state["publish_result"] = {...}``, or
      handed over inline as ``return {"publish_result": {...}}``;
    * a dict literal passed to the metadata helper, which takes a publish result
      by construction;
    * a subscript write -- ``publish_result["error"] = ...``, which is how the
      error path extends the dict after the literal.

    A key added by ``.update()`` on a *derived* name is invisible to all four
    (``_with_publish_link_metadata`` copies into a local ``result`` first), so
    the identity keys are not read from source at all -- see ``PRODUCED``.
    """
    keys: set[str] = set()
    for _path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for key, value in zip(node.keys, node.values, strict=True):
                    if (
                        isinstance(key, ast.Constant)
                        and key.value == "publish_result"
                        and isinstance(value, ast.Dict)
                    ):
                        keys |= _dict_str_keys(value)
            if isinstance(node, ast.Call) and _is_publish_metadata_call(node):
                for arg in node.args:
                    if isinstance(arg, ast.Dict):
                        keys |= _dict_str_keys(arg)
            if isinstance(node, ast.Assign):
                value = node.value
                for target in node.targets:
                    if _is_name(target, "publish_result") and isinstance(value, ast.Dict):
                        keys |= _dict_str_keys(value)
                    if (
                        isinstance(target, ast.Subscript)
                        and isinstance(value, ast.Dict)
                        and _subscript_key(target) == "publish_result"
                    ):
                        keys |= _dict_str_keys(value)
                    if isinstance(target, ast.Subscript) and _is_name(
                        target.value, "publish_result"
                    ):
                        key = _subscript_key(target)
                        if key:
                            keys.add(key)
            elif isinstance(node, ast.AnnAssign):
                if _is_name(node.target, "publish_result") and isinstance(node.value, ast.Dict):
                    keys |= _dict_str_keys(node.value)
    return keys


def _subscript_key(node: ast.Subscript) -> str | None:
    """The constant string a subscript reads or writes, if it is one."""
    index = node.slice
    if isinstance(index, ast.Constant) and isinstance(index.value, str):
        return index.value
    return None


def _keyword_values(root: Path, arg: str) -> list[str]:
    """Every string literal passed as ``arg=<str>`` under ``root``.

    Keyword *arguments*, not assignments: this is the shape a sample writer uses
    (``insert_sample(..., label_source="evaluator")``), and it is what makes the
    scan immune to the comment in ``evaluator_config`` that names the label this
    one has no writer for.
    """
    values: list[str] = []
    for _path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if (
                        kw.arg == arg
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        values.append(kw.value.value)
    return values


def _formula_keys(path: Path = EVALUATOR_CONFIG) -> set[str]:
    """The payload keys ``_engagement_rate`` reads, taken from its source.

    The function is private, so it is scanned rather than called: importing a
    private name would pin a signature the contract does not depend on, while
    what actually has to stay in step is the *keys*.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_engagement_rate":
            return {
                call.args[0].value
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "get"
                and call.args
                and isinstance(call.args[0], ast.Constant)
                and isinstance(call.args[0].value, str)
            }
    raise AssertionError(f"_engagement_rate is not defined in {path}")


def _callers_of(name: str, root: Path = BACKEND) -> list[Path]:
    """Modules that call ``name``, ignoring the import that brought it in."""
    found: list[Path] = []
    for path, tree in _trees(root):
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
                if called == name:
                    found.append(path)
                    break
    return found


#: What a publish can currently leave behind: the source half is a scan over
#: ``backend/``, the identity half is a call into the real helper.  Computed once
#: at import, after the scanners it needs are defined.
PRODUCED = _publish_result_keys() | set(_with_publish_link_metadata({}, {}))


# ── the contract ─────────────────────────────────────────────────────────────


def test_the_declaration_and_the_formula_read_the_same_keys():
    """The five keys are declared once, and ``_engagement_rate`` consumes those.

    Direction matters: the declaration exists so the requirement and the formula
    cannot be edited apart.  A tuple that no longer matches the arithmetic would
    be documentation of a contract nobody keeps.
    """
    assert _formula_keys() == CONTRACT, (
        "WEAK_LABEL_METRIC_KEYS and the keys _engagement_rate reads have drifted apart"
    )


def test_build_weak_label_selects_what_the_payload_carries():
    """A payload with the metrics comes back whole; an empty payload comes back empty.

    The empty case is the one that matters in production -- but on its own it
    cannot distinguish "the producer sent nothing" from "the selector drops
    everything", so the non-empty case is asserted beside it.
    """
    full = {key: 7 for key in WEAK_LABEL_METRIC_KEYS}
    assert build_weak_label(full) == full

    partial = {"views": 10, "likes": 1, "post_id": "abc", "status": "published"}
    assert build_weak_label(partial) == {"views": 10, "likes": 1}

    assert build_weak_label(None) == {}
    assert build_weak_label({}) == {}


def test_every_producer_asks_the_contract_instead_of_repeating_it():
    """The seam this slice exists to create: one declaration, every producer asks it.

    ``analyst`` used to spell the five keys out a second time, which is how a
    contract and its only consumer drift apart silently.  P3-S3 added the second
    producer -- the creator-stats import -- and it asks the same selector instead
    of spelling the keys out again, so a change to the requirement reaches both
    call sites by construction.  Pinned by call, not by the absence of a literal:
    an absence would also be satisfied by a caller that asks nothing at all.

    The set is asserted exactly rather than as a subset: a third producer has to
    be registered here deliberately, and a producer that quietly stops asking the
    contract fails instead of drifting.
    """
    assert set(_callers_of("build_weak_label")) == {
        BACKEND / "agents" / "analyst.py",
        BACKEND / "services" / "creator_stats" / "pipeline.py",
    }
    # Positive control, from this file: it calls the selector too, so pointing
    # the same scanner at its own directory has to see it.  ``analyst`` being
    # the *only* caller in ``backend/`` says nothing on its own.
    assert Path(__file__).resolve() in _callers_of("build_weak_label", Path(__file__).parent)


def test_publisher_cannot_feed_the_weak_label_path():
    """The registered gap: ``publish_result`` carries none of the five keys.

    This is the whole reason the loop never starts.  ``analyst`` is reachable and
    runs (``state/modes.py`` maps ``ANALYZING`` to it and the application route
    exposes a manual trigger); it simply has nothing to hand over, because a
    publish-time payload is identity and status only.

    The shortfall is asserted as a set, not as "the intersection is empty": when
    the numbers start arriving, this test has to be *edited*, which is the point.
    """
    produced = PRODUCED
    assert produced & CONTRACT == set(), (
        f"a publisher now writes metrics -- update the gap registration and prd.md: "
        f"{sorted(produced & CONTRACT)}"
    )
    assert CONTRACT - produced == CONTRACT, "the shortfall is not all five keys any more"


def test_publish_result_is_produced_with_identity_and_status_only():
    """Non-emptiness control for the producer scan, from the other side.

    ``test_publisher_cannot_feed_the_weak_label_path`` asserts an absence, so it
    would pass just as happily against a scanner that returns nothing at all.
    These keys are the ones the scan *must* see, and they come from the two
    halves between them: source for the literals, the real
    ``_with_publish_link_metadata`` for the identity the source hides behind
    ``.update()``.
    """
    assert {"post_id", "post_url", "status", "publish_id"} <= PRODUCED
    # Call it rather than scan it: the function copies into a local before
    # updating, so no reading of its source can see what it adds.
    assert set(_with_publish_link_metadata({}, {})) == {
        "workflow_thread_id",
        "platform_post_id",
        "link_status",
    }
    assert {"workflow_thread_id", "platform_post_id", "link_status"} <= PRODUCED


def test_the_publisher_scanner_can_see_a_producer_that_writes_metrics(tmp_path: Path):
    """Positive control for the producer scan, pointed at a producer that works.

    The fixture exercises every shape the scanner claims to read, because a
    scanner that reads one shape and silently ignores the others would report the
    same plausible emptiness about the real publisher.  Pointed at the shape the
    sync path is supposed to grow -- a publish result extended with the numbers
    after the fact.
    """
    (tmp_path / "producer.py").write_text(
        "def attach(publish_result):\n"
        '    publish_result["views"] = 120\n'
        '    publish_result["likes"] = 3\n'
        '    return {"publish_result": publish_result}\n'
        "\n"
        "def inline():\n"
        '    return {"publish_result": {"comments": 1}}\n'
        "\n"
        "def through_the_helper(state):\n"
        f'    return {PUBLISH_METADATA_HELPER}({{"shares": 2}}, state)\n',
        encoding="utf-8",
    )
    assert _publish_result_keys(tmp_path) & CONTRACT == {
        "views",
        "likes",
        "comments",
        "shares",
    }


def test_the_formula_scanner_can_see_a_different_key_set(tmp_path: Path):
    """Positive control for the formula scan.

    The same function name reading a different payload, which is what a stale
    declaration would look like.  If the scanner cannot tell these apart it
    cannot tell the real one from an empty one either.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        "def _engagement_rate(engagement):\n"
        '    views = float(engagement.get("impressions") or 0)\n'
        '    return views + float(engagement.get("saves") or 0)\n',
        encoding="utf-8",
    )
    assert _formula_keys(sample) == {"impressions", "saves"}


def test_each_label_writer_is_accounted_for(tmp_path: Path):
    """Two of the three declared ``label_source`` values now have writers.

    Reshaped rather than deleted (P3-S3).  The previous version asserted "only
    ``evaluator`` has a writer", which the sync path made false; what survives is
    the part that can still fail.  The two writers are found by different means
    because they are written differently, and that asymmetry is the point:

    * the *insert* paths pass the label as a keyword argument, so an AST scan for
      ``label_source=<str>`` sees them -- and still sees exactly one value, because
      nothing inserts an already-labeled sample;
    * the *attach* path writes the label inside SQL, where no keyword scan can
      reach it.  A keyword scan on its own would therefore have kept this file
      green while the column silently acquired a second writer -- the "guard keeps
      saying all clear" failure this module exists to prevent.  So the attach is
      checked against the clause it shares with its sibling, and the clause is
      checked to carry the declared constant.
    """
    assert set(_keyword_values(BACKEND, "label_source")) == {"evaluator"}
    assert ENGAGEMENT_LABEL_SOURCE == "engagement"
    assert f"label_source = '{ENGAGEMENT_LABEL_SOURCE}'" in _ATTACH_WEAK_LABEL_SQL

    # Positive control for the keyword scan, unchanged in spirit: a writer that
    # does pass the other label as a keyword argument must show up.
    (tmp_path / "writer.py").write_text(
        "async def save(conn, sample):\n"
        '    await conn.execute("insert", sample, label_source="engagement")\n',
        encoding="utf-8",
    )
    assert _keyword_values(tmp_path, "label_source") == ["engagement"]


def test_both_attach_paths_share_one_clause():
    """One statement body, two selectors -- so the writers cannot drift apart.

    ``backfill_engagement`` picks its rows by thread and
    ``backfill_engagement_for_posts`` by platform post; both must set the same
    columns to the same values.  Pinning that as "each function names the shared
    constant" means inlining the payload or the label into either statement is a
    test failure rather than a silent divergence discovered later by a refit.
    """
    for name in ("backfill_engagement", "backfill_engagement_for_posts"):
        source = inspect.getsource(getattr(evaluator_config, name))
        assert "_ATTACH_WEAK_LABEL_SQL" in source, (
            f"{name} no longer attaches through the shared clause"
        )
