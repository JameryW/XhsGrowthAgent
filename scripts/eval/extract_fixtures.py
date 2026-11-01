"""Extract redacted evaluation fixtures from real LangGraph checkpoints (E1).

Decisions this implements (2026-11-01):
* **真实** — the corpus is built from real workflow checkpoints, not synthetic
  states;
* **都需要** — a fixture keeps content-bearing fields (copy/visual/plan
  structures) so both decision correctness *and* content quality can be scored
  later, while every identity/secret is removed by the one redaction pass in
  ``fixtures.py``;
* **可配置** — how many fixtures to take is an explicit flag (``--limit`` /
  ``--all``), the source is selectable (SQLite file or Postgres URI) and the
  output directory is explicit.

The script is offline: it reads a checkpoint store and writes fixtures plus a
manifest.  It never runs a workflow, calls a model or touches the network
(the Postgres reader is the only thing that opens a connection, and only when
``--postgres-uri`` is passed).

Usage::

    python scripts/eval/extract_fixtures.py --sqlite-path .xhs/checkpoints.sqlite
    python scripts/eval/extract_fixtures.py --postgres-uri "$XHS_POSTGRES_URI" --limit 20
    python scripts/eval/extract_fixtures.py --dry-run --phases reviewing,publishing
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import AsyncIterator, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

_EVAL_DIR = Path(__file__).resolve().parent
if str(_EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(_EVAL_DIR))

from fixtures import (  # noqa: E402  (sibling module, loaded after sys.path setup)
    EXTRACTOR_VERSION,
    SCHEMA_VERSION,
    EvalFixture,
    FixtureEntry,
    FixtureManifest,
    build_fixture,
)

DEFAULT_OUTPUT = Path(".eval-fixtures")
DEFAULT_SQLITE = Path(".xhs/checkpoints.sqlite")
DEFAULT_LIMIT = 100


@dataclass(frozen=True)
class CheckpointRecord:
    """One checkpoint as the extractor needs it: thread, id and state values."""

    thread_id: str
    checkpoint_id: str
    state: Mapping[str, Any]


async def _records_from_saver(saver: Any) -> AsyncIterator[CheckpointRecord]:
    """Yield checkpoint records from a LangGraph saver, newest first."""
    async for item in saver.alist(None):
        config = getattr(item, "config", None) or {}
        configurable = config.get("configurable") if isinstance(config, Mapping) else None
        configurable = configurable if isinstance(configurable, Mapping) else {}
        thread_id = str(configurable.get("thread_id") or "")
        checkpoint = getattr(item, "checkpoint", None)
        channel_values = (
            checkpoint.get("channel_values") if isinstance(checkpoint, Mapping) else None
        )
        if not thread_id or not isinstance(channel_values, Mapping):
            continue
        checkpoint_id = str(configurable.get("checkpoint_id") or checkpoint.get("id") or "")
        yield CheckpointRecord(
            thread_id=thread_id,
            checkpoint_id=checkpoint_id,
            state=channel_values,
        )


async def iter_sqlite(path: Path) -> AsyncIterator[CheckpointRecord]:
    """Read every checkpoint from a local ``AsyncSqliteSaver`` database."""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with aiosqlite.connect(str(path)) as conn:
        saver = AsyncSqliteSaver(conn=conn)
        async for record in _records_from_saver(saver):
            yield record


async def iter_postgres(uri: str) -> AsyncIterator[CheckpointRecord]:
    """Read every checkpoint from a Postgres ``AsyncPostgresSaver`` database."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    async with AsyncPostgresSaver.from_conn_string(uri) as saver:
        async for record in _records_from_saver(saver):
            yield record


