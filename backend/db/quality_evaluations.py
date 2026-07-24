"""Durable storage for user-visible RQGM quality evaluation runs.

Historical-note evaluations are an audit surface, not training samples.  This
module intentionally lives next to the app-level database modules and keeps a
small in-memory fallback so the API remains usable in fixture/dev mode when
Postgres is unavailable.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.db.pool import get_pool, is_pool_ready

logger = logging.getLogger("xhs_growth.db.quality_evaluations")


@dataclass
class QualityEvaluationRun:
    """One immutable evaluation attempt and its input/version metadata."""

    evaluation_id: str
    account_id: str
    subject_type: str
    subject_id: str
    assessment_type: str
    source_content_hash: str
    source_data_as_of: str = ""
    context_hash: str = ""
    evaluator_fingerprint: str = ""
    status: str = "running"
    result_json: dict[str, Any] = field(default_factory=dict)
    coverage_json: dict[str, Any] = field(default_factory=dict)
    thresholds_json: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = ""
    completed_at: str | None = None
    stale_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "evaluation_id": self.evaluation_id,
            "account_id": self.account_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "assessment_type": self.assessment_type,
            "source_content_hash": self.source_content_hash,
            "source_data_as_of": self.source_data_as_of,
            "context_hash": self.context_hash,
            "evaluator_fingerprint": self.evaluator_fingerprint,
            "status": self.status,
            "result_json": self.result_json,
            "coverage_json": self.coverage_json,
            "thresholds_json": self.thresholds_json,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "stale_at": self.stale_at,
        }


_mem_runs: dict[str, QualityEvaluationRun] = {}


def _reset_memory_store() -> None:
    """Test helper for the no-Postgres fallback."""
    _mem_runs.clear()


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS quality_evaluation_runs (
    evaluation_id          TEXT PRIMARY KEY,
    account_id             TEXT NOT NULL,
    subject_type           TEXT NOT NULL,
    subject_id             TEXT NOT NULL,
    assessment_type        TEXT NOT NULL,
    source_content_hash    TEXT NOT NULL,
    source_data_as_of      TEXT NOT NULL DEFAULT '',
    context_hash           TEXT NOT NULL DEFAULT '',
    evaluator_fingerprint  TEXT NOT NULL DEFAULT '',
    status                 TEXT NOT NULL,
    result_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    coverage_json          JSONB NOT NULL DEFAULT '{}'::jsonb,
    thresholds_json        JSONB NOT NULL DEFAULT '{}'::jsonb,
    error                  TEXT,
    created_at             TEXT NOT NULL,
    completed_at           TEXT,
    stale_at               TEXT
);
"""

_CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_quality_eval_subject
    ON quality_evaluation_runs (account_id, subject_type, subject_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_eval_status
    ON quality_evaluation_runs (account_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_quality_eval_identity
    ON quality_evaluation_runs (
        account_id, subject_type, subject_id, source_content_hash,
        context_hash, evaluator_fingerprint, created_at DESC
    );
"""


async def ensure_tables() -> None:
    """Create the additive quality-run table when the app pool is ready."""
    if not is_pool_ready():
        logger.debug("quality evaluation table ensure skipped: pool not ready")
        return
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_TABLE_SQL)
        await conn.execute(_CREATE_INDEX_SQL)
    logger.info("quality_evaluation_runs table ensured")


def _normalize_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(decoded) if isinstance(decoded, dict) else {}
    return {}


def _from_row(row: Any) -> QualityEvaluationRun | None:
    if row is None:
        return None
    if not isinstance(row, dict):
        # Keep tuple decoding aligned with the SELECT below.  This is useful
        # for lightweight fake cursors used by API/unit tests.
        if len(row) < 17:
            return None
        return QualityEvaluationRun(
            evaluation_id=str(row[0] or ""),
            account_id=str(row[1] or ""),
            subject_type=str(row[2] or ""),
            subject_id=str(row[3] or ""),
            assessment_type=str(row[4] or ""),
            source_content_hash=str(row[5] or ""),
            source_data_as_of=str(row[6] or ""),
            context_hash=str(row[7] or ""),
            evaluator_fingerprint=str(row[8] or ""),
            status=str(row[9] or ""),
            result_json=_normalize_json(row[10]),
            coverage_json=_normalize_json(row[11]),
            thresholds_json=_normalize_json(row[12]),
            error=str(row[13]) if row[13] is not None else None,
            created_at=str(row[14] or ""),
            completed_at=str(row[15]) if row[15] is not None else None,
            stale_at=str(row[16]) if row[16] is not None else None,
        )
    return QualityEvaluationRun(
        evaluation_id=str(row.get("evaluation_id") or ""),
        account_id=str(row.get("account_id") or ""),
        subject_type=str(row.get("subject_type") or ""),
        subject_id=str(row.get("subject_id") or ""),
        assessment_type=str(row.get("assessment_type") or ""),
        source_content_hash=str(row.get("source_content_hash") or ""),
        source_data_as_of=str(row.get("source_data_as_of") or ""),
        context_hash=str(row.get("context_hash") or ""),
        evaluator_fingerprint=str(row.get("evaluator_fingerprint") or ""),
        status=str(row.get("status") or ""),
        result_json=_normalize_json(row.get("result_json")),
        coverage_json=_normalize_json(row.get("coverage_json")),
        thresholds_json=_normalize_json(row.get("thresholds_json")),
        error=str(row["error"]) if row.get("error") is not None else None,
        created_at=str(row.get("created_at") or ""),
        completed_at=str(row["completed_at"]) if row.get("completed_at") is not None else None,
        stale_at=str(row["stale_at"]) if row.get("stale_at") is not None else None,
    )


_SELECT_COLUMNS = """
    evaluation_id, account_id, subject_type, subject_id, assessment_type,
    source_content_hash, source_data_as_of, context_hash, evaluator_fingerprint,
    status, result_json, coverage_json, thresholds_json, error, created_at,
    completed_at, stale_at
"""


def _matches(
    run: QualityEvaluationRun,
    *,
    account_id: str,
    subject_type: str,
    subject_id: str,
    assessment_type: str,
    source_content_hash: str,
    context_hash: str,
    evaluator_fingerprint: str,
) -> bool:
    return (
        run.account_id == account_id
        and run.subject_type == subject_type
        and run.subject_id == subject_id
        and run.assessment_type == assessment_type
        and run.source_content_hash == source_content_hash
        and run.context_hash == context_hash
        and run.evaluator_fingerprint == evaluator_fingerprint
    )


async def get_cached(
    *,
    account_id: str,
    subject_type: str,
    subject_id: str,
    assessment_type: str,
    source_content_hash: str,
    context_hash: str,
    evaluator_fingerprint: str,
    source_data_as_of: str | None = None,
) -> QualityEvaluationRun | None:
    """Return the latest reusable successful/partial run for an exact identity."""
    if not is_pool_ready():
        candidates = [
            run
            for run in _mem_runs.values()
            if _matches(
                run,
                account_id=account_id,
                subject_type=subject_type,
                subject_id=subject_id,
                assessment_type=assessment_type,
                source_content_hash=source_content_hash,
                context_hash=context_hash,
                evaluator_fingerprint=evaluator_fingerprint,
            )
            and run.status in {"ready", "partial"}
            and not run.stale_at
        ]
        return max(candidates, key=lambda run: run.created_at, default=None)
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            from psycopg.rows import dict_row

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""SELECT {_SELECT_COLUMNS} FROM quality_evaluation_runs
                    WHERE account_id = %s AND subject_type = %s AND subject_id = %s
                      AND assessment_type = %s AND source_content_hash = %s
                      AND context_hash = %s AND evaluator_fingerprint = %s
                      AND status IN ('ready', 'partial') AND stale_at IS NULL
                    ORDER BY created_at DESC LIMIT 1""",
                    (
                        account_id,
                        subject_type,
                        subject_id,
                        assessment_type,
                        source_content_hash,
                        context_hash,
                        evaluator_fingerprint,
                    ),
                )
                return _from_row(await cur.fetchone())
    except Exception as exc:
        logger.warning("quality evaluation cache lookup failed: %s", exc)
        return None


async def create_run(run: QualityEvaluationRun) -> QualityEvaluationRun:
    """Insert an immutable run.

    Idempotency is implemented by :func:`get_cached`; inserts deliberately do
    not use a uniqueness constraint so ``force=true`` can retain a new version
    with the same input/evaluator identity.
    """
    if not run.evaluation_id:
        run.evaluation_id = f"eval_{uuid.uuid4().hex}"
    if not run.created_at:
        run.created_at = datetime.now(UTC).isoformat()
    if not is_pool_ready():
        _mem_runs[run.evaluation_id] = run
        return run
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            from psycopg.rows import dict_row

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""INSERT INTO quality_evaluation_runs
                    (evaluation_id, account_id, subject_type, subject_id, assessment_type,
                     source_content_hash, source_data_as_of, context_hash,
                     evaluator_fingerprint, status, result_json, coverage_json,
                     thresholds_json, error, created_at, completed_at, stale_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING {_SELECT_COLUMNS}""",
                    (
                        run.evaluation_id,
                        run.account_id,
                        run.subject_type,
                        run.subject_id,
                        run.assessment_type,
                        run.source_content_hash,
                        run.source_data_as_of,
                        run.context_hash,
                        run.evaluator_fingerprint,
                        run.status,
                        json.dumps(run.result_json, ensure_ascii=False),
                        json.dumps(run.coverage_json, ensure_ascii=False),
                        json.dumps(run.thresholds_json, ensure_ascii=False),
                        run.error,
                        run.created_at,
                        run.completed_at,
                        run.stale_at,
                    ),
                )
                return _from_row(await cur.fetchone()) or run
    except Exception as exc:
        logger.warning("quality evaluation run insert failed; continuing: %s", exc)
        return run


async def update_run(run: QualityEvaluationRun) -> QualityEvaluationRun:
    """Update the mutable result/status fields of a run."""
    if not is_pool_ready():
        _mem_runs[run.evaluation_id] = run
        return run
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            from psycopg.rows import dict_row

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """UPDATE quality_evaluation_runs
                    SET status = %s, result_json = %s, coverage_json = %s,
                        thresholds_json = %s, error = %s, completed_at = %s,
                        stale_at = %s
                    WHERE evaluation_id = %s
                    RETURNING """
                    + _SELECT_COLUMNS,
                    (
                        run.status,
                        json.dumps(run.result_json, ensure_ascii=False),
                        json.dumps(run.coverage_json, ensure_ascii=False),
                        json.dumps(run.thresholds_json, ensure_ascii=False),
                        run.error,
                        run.completed_at,
                        run.stale_at,
                        run.evaluation_id,
                    ),
                )
                return _from_row(await cur.fetchone()) or run
    except Exception as exc:
        logger.warning("quality evaluation run update failed; continuing: %s", exc)
        return run


async def get_latest_for_subject(
    account_id: str,
    subject_type: str,
    subject_id: str,
    *,
    assessment_type: str = "rqgm_content_review",
) -> QualityEvaluationRun | None:
    """Return the latest run for a subject, including stale/degraded history."""
    account_id = (account_id or "").strip()
    subject_type = (subject_type or "").strip()
    subject_id = (subject_id or "").strip()
    if not account_id or not subject_type or not subject_id:
        return None
    if not is_pool_ready():
        candidates = [
            run
            for run in _mem_runs.values()
            if run.account_id == account_id
            and run.subject_type == subject_type
            and run.subject_id == subject_id
            and run.assessment_type == assessment_type
        ]
        return max(candidates, key=lambda run: run.created_at, default=None)
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            from psycopg.rows import dict_row

            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""SELECT {_SELECT_COLUMNS} FROM quality_evaluation_runs
                    WHERE account_id = %s AND subject_type = %s AND subject_id = %s
                      AND assessment_type = %s
                    ORDER BY created_at DESC LIMIT 1""",
                    (account_id, subject_type, subject_id, assessment_type),
                )
                return _from_row(await cur.fetchone())
    except Exception as exc:
        logger.warning("latest quality evaluation lookup failed: %s", exc)
        return None


def _run_to_trend_row(run: QualityEvaluationRun) -> dict[str, Any] | None:
    """Map a durable quality run into the trend endpoint's sample shape.

    Returns None when the run has no consumable score (degraded / incomplete).
    Historical-note RQGM evaluations live here rather than in
    ``evaluator_samples`` (training-only); the trend chart must include them.
    """
    result = run.result_json if isinstance(run.result_json, dict) else {}
    status = str(result.get("status") or run.status or "ready").lower()
    if bool(result.get("degraded")) or status in {
        "degraded",
        "failed",
        "running",
        "unavailable",
    }:
        return None
    score = result.get("overall_score")
    if score is None:
        return None
    try:
        score_f = float(score)
    except (TypeError, ValueError):
        return None
    created = str(run.completed_at or run.created_at or result.get("evaluated_at") or "")
    dims = result.get("dimensions") or []
    if not isinstance(dims, list):
        dims = []
    return {
        "created_at": created,
        "overall_score": score_f,
        "decision": str(result.get("decision") or ""),
        "dimensions": dims,
        "account_id": run.account_id,
        "status": status,
        "degraded": False,
        "data_as_of": run.source_data_as_of or created,
        "source": "quality_evaluation_run",
        "subject_type": run.subject_type,
        "subject_id": run.subject_id,
    }


async def fetch_trend_points(
    account_id: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    """Newest-first then reversed: ascending timeline of scorable quality runs.

    Used by ``GET /evaluation/trend`` so historical-note RQGM reviews appear
    alongside workflow evaluator samples.
    """
    limit = max(1, min(int(limit or 100), 500))
    if not is_pool_ready():
        rows = [
            row
            for run in _mem_runs.values()
            if (not account_id or run.account_id == account_id)
            for row in (_run_to_trend_row(run),)
            if row is not None
        ]
        rows.sort(key=lambda r: str(r.get("created_at") or ""))
        return rows[-limit:]

    try:
        from psycopg.rows import dict_row

        pool = get_pool()
        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            # Pull the newest N, then reverse to ascending for chart plotting.
            if account_id:
                await cur.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM quality_evaluation_runs
                    WHERE account_id = %s
                    ORDER BY COALESCE(completed_at, created_at) DESC
                    LIMIT %s
                    """,
                    (account_id, limit),
                )
            else:
                await cur.execute(
                    f"""
                    SELECT {_SELECT_COLUMNS}
                    FROM quality_evaluation_runs
                    ORDER BY COALESCE(completed_at, created_at) DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            runs = [_from_row(r) for r in await cur.fetchall()]
    except Exception as exc:
        logger.warning("fetch quality evaluation trend failed: %s", exc)
        return []

    points: list[dict[str, Any]] = []
    for run in runs:
        if run is None:
            continue
        row = _run_to_trend_row(run)
        if row is not None:
            points.append(row)
    points.sort(key=lambda r: str(r.get("created_at") or ""))
    return points


async def mark_subject_stale(
    account_id: str,
    subject_type: str,
    subject_id: str,
    *,
    reason: str = "source_changed",
) -> int:
    """Mark prior runs stale when content/context changes."""
    now = datetime.now(UTC).isoformat()
    count = 0
    if not is_pool_ready():
        for run in _mem_runs.values():
            if (
                run.account_id == account_id
                and run.subject_type == subject_type
                and run.subject_id == subject_id
                and not run.stale_at
            ):
                run.stale_at = now
                run.error = run.error or reason
                count += 1
        return count
    try:
        pool = get_pool()
        async with pool.connection() as conn:
            cur = await conn.execute(
                """UPDATE quality_evaluation_runs SET stale_at = %s,
                    error = COALESCE(error, %s)
                WHERE account_id = %s AND subject_type = %s AND subject_id = %s
                  AND stale_at IS NULL""",
                (now, reason, account_id, subject_type, subject_id),
            )
            count = int(getattr(cur, "rowcount", 0) or 0)
    except Exception as exc:
        logger.warning("mark quality evaluations stale failed: %s", exc)
    return count


def new_run(
    *,
    account_id: str,
    subject_type: str,
    subject_id: str,
    assessment_type: str,
    source_content_hash: str,
    source_data_as_of: str,
    context_hash: str,
    evaluator_fingerprint: str,
) -> QualityEvaluationRun:
    """Build a running run object for the API/service layer."""
    return QualityEvaluationRun(
        evaluation_id=f"eval_{uuid.uuid4().hex}",
        account_id=account_id,
        subject_type=subject_type,
        subject_id=subject_id,
        assessment_type=assessment_type,
        source_content_hash=source_content_hash,
        source_data_as_of=source_data_as_of,
        context_hash=context_hash,
        evaluator_fingerprint=evaluator_fingerprint,
        status="running",
        created_at=datetime.now(UTC).isoformat(),
    )
