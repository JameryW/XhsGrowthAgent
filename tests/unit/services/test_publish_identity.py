"""Pin the link between a workflow run and the platform post it produced.

P3-S2's claim is that this link stopped being a per-request projection and
became a stored fact.  Three things have to hold at once, and each is asserted
here rather than described:

1. **One owner for "what counts as a platform id".**  The rule used to exist
   twice -- ``analytics`` rejected ``mock_``/``workflow:``, ``publisher``
   rejected only ``mock_`` -- and the two stayed in agreement *by luck of the
   read side normalizing before comparing*.
2. **The match is a pure function.**  It is repeatable today because the
   decision reads nothing but ``platform_post_id``; the resolver makes that a
   property of its shape (no mutation, no I/O) instead of a property of the
   current field set, which is what "recomputable" is supposed to mean.
3. **The nullable column has a writer production actually reaches.**  A column
   nobody fills is the same complete-but-never-started shape the parent ticket
   exists to expose, so the writer's call site is pinned too.

Every "nothing does X" assertion here is a function of the ``root`` it scans and
has a control that points the same code at a place where X *is* present: a
scanner gutted to ``return set()`` would otherwise keep them green forever.
"""

from __future__ import annotations

import ast
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.publish_identity import (
    normalize_platform_post_id,
    resolve_platform_links,
)

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
PUBLISH_IDENTITY = BACKEND / "services" / "publish_identity.py"
ANALYTICS = BACKEND / "api" / "routes" / "analytics.py"
PUBLISHER_AGENT = BACKEND / "agents" / "publisher.py"
PUBLISHER_NODE = BACKEND / "agents" / "nodes" / "publisher.py"
EVALUATOR_CONFIG = BACKEND / "db" / "evaluator_config.py"


# ── source scans ─────────────────────────────────────────────────────────────
# ``root`` is a parameter on every scanner so a positive control can point the
# same code at somewhere the thing it looks for does exist.


def _defined_names(root: Path, names: set[str]) -> set[Path]:
    """Files under ``root`` that define a function called one of ``names``."""
    hits: set[Path] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name in names:
                hits.add(path.resolve())
    return hits


def _call_sites(name: str, root: Path) -> set[Path]:
    """Files under ``root`` that CALL ``name`` (mentioning it is not calling)."""
    sites: set[Path] = set()
    for path in sorted(root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
            if called == name:
                sites.add(path.resolve())
    return sites


def _executed_constants(func: ast.AsyncFunctionDef) -> set[str]:
    """Names passed as the first argument to ``<something>.execute(...)``."""
    out: set[str] = set()
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and node.args
            and isinstance(node.args[0], ast.Name)
        ):
            out.add(node.args[0].id)
    return out


# ── 1. the rule ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("", ""),
        ("   ", ""),
        ("mock_abc123", ""),
        ("workflow:thread-1", ""),
        ("note-1", "note-1"),
        ("  note-1  ", "note-1"),
        ("https://www.xiaohongshu.com/explore/note-1", "note-1"),
        ("https://www.xiaohongshu.com/explore/note-1/", "note-1"),
    ],
)
def test_normalize_accepts_only_explicit_platform_ids(raw: object, expected: str) -> None:
    assert normalize_platform_post_id(raw) == expected


# ── 2. the match ─────────────────────────────────────────────────────────────


def _workflow_rows(*ids: str) -> list[dict[str, str]]:
    return [
        {"platform_post_id": pid, "workflow_thread_id": f"thread-{index}"}
        for index, pid in enumerate(ids)
    ]


def _imported_rows(*ids: str) -> list[dict[str, str]]:
    return [{"id": pid, "platform_post_id": pid} for pid in ids]


@pytest.mark.parametrize(
    ("workflow_ids", "imported_ids", "statuses", "appended", "linked"),
    [
        # one claim on each side -> linked
        (("n1",), ("n1",), ("linked",), (), ((0, 0),)),
        # two workflows claim the same note -> ambiguous, nothing collapsed
        (("n1", "n1"), ("n1",), ("ambiguous",), (0,), ()),
        # one workflow, two imported claims for the same id -> ambiguous
        (("n1",), ("n1", "n1"), ("ambiguous",), (0, 1), ()),
        # no workflow claim -> the imported note is simply unmatched
        ((), ("n1",), ("unmatched",), (0,), ()),
        # ★ no workflow claim but TWO imported claims is still ambiguous: two
        # notes for one id would otherwise silently pick a winner
        ((), ("n1", "n1"), ("ambiguous",), (0, 1), ()),
        # a synthetic workflow id is not a claim at all
        (("workflow:t",), ("n1",), ("unmatched",), (0,), ()),
    ],
)
def test_link_decisions_cover_every_exit(
    workflow_ids: tuple[str, ...],
    imported_ids: tuple[str, ...],
    statuses: tuple[str, ...],
    appended: tuple[int, ...],
    linked: tuple[tuple[int, int], ...],
) -> None:
    resolution = resolve_platform_links(
        _workflow_rows(*workflow_ids), _imported_rows(*imported_ids)
    )

    assert tuple(group.status for group in resolution.groups) == statuses
    assert resolution.appended_imported == appended
    assert resolution.linked == linked


