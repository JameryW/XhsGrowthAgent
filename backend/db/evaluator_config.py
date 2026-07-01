"""Evaluator grader weights + training samples — learnable config storage.

Stores the RQGM agent-as-a-judge panel weights and decision thresholds so they
can be tuned per-account and eventually trained from real engagement feedback
(true co-evolution). Distinct from `system_config` (which holds global secrets
/ env-overrides): weights are learnable scalar parameters, not secrets.

Tables:
- `evaluator_config`: weight_key / account_id (nullable=global default) / value
- `evaluator_samples`: training samples — (dimensions, decision, engagement)
  collected from each evaluation + post-publish feedback, for future finetuning.

`account_id IS NULL` means the global default; per-account rows override it.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.db.pool import get_pool

logger = logging.getLogger("xhs_growth.db.evaluator_config")

# ── Default weights — mirror backend/agents/evaluator.py module constants ──
# Kept here so the DB layer is the single source of truth for defaults; the
# evaluator falls back to these when no DB row exists.

DEFAULT_DIMENSION_WEIGHTS: dict[str, float] = {
    "copywriting": 0.25,
    "visual": 0.20,
    "compliance": 0.20,
    "reach": 0.15,
    "audience": 0.20,
}
DEFAULT_PASS_THRESHOLD = 70.0
DEFAULT_REJECT_THRESHOLD = 50.0
DEFAULT_BIAS_PENALTY_THRESHOLD = 60.0
DEFAULT_BIAS_PENALTY = 5.0

# Flat key map — every tunable scalar the evaluator reads, with its default.
DEFAULT_WEIGHTS: dict[str, float] = {
    **{f"weight.{k}": v for k, v in DEFAULT_DIMENSION_WEIGHTS.items()},
    "threshold.pass": DEFAULT_PASS_THRESHOLD,
    "threshold.reject": DEFAULT_REJECT_THRESHOLD,
    "bias.penalty_threshold": DEFAULT_BIAS_PENALTY_THRESHOLD,
    "bias.penalty": DEFAULT_BIAS_PENALTY,
}


@dataclass
class EvaluatorWeights:
    """Resolved grader weights for one account (defaults overridden by DB rows).

    `dimension_weights` excludes bias_check (handled via penalty, not weighted avg),
    matching `_DIMENSION_WEIGHTS` in evaluator.py.
    """

    dimension_weights: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_DIMENSION_WEIGHTS)
    )
    pass_threshold: float = DEFAULT_PASS_THRESHOLD
    reject_threshold: float = DEFAULT_REJECT_THRESHOLD
    bias_penalty_threshold: float = DEFAULT_BIAS_PENALTY_THRESHOLD
    bias_penalty: float = DEFAULT_BIAS_PENALTY

    @property
    def required_dimensions(self) -> list[str]:
        return list(self.dimension_weights.keys()) + ["bias_check"]


# ── Table creation ──

_CREATE_CONFIG_SQL = """
CREATE TABLE IF NOT EXISTS evaluator_config (
    weight_key   TEXT NOT NULL,
    account_id   TEXT,
    weight_value DOUBLE PRECISION NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (weight_key, account_id)
);
"""

_CREATE_SAMPLES_SQL = """
CREATE TABLE IF NOT EXISTS evaluator_samples (
    id            SERIAL PRIMARY KEY,
    account_id    TEXT,
    thread_id     TEXT NOT NULL,
    dimensions    JSONB NOT NULL,
    overall_score DOUBLE PRECISION NOT NULL,
    decision      TEXT NOT NULL,
    label_source  TEXT NOT NULL,
    engagement    JSONB,
    created_at    TEXT NOT NULL DEFAULT ''
);
"""

_CREATE_SAMPLES_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_evaluator_samples_account
    ON evaluator_samples (account_id, created_at);
"""


async def ensure_tables() -> None:
    """Create evaluator_config + evaluator_samples tables if absent."""
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_CONFIG_SQL)
        await conn.execute(_CREATE_SAMPLES_SQL)
        await conn.execute(_CREATE_SAMPLES_INDEX_SQL)
    logger.info("evaluator_config + evaluator_samples tables ensured")


# ── Weight CRUD ──


async def load_weights(account_id: str | None = None) -> EvaluatorWeights:
    """Load resolved weights: global defaults overridden by global DB rows,
    then by per-account DB rows. Returns defaults if no rows / DB unavailable.

    ponytail: per-key COALESCE — global row wins over default, account row wins
    over global. No cross-key transactionality needed (weights are advisory).
    """
    weights = EvaluatorWeights()
    overrides = await _fetch_overrides(account_id)
    if not overrides:
        return weights

    for key, val in overrides.items():
        _apply_override(weights, key, val)
    return weights