def select_corpus(
    records: Iterable[CheckpointRecord],
    *,
    source: Literal["sqlite", "postgres"],
    phases: frozenset[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    include_messages: bool = False,
) -> tuple[list[EvalFixture], dict[str, int]]:
    """Pick at most *limit* latest-per-thread fixtures and count what was skipped.

    ``alist`` yields the newest checkpoint of each thread first, so "first seen
    wins" is the latest state of that thread without a second query.  The limit is
    the configurable budget: ``0`` means "no limit", anything else stops once that
    many fixtures have been collected (records are still counted as skipped).
    """
    fixtures: list[EvalFixture] = []
    skipped = {"duplicate_thread": 0, "phase_filtered": 0, "limit_reached": 0, "invalid": 0}
    seen: set[str] = set()
    for record in records:
        if record.thread_id in seen:
            skipped["duplicate_thread"] += 1
            continue
        seen.add(record.thread_id)
        try:
            fixture = build_fixture(
                source=source,
                thread_id=record.thread_id,
                checkpoint_id=record.checkpoint_id,
                state=record.state,
                include_messages=include_messages,
            )
        except ValueError:
            skipped["invalid"] += 1
            continue
        if phases and fixture.phase and fixture.phase not in phases:
            skipped["phase_filtered"] += 1
            continue
        if limit and len(fixtures) >= limit:
            skipped["limit_reached"] += 1
            continue
        fixtures.append(fixture)
    return fixtures, skipped


def write_corpus(
    fixtures: list[EvalFixture],
    *,
    out_dir: Path,
    source_kind: Literal["sqlite", "postgres"],
    include_messages: bool,
    skipped: Mapping[str, int],
    generated_at: str | None = None,
) -> FixtureManifest:
    """Write fixtures + manifest; returns the manifest (also written to disk)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    entries: list[FixtureEntry] = []
    for fixture in fixtures:
        payload = fixture.model_dump_json(indent=2).encode("utf-8")
        path = out_dir / f"fixture-{fixture.fixture_id}.json"
        path.write_bytes(payload)
        entries.append(
            FixtureEntry(
                fixture_id=fixture.fixture_id,
                file=path.name,
                sha256=hashlib.sha256(payload).hexdigest(),
                phase=fixture.phase,
                thread_pseudonym=fixture.thread_pseudonym,
            )
        )
    manifest = FixtureManifest(
        schema_version=SCHEMA_VERSION,
        extractor_version=EXTRACTOR_VERSION,
        source_kind=source_kind,
        generated_at=generated_at or datetime.now(UTC).isoformat(),
        include_messages=include_messages,
        total=len(entries),
        fixtures=entries,
        skipped=dict(skipped),
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


async def run_extraction(
    *,
    sqlite_path: Path | None,
    postgres_uri: str | None,
    out_dir: Path,
    limit: int,
    phases: frozenset[str] | None,
    include_messages: bool,
    dry_run: bool,
) -> tuple[list[EvalFixture], dict[str, int], FixtureManifest | None]:
    """The whole pipeline, shared by the CLI and the tests (no printing)."""
    if (sqlite_path is None) == (postgres_uri is None):
        raise ValueError("pass exactly one of sqlite_path / postgres_uri")
    source: Literal["sqlite", "postgres"]
    if sqlite_path is not None:
        source = "sqlite"
        records = [record async for record in iter_sqlite(sqlite_path)]
    else:
        assert postgres_uri is not None
        source = "postgres"
        records = [record async for record in iter_postgres(postgres_uri)]
    fixtures, skipped = select_corpus(
        records,
        source=source,
        phases=phases,
        limit=limit,
        include_messages=include_messages,
    )
    manifest = None
    if not dry_run:
        manifest = write_corpus(
            fixtures,
            out_dir=out_dir,
            source_kind=source,
            include_messages=include_messages,
            skipped=skipped,
        )
    return fixtures, skipped, manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract redacted eval fixtures from checkpoints")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--sqlite-path", type=Path, default=None)
    source.add_argument("--postgres-uri", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"max fixtures (budget); 0 means no limit (default {DEFAULT_LIMIT})",
    )
    parser.add_argument("--all", action="store_true", help="shorthand for --limit 0")
    parser.add_argument("--phases", default="", help="comma-separated workflow phases to keep")
    parser.add_argument("--include-messages", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="read and redact, write nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    options = _build_parser().parse_args(argv)
    sqlite_path = options.sqlite_path
    if sqlite_path is None and not options.postgres_uri:
        sqlite_path = DEFAULT_SQLITE
    phases = frozenset(part.strip() for part in options.phases.split(",") if part.strip())
    limit = 0 if options.all else max(0, options.limit)
    try:
        fixtures, skipped, manifest = asyncio.run(
            run_extraction(
                sqlite_path=sqlite_path,
                postgres_uri=options.postgres_uri,
                out_dir=options.output,
                limit=limit,
                phases=phases or None,
                include_messages=options.include_messages,
                dry_run=options.dry_run,
            )
        )
    except FileNotFoundError:
        print(f"checkpoint source not found: {sqlite_path}")
        return 1
    except ConnectionError as exc:
        print(f"could not read checkpoint source: {exc}")
        return 1
    print(f"fixtures: {len(fixtures)}  skipped: {json.dumps(skipped, ensure_ascii=False)}")
    if not fixtures:
        print("no fixtures extracted: the source has no matching checkpoints")
    if manifest is not None:
        print(f"manifest: {options.output / 'manifest.json'} ({manifest.total} fixtures)")
    elif options.dry_run:
        print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
