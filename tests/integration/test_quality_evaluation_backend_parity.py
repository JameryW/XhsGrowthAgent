"""Postgres/memory agreement for quality-evaluation recency rules.

``tests/unit/db/test_quality_evaluation_recency.py`` pins the in-memory fallback.
That coverage alone let a real divergence through: the Postgres trend branch
re-sorted rows by ``created_at`` after a query that had already applied the
insertion-sequence tie-break, so two runs written in the same clock tick came
back ascending from memory and descending from the database.

Same opt-in contract as ``test_creator_agent_backend_parity.py``: skip unless
``XHS_PG_PARITY_URI`` is set, and create plus drop a private scratch database so
no existing data is touched. On Windows the scenario owns a selector event loop
because psycopg3 refuses to run async on the default ``ProactorEventLoop``.
"""

from __future__ import annotations

import asyncio
import json
import os
import selectors
import uuid
from typing import Any

import pytest

PG_URI_ENV = "XHS_PG_PARITY_URI"
TICK = "2026-09-11T00:00:00+00:00"

pytestmark = pytest.mark.skipif(
    not os.environ.get(PG_URI_ENV),
    reason=f"set {PG_URI_ENV} to a scratch-capable PostgreSQL server URI to run quality parity",
)

_IDENTITY = {
    "account_id": "acc-a",
    "subject_type": "imported_note",
    "subject_id": "note-1",
    "assessment_type": "rqgm_content_review",
    "source_content_hash": "sha256:source",
    "source_data_as_of": "2026-09-11",
    "context_hash": "sha256:context",
    "evaluator_fingerprint": "rqgm:fingerprint",
}


def _run(coro: Any) -> Any:
    loop = asyncio.SelectorEventLoop(selectors.SelectSelector())
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        asyncio.set_event_loop(None)
        loop.close()


async def _scenario(qe: Any) -> dict[str, Any]:
    """Write two runs that tie on created_at, then read every recency surface."""
    qe._reset_memory_store()
    first = qe.new_run(**_IDENTITY)
    first.created_at = TICK
    first.status = "ready"
    first.result_json = {"overall_score": 82}
    second = qe.new_run(**_IDENTITY)
    second.created_at = TICK
    second.status = "ready"
    second.result_json = {"overall_score": 84}
    # Use the returned rows: Postgres assigns seq server-side and hands back the
    # stored row, while the fallback fills it in on the object it was given.
    stored_first = await qe.create_run(first)
    stored_second = await qe.create_run(second)

    latest = await qe.get_latest_for_subject("acc-a", "imported_note", "note-1")
    cached = await qe.get_cached(**_IDENTITY)
    trend = await qe.fetch_trend_points("acc-a", limit=10)

    return {
        # Scores in chart order, which is the observable both branches must share.
        "trend_scores": [point["overall_score"] for point in trend],
        "latest_score": None if latest is None else latest.result_json["overall_score"],
        "cached_score": None if cached is None else cached.result_json["overall_score"],
        "seqs_increase": stored_second.seq > stored_first.seq,
    }


@pytest.fixture
def scratch_database() -> Any:
    import psycopg

    admin_uri = os.environ[PG_URI_ENV]
    database = f"xhs_qparity_{uuid.uuid4().hex[:10]}"
    base = psycopg.conninfo.conninfo_to_dict(admin_uri)
    scratch_uri = psycopg.conninfo.make_conninfo(**{**base, "dbname": database})
    with psycopg.connect(admin_uri, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{database}"')
    try:
        yield scratch_uri
    finally:
        with psycopg.connect(admin_uri, autocommit=True) as admin:
            admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')


def test_quality_recency_matches_across_both_backends(scratch_database: str) -> None:
    from backend.db import pool as db_pool
    from backend.db import quality_evaluations as qe

    # With no pool initialized, create_run and every read take the fallback
    # branch, so this is the memory adapter's answer to the same scenario.
    memory_result = _run(_scenario(qe))

    os.environ["POSTGRES_URI"] = scratch_database
    try:
        postgres_result = _run(_postgres_run(qe, db_pool))
    finally:
        os.environ.pop("POSTGRES_URI", None)

    assert postgres_result == memory_result, json.dumps(
        {"postgres": postgres_result, "memory": memory_result}, indent=2
    )
    # Both branches must actually place the later-created run last on the chart;
    # agreeing on the wrong order would still pass a pure equality check.
    assert memory_result["trend_scores"] == [82.0, 84.0]
    assert memory_result["latest_score"] == 84
    assert memory_result["seqs_increase"] is True


async def _postgres_run(qe: Any, db_pool: Any) -> dict[str, Any]:
    await db_pool.init_pool()
    try:
        await qe.ensure_tables()
        assert db_pool.is_pool_ready(), "pool must be live or this proves nothing"
        return await _scenario(qe)
    finally:
        await db_pool.close_pool()