async def _fetch_overrides(account_id: str | None) -> dict[str, float]:
    """Fetch global + per-account overrides, account winning on key clash."""
    from psycopg.rows import dict_row

    pool = get_pool()
    rows: dict[str, float] = {}
    try:
        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            # global first (account_id IS NULL), then account-specific override
            await cur.execute(
                "SELECT weight_key, weight_value FROM evaluator_config "
                "WHERE account_id IS NULL OR account_id = %s",
                (account_id,),
            )
            for r in await cur.fetchall():
                rows[r["weight_key"]] = float(r["weight_value"])
    except Exception as e:
        logger.warning("load_weights DB fetch failed, using defaults: %s", e)
        return {}
    return rows


def _apply_override(w: EvaluatorWeights, key: str, val: float) -> None:
    if key.startswith("weight."):
        dim = key.removeprefix("weight.")
        if dim in w.dimension_weights:
            w.dimension_weights[dim] = val
    elif key == "threshold.pass":
        w.pass_threshold = val
    elif key == "threshold.reject":
        w.reject_threshold = val
    elif key == "bias.penalty_threshold":
        w.bias_penalty_threshold = val
    elif key == "bias.penalty":
        w.bias_penalty = val


async def set_weight(key: str, value: float, account_id: str | None = None) -> None:
    """Upsert one weight override. Validates key against DEFAULT_WEIGHTS."""
    if key not in DEFAULT_WEIGHTS:
        raise ValueError(f"unknown evaluator weight key: {key}")
    now = datetime.now(UTC).isoformat()
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(
            """
            INSERT INTO evaluator_config (weight_key, account_id, weight_value, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (weight_key, account_id) DO UPDATE SET weight_value = EXCLUDED.weight_value,
                updated_at = EXCLUDED.updated_at
            """,
            (key, value, account_id, now),
        )


async def list_weights(account_id: str | None = None) -> list[dict[str, Any]]:
    """List all effective weights (default + override resolved) for inspection/UI."""
    resolved = await load_weights(account_id)
    flat = {
        **{f"weight.{k}": v for k, v in resolved.dimension_weights.items()},
        "threshold.pass": resolved.pass_threshold,
        "threshold.reject": resolved.reject_threshold,
        "bias.penalty_threshold": resolved.bias_penalty_threshold,
        "bias.penalty": resolved.bias_penalty,
    }
    return [
        {"weight_key": k, "value": v, "is_default": v == DEFAULT_WEIGHTS.get(k)}
        for k, v in flat.items()
    ]


# ── Training samples ──


@dataclass
class EvaluatorSample:
    """One training sample: evaluator judgment on content + optional real label."""

    account_id: str | None
    thread_id: str
    dimensions: list[dict[str, Any]]  # DimensionScore list
    overall_score: float
    decision: str
    label_source: str  # "evaluator" | "engagement" | "human_review"
    engagement: dict[str, Any] | None = None  # post-publish real metrics (weak label)
    created_at: str = ""


async def insert_sample(sample: EvaluatorSample) -> int:
    """Persist a training sample. Non-blocking on failure (caller swallows)."""
    pool = get_pool()
    now = sample.created_at or datetime.now(UTC).isoformat()
    from psycopg.rows import dict_row

    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            """
                INSERT INTO evaluator_samples
                    (account_id, thread_id, dimensions, overall_score, decision,
                     label_source, engagement, created_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
            (
                sample.account_id,
                sample.thread_id,
                json.dumps(sample.dimensions),
                sample.overall_score,
                sample.decision,
                sample.label_source,
                json.dumps(sample.engagement) if sample.engagement else None,
                now,
            ),
        )
        row = await cur.fetchone()
        return int(row["id"]) if row else -1


async def export_samples(account_id: str | None = None, limit: int = 1000) -> list[dict[str, Any]]:
    """Export samples as flat dicts for jsonl training format."""
    from psycopg.rows import dict_row

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if account_id:
            await cur.execute(
                "SELECT * FROM evaluator_samples WHERE account_id = %s "
                "ORDER BY created_at DESC LIMIT %s",
                (account_id, limit),
            )
        else:
            await cur.execute(
                "SELECT * FROM evaluator_samples ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        return list(await cur.fetchall())


async def backfill_engagement(thread_id: str, engagement: dict[str, Any]) -> int:
    """Back-fill real post-publish engagement onto the most recent sample for a thread.

    Called from analyst_node after publish — attaches the weak label (real likes/
    comments/collects) to the evaluator's original judgment sample. Returns rows
    updated (0 if no sample / DB unavailable).

    ponytail: UPDATE latest-by-thread; one thread may have multiple revisions,
    we label the most recent judgment. Non-blocking on DB failure.
    """
    pool = get_pool()
    async with pool.connection() as conn:
        cur = await conn.execute(
            """
            UPDATE evaluator_samples
            SET engagement = %s
            WHERE id = (
                SELECT id FROM evaluator_samples
                WHERE thread_id = %s ORDER BY created_at DESC LIMIT 1
            )
            """,
            (json.dumps(engagement), thread_id),
        )
        return cur.rowcount