def test_groups_follow_the_imported_side_order() -> None:
    resolution = resolve_platform_links(_workflow_rows("a", "b"), _imported_rows("b", "a"))

    assert tuple(group.platform_post_id for group in resolution.groups) == ("b", "a")


def test_idless_imported_rows_trail_the_appended_order() -> None:
    resolution = resolve_platform_links(_workflow_rows("n1"), _imported_rows("n1", ""))

    assert tuple(group.status for group in resolution.groups) == ("linked",)
    assert resolution.idless_imported == (1,)
    # the linked note is represented by its workflow row; the id-less one trails
    assert resolution.appended_imported == (1,)


def test_resolution_is_recomputable_and_leaves_its_inputs_alone() -> None:
    workflow = _workflow_rows("n1", "n2")
    imported = _imported_rows("n1", "n2", "n3", "")
    workflow_before, imported_before = deepcopy(workflow), deepcopy(imported)

    first = resolve_platform_links(workflow, imported)
    second = resolve_platform_links(workflow, imported)

    # "recomputable" is a property of the function, not of the current inputs
    assert first == second
    assert workflow == workflow_before
    assert imported == imported_before
    assert all("link_status" not in row for row in workflow)
    # ...and the check is not vacuous: the resolution really did decide things
    assert first.linked == ((0, 0), (1, 1))
    assert first.idless_imported == (3,)
    assert first.appended_imported == (2, 3)


# ── 3. who owns the rule, and who delegates to it ────────────────────────────


def test_the_platform_id_rule_has_exactly_one_owner(tmp_path: Path) -> None:
    names = {"normalize_platform_post_id", "_normalize_platform_post_id"}

    assert _defined_names(BACKEND, names) == {PUBLISH_IDENTITY.resolve()}

    # positive control: the same scanner sees both spellings in a fixture
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    (fixture / "a.py").write_text(
        "def normalize_platform_post_id(value):\n    return value\n", encoding="utf-8"
    )
    (fixture / "b.py").write_text(
        "def _normalize_platform_post_id(value):\n    return value\n", encoding="utf-8"
    )
    assert len(_defined_names(fixture, names)) == 2


def test_analytics_delegates_the_rule_and_the_match(tmp_path: Path) -> None:
    assert _call_sites("resolve_platform_links", BACKEND) == {ANALYTICS.resolve()}
    # the owner consumes its own rule too (``resolve_platform_links`` normalizes
    # both sides), which is what keeps the two sides comparable by construction
    assert _call_sites("normalize_platform_post_id", BACKEND) == {
        ANALYTICS.resolve(),
        PUBLISHER_NODE.resolve(),
        PUBLISH_IDENTITY.resolve(),
    }

    # the read side kept no private copy of the id-prefix rule
    source = ANALYTICS.read_text(encoding="utf-8")
    assert "_normalize_platform_post_id" not in source
    assert 'startswith("mock_")' not in source

    # positive control for that claim: the write side deliberately still has it
    # (changing publisher's stored value would move the publish contract), so
    # the scanner's target is known to be findable rather than gone everywhere
    assert 'startswith("mock_")' in PUBLISHER_AGENT.read_text(encoding="utf-8")

    # positive control for the call scan itself: an empty tree has no callers
    assert _call_sites("resolve_platform_links", tmp_path) == set()


# ── 4. the column and its writer ─────────────────────────────────────────────


