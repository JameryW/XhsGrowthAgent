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
import os
import sqlite3
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
    """One checkpoint as the extractor needs it: namespace, thread, id and state."""

    thread_id: str
    checkpoint_id: str
    state: Mapping[str, Any]
    checkpoint_ns: str = ""


async def _records_from_saver(saver: Any) -> AsyncIterator[CheckpointRecord]:
    """Yield checkpoint records from a LangGraph saver, newest first."""
    async for item in saver.alist(None):
        config = getattr(item, "config", None) or {}
        configurable = config.get("configurable") if isinstance(config, Mapping) else None
        configurable = configurable if isinstance(configurable, Mapping) else {}
        thread_id = str(configurable.get("thread_id") or "")
        checkpoint_ns = str(configurable.get("checkpoint_ns") or "")
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
            checkpoint_ns=checkpoint_ns,
        )


async def iter_sqlite(path: Path) -> AsyncIterator[CheckpointRecord]:
    """Read a local ``AsyncSqliteSaver`` database, strictly read-only.

    Opening the file is the only write-shaped thing this used to do: a missing
    path made ``aiosqlite.connect`` create an empty database and a matching
    ``setup()`` schema, so a typo produced a valid-looking empty corpus.  The
    pre-check plus ``mode=ro`` means a wrong path is an error, not a fixture.
    """
    if not path.is_file():
        raise FileNotFoundError(f"checkpoint database not found: {path}")
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async with aiosqlite.connect(f"file:{path.as_posix()}?mode=ro", uri=True) as conn:
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
    redaction_key: bytes | None = None,
) -> tuple[list[EvalFixture], dict[str, int]]:
    """Pick at most *limit* latest-per-thread fixtures and count what was skipped.

    ``alist`` yields the newest checkpoint of each thread first, so "first seen
    wins" is the latest state of that thread without a second query.  The limit is
    the configurable budget: ``0`` means "no limit", anything else stops once that
    many fixtures have been collected (records are still counted as skipped).

    Subgraph checkpoints (non-empty ``checkpoint_ns``) are skipped: they carry a
    child namespace's state, and because alist is ordered globally, a subgraph row
    can be newer than the thread's main-state row.  Counting them separately keeps
    that visible instead of silently becoming the thread's "latest" fixture.
    """
    fixtures: list[EvalFixture] = []
    skipped = {
        "duplicate_thread": 0,
        "subgraph_checkpoint": 0,
        "phase_filtered": 0,
        "limit_reached": 0,
        "invalid": 0,
    }
    seen: set[str] = set()
    for record in records:
        if record.checkpoint_ns:
            skipped["subgraph_checkpoint"] += 1
            continue
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
                redaction_key=redaction_key,
            )
        except ValueError:
            skipped["invalid"] += 1
            continue
        if phases and fixture.phase not in phases:
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
    skipped: Mapping[str, int],
    generated_at: str | None = None,
    pseudonym_mode: Literal["sha256", "hmac"] = "sha256",
) -> FixtureManifest:
    """Write fixtures + manifest + ``manifest.sha256`` (a detached digest).

    The digest file catches an edited manifest; a *paired rewrite* of fixtures,
    manifest and digest is only detectable with an out-of-band value such as
    ``run_gate.py --expect-manifest-sha256`` or the digest kept in the experiment
    record.  The docstring says so instead of implying tamper-proofness.
    """
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
        total=len(entries),
        fixtures=entries,
        skipped=dict(skipped),
        pseudonym_mode=pseudonym_mode,
    )
    manifest_bytes = json.dumps(
        manifest.model_dump(mode="json"), ensure_ascii=False, indent=2
    ).encode("utf-8")
    (out_dir / "manifest.json").write_bytes(manifest_bytes)
    (out_dir / "manifest.sha256").write_text(
        hashlib.sha256(manifest_bytes).hexdigest() + "\n", encoding="utf-8"
    )
    return manifest


async def run_extraction(
    *,
    sqlite_path: Path | None,
    postgres_uri: str | None,
    out_dir: Path,
    limit: int,
    phases: frozenset[str] | None,
    dry_run: bool,
    redaction_key: bytes | None = None,
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
        redaction_key=redaction_key,
    )
    manifest = None
    if not dry_run:
        manifest = write_corpus(
            fixtures,
            out_dir=out_dir,
            source_kind=source,
            skipped=skipped,
            pseudonym_mode="hmac" if redaction_key is not None else "sha256",
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
    parser.add_argument(
        "--redaction-key-env",
        default="XHS_EVAL_REDACTION_KEY",
        help="environment variable holding the HMAC key for pseudonyms "
        "(unset = weak sha256 pseudonyms, with a warning)",
    )
    parser.add_argument("--dry-run", action="store_true", help="read and redact, write nothing")
    return parser


def main(argv: list[str] | None = None) -> int:
    options = _build_parser().parse_args(argv)
    sqlite_path = options.sqlite_path
    if sqlite_path is None and not options.postgres_uri:
        sqlite_path = DEFAULT_SQLITE
    phases = frozenset(part.strip() for part in options.phases.split(",") if part.strip())
    limit = 0 if options.all else max(0, options.limit)
    raw_key = os.environ.get(options.redaction_key_env, "").strip()
    redaction_key = raw_key.encode("utf-8") if raw_key else None
    if redaction_key is None:
        print(
            f"warning: {options.redaction_key_env} is unset; pseudonyms are plain truncated "
            "SHA-256 and short ids can be guessed from the corpus (set the key to use HMAC)"
        )
    try:
        fixtures, skipped, manifest = asyncio.run(
            run_extraction(
                sqlite_path=sqlite_path,
                postgres_uri=options.postgres_uri,
                out_dir=options.output,
                limit=limit,
                phases=phases or None,
                dry_run=options.dry_run,
                redaction_key=redaction_key,
            )
        )
    except FileNotFoundError:
        print(f"checkpoint source not found: {sqlite_path}")
        return 1
    except (ConnectionError, sqlite3.OperationalError) as exc:
        print(f"could not read checkpoint source: {exc}")
        return 1
    print(f"fixtures: {len(fixtures)}  skipped: {json.dumps(skipped, ensure_ascii=False)}")
    if not fixtures:
        print("no fixtures extracted: the source has no matching checkpoints")
    if manifest is not None:
        print(
            f"manifest: {options.output / 'manifest.json'} "
            f"({manifest.total} fixtures, pseudonyms={manifest.pseudonym_mode})"
        )
        print(
            "record this digest out of band: "
            f"{(options.output / 'manifest.sha256').read_text(encoding='utf-8').strip()}"
        )
    elif options.dry_run:
        print("dry run: nothing written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