def test_the_column_is_created_on_both_paths_and_stays_nullable() -> None:
    source = EVALUATOR_CONFIG.read_text(encoding="utf-8")
    tree = ast.parse(source)

    # new installs get it from CREATE TABLE, upgrades from the idempotent ALTER
    assert source.count("platform_post_id TEXT") == 2
    assert "ADD COLUMN IF NOT EXISTS platform_post_id TEXT" in source
    assert "platform_post_id TEXT NOT NULL" not in source

    ensure = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "ensure_tables"
    )
    assert "_ADD_PLATFORM_ID_COL_SQL" in _executed_constants(ensure)

    # the insert path is untouched, so existing callers and legacy rows keep
    # working -- the new value only ever arrives through the writer below
    insert = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "insert_sample"
    )
    literals = [
        node.value
        for node in ast.walk(insert)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    assert not any("platform_post_id" in literal for literal in literals)


@pytest.mark.asyncio
async def test_record_publish_identity_updates_the_latest_sample() -> None:
    from backend.db.evaluator_config import record_publish_identity

    cursor = MagicMock()
    cursor.rowcount = 1
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=cursor)

    @asynccontextmanager
    async def conn_ctx(*_args: object, **_kwargs: object):
        yield conn

    pool = MagicMock()
    pool.connection = conn_ctx
    with patch("backend.db.evaluator_config.get_pool", return_value=pool):
        updated = await record_publish_identity("thread-1", "note-1")

    assert updated == 1
    sql, params = conn.execute.await_args.args
    assert "UPDATE evaluator_samples" in sql
    assert "SET platform_post_id = %s" in sql
    # same latest-by-thread rule as backfill_engagement: one sample per thread
    assert "WHERE thread_id = %s ORDER BY created_at DESC LIMIT 1" in sql
    assert params == ("note-1", "thread-1")


@pytest.mark.asyncio
async def test_record_publish_identity_is_a_no_op_without_an_id() -> None:
    from backend.db.evaluator_config import record_publish_identity

    pool = MagicMock()
    pool.connection = MagicMock(side_effect=AssertionError("must not touch the DB"))
    with patch("backend.db.evaluator_config.get_pool", return_value=pool):
        assert await record_publish_identity("thread-1", "") == 0


def test_the_writer_has_a_production_caller(tmp_path: Path) -> None:
    assert _call_sites("record_publish_identity", BACKEND) == {PUBLISHER_NODE.resolve()}
    assert _call_sites("_record_publish_identity", BACKEND) == {PUBLISHER_NODE.resolve()}

    node = PUBLISHER_NODE.read_text(encoding="utf-8")
    # reached from the node body, not just defined
    assert "await _record_publish_identity(state, result)" in node
    # normalized before the write, never the raw value
    assert 'normalize_platform_post_id(publish_result.get("platform_post_id"))' in node

    # positive control: no callers in an empty tree
    assert _call_sites("record_publish_identity", tmp_path) == set()
    assert _call_sites("_record_publish_identity", tmp_path) == set()


@pytest.mark.asyncio
async def test_the_publish_funnel_stores_the_normalized_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The node helper normalizes before it stores, so no synthetic id lands."""
    from backend.agents.nodes import publisher as node_module

    calls: list[tuple[str, str]] = []

    async def fake_record(thread_id: str, platform_post_id: str) -> int:
        calls.append((thread_id, platform_post_id))
        return 1

    monkeypatch.setattr("backend.db.evaluator_config.record_publish_identity", fake_record)
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

    await node_module._record_publish_identity(
        {"session_id": "thread-1"}, {"publish_result": {"platform_post_id": "note-1"}}
    )
    assert calls == [("thread-1", "note-1")]

    # a dry run stamps a mock_* id — normalized to "", so nothing is written
    await node_module._record_publish_identity(
        {"session_id": "thread-1"}, {"publish_result": {"platform_post_id": "mock_thread-1"}}
    )
    # a URL is unwrapped to the bare id, so both spellings compare equal
    await node_module._record_publish_identity(
        {"session_id": "thread-2"},
        {"publish_result": {"platform_post_id": "https://www.xiaohongshu.com/explore/note-2"}},
    )
    assert calls == [("thread-1", "note-1"), ("thread-2", "note-2")]


@pytest.mark.asyncio
async def test_the_publish_funnel_swallows_a_database_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A publish that already happened must not fail because the write did."""
    from backend.agents.nodes import publisher as node_module

    async def boom(thread_id: str, platform_post_id: str) -> int:
        raise RuntimeError("pool down")

    monkeypatch.setattr("backend.db.evaluator_config.record_publish_identity", boom)
    monkeypatch.setattr("backend.db.pool.is_pool_ready", lambda: True)

    await node_module._record_publish_identity(
        {"session_id": "thread-1"}, {"publish_result": {"platform_post_id": "note-1"}}
    )
