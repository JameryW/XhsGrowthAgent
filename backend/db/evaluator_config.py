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

_CREATE_EPOCHS_SQL = """
CREATE TABLE IF NOT EXISTS evaluator_prompt_epochs (
    epoch_id      SERIAL PRIMARY KEY,
    bias_severity TEXT NOT NULL DEFAULT 'standard',
    note          TEXT NOT NULL DEFAULT '',
    active        BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TEXT NOT NULL DEFAULT ''
);
"""


async def ensure_tables() -> None:
    """Create evaluator_config + evaluator_samples + epochs tables if absent."""
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute(_CREATE_CONFIG_SQL)
        await conn.execute(_CREATE_SAMPLES_SQL)
        await conn.execute(_CREATE_SAMPLES_INDEX_SQL)
        await conn.execute(_CREATE_EPOCHS_SQL)
        await _ensure_default_epoch(conn)
    logger.info("evaluator_config + evaluator_samples + epochs tables ensured")


async def _ensure_default_epoch(conn: Any) -> None:
    """Seed a default active epoch if none exists (epoch-1 behavior)."""
    from psycopg.rows import dict_row

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT epoch_id FROM evaluator_prompt_epochs WHERE active = TRUE LIMIT 1"
        )
        if await cur.fetchone():
            return
        await cur.execute(
            "INSERT INTO evaluator_prompt_epochs (bias_severity, note, active, created_at) "
            "VALUES (%s, %s, TRUE, %s)",
            ("standard", "epoch-1 default prompt behavior", datetime.now(UTC).isoformat()),
        )


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


async def fetch_trend(account_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    """Fetch samples in ascending time order for trend visualization.

    Returns minimal fields (created_at, overall_score, decision, dimensions)
    so the frontend can plot an overall-score timeline + per-dimension trends.
    """
    from psycopg.rows import dict_row

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if account_id:
            await cur.execute(
                "SELECT created_at, overall_score, decision, dimensions FROM "
                "evaluator_samples WHERE account_id = %s ORDER BY created_at ASC LIMIT %s",
                (account_id, limit),
            )
        else:
            await cur.execute(
                "SELECT created_at, overall_score, decision, dimensions FROM "
                "evaluator_samples ORDER BY created_at ASC LIMIT %s",
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


# ── Online weight training (statistical fit, no GPU) ──


# Dimensions that participate in the weighted average (bias_check handled via penalty).
WEIGHTED_DIMENSIONS = list(DEFAULT_DIMENSION_WEIGHTS.keys())

# Min samples with engagement labels before training kicks in.
MIN_TRAIN_SAMPLES = 10


@dataclass
class TrainingReport:
    """Result of a weight-training run — returned for inspection / dry-run."""

    account_id: str | None
    n_samples: int
    fitted_weights: dict[str, float]
    pass_threshold: float
    reject_threshold: float
    r_squared: float
    applied: bool = False
    note: str = ""


def _engagement_rate(engagement: dict[str, Any] | None) -> float | None:
    """engagement_rate = (likes+collects+comments+shares) / views. None if no views."""
    if not engagement:
        return None
    views = float(engagement.get("views") or 0)
    if views <= 0:
        return None
    total = (
        float(engagement.get("likes") or 0)
        + float(engagement.get("collects") or 0)
        + float(engagement.get("comments") or 0)
        + float(engagement.get("shares") or 0)
    )
    return total / views


def _dim_score(dimensions: list[dict[str, Any]], name: str) -> float:
    """Extract one dimension's score (0-100) from a sample's dimensions list."""
    for d in dimensions:
        if isinstance(d, dict) and d.get("dimension") == name:
            try:
                return float(d.get("score") or 70.0)
            except (TypeError, ValueError):
                return 70.0
    return 70.0


def fit_weights(samples: list[dict[str, Any]]) -> TrainingReport:
    """Fit dimension weights from labeled samples via normalized linear regression.

    Signal: engagement_rate (weak label) ~ sum(dim_score * weight).
    Algorithm: ordinary least squares on standardized features, then take |coef|,
    normalize to sum=1. Thresholds tuned from decision/engagement confusion.

    ponytail: statistical heuristic, not deep learning — needs no GPU, gives a
    data-driven starting point that beats hardcoded defaults once samples accrue.
    Falls back to defaults when samples are too few or degenerate.
    """
    import numpy as np

    # Build (X, y) from samples that have an engagement label.
    rows: list[tuple[list[float], float]] = []
    for s in samples:
        rate = _engagement_rate(s.get("engagement"))
        if rate is None:
            continue
        dims = s.get("dimensions") or []
        feats = [_dim_score(dims, name) / 100.0 for name in WEIGHTED_DIMENSIONS]
        rows.append((feats, rate))

    n = len(rows)
    if n < MIN_TRAIN_SAMPLES:
        return TrainingReport(
            account_id=None,
            n_samples=n,
            fitted_weights=dict(DEFAULT_DIMENSION_WEIGHTS),
            pass_threshold=DEFAULT_PASS_THRESHOLD,
            reject_threshold=DEFAULT_REJECT_THRESHOLD,
            r_squared=0.0,
            note=f"only {n} labeled samples (< {MIN_TRAIN_SAMPLES}), keeping defaults",
        )

    X = np.array([r[0] for r in rows])  # noqa: N806  # (n, 5) numpy convention
    y = np.array([r[1] for r in rows])  # (n,)

    # Standardize features for comparable coefficients.
    x_mean = X.mean(axis=0)
    x_std = X.std(axis=0)
    x_std_safe = np.where(x_std == 0, 1.0, x_std)
    Xz = (X - x_mean) / x_std_safe  # noqa: N806

    # OLS: coefs = (Xz^T Xz)^-1 Xz^T y, with intercept via centering y.
    y_mean = y.mean()
    yc = y - y_mean
    try:
        coefs = np.linalg.lstsq(Xz, yc, rcond=None)[0]  # (5,)
    except np.linalg.LinAlgError:
        return TrainingReport(
            account_id=None,
            n_samples=n,
            fitted_weights=dict(DEFAULT_DIMENSION_WEIGHTS),
            pass_threshold=DEFAULT_PASS_THRESHOLD,
            reject_threshold=DEFAULT_REJECT_THRESHOLD,
            r_squared=0.0,
            note="least-squares failed (degenerate matrix), keeping defaults",
        )

    # R² on the fit.
    pred = Xz @ coefs + y_mean
    ss_res = float(np.sum((y - pred) ** 2))
    ss_tot = float(np.sum(yc**2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

    # Weights = |coef| normalized to sum=1 (magnitude = predictive importance).
    abs_coefs = np.abs(coefs)
    total = float(abs_coefs.sum())
    if total <= 0:
        fitted = dict(DEFAULT_DIMENSION_WEIGHTS)
    else:
        fitted = {name: float(abs_coefs[i] / total) for i, name in enumerate(WEIGHTED_DIMENSIONS)}

    # Threshold tuning: split samples by engagement median, find score thresholds
    # that best separate high/low engagement. ponytail: simple quantile heuristic.
    med = float(np.median(y))
    w_vec = np.array([fitted[n] for n in WEIGHTED_DIMENSIONS])
    high = [float(X[i] @ w_vec) * 100 for i in range(n) if y[i] >= med]
    low = [float(X[i] @ w_vec) * 100 for i in range(n) if y[i] < med]
    pass_t, reject_t = _tune_thresholds(high, low)

    return TrainingReport(
        account_id=None,
        n_samples=n,
        fitted_weights=fitted,
        pass_threshold=pass_t,
        reject_threshold=reject_t,
        r_squared=r_squared,
        note="fitted from engagement weak labels",
    )


def _tune_thresholds(high: list[float], low: list[float]) -> tuple[float, float]:
    """Tune pass/reject thresholds from high/low engagement weighted scores.

    pass = high-group 25th percentile (most low-engagement content stays below).
    reject = low-group 75th percentile (clearly weak content falls below).
    Clamped to sensible bands; falls back to defaults if groups too small.
    """
    import numpy as np

    if len(high) < 3 or len(low) < 3:
        return DEFAULT_PASS_THRESHOLD, DEFAULT_REJECT_THRESHOLD
    pass_t = float(np.percentile(high, 25))
    reject_t = float(np.percentile(low, 75))
    # Keep ordering sane and within plausible bands.
    pass_t = max(60.0, min(85.0, pass_t))
    reject_t = max(40.0, min(60.0, reject_t))
    if pass_t <= reject_t:
        pass_t, reject_t = DEFAULT_PASS_THRESHOLD, DEFAULT_REJECT_THRESHOLD
    return pass_t, reject_t


async def fetch_labeled_samples(account_id: str | None, limit: int = 5000) -> list[dict[str, Any]]:
    """Fetch samples that have an engagement weak label (for training)."""
    from psycopg.rows import dict_row

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        if account_id:
            await cur.execute(
                "SELECT * FROM evaluator_samples WHERE account_id = %s "
                "AND engagement IS NOT NULL ORDER BY created_at DESC LIMIT %s",
                (account_id, limit),
            )
        else:
            await cur.execute(
                "SELECT * FROM evaluator_samples WHERE engagement IS NOT NULL "
                "ORDER BY created_at DESC LIMIT %s",
                (limit,),
            )
        return list(await cur.fetchall())


async def train_weights(account_id: str | None = None, *, apply: bool = False) -> TrainingReport:
    """Train weights from labeled samples; optionally write back to evaluator_config.

    ponytail: non-blocking on DB failure — returns a report with defaults + note.
    """
    try:
        samples = await fetch_labeled_samples(account_id)
    except Exception as e:
        logger.warning("train_weights: fetch failed, using defaults: %s", e)
        samples = []

    report = fit_weights(samples)
    report.account_id = account_id

    if not apply:
        report.note = report.note + " (dry-run, not applied)"
        return report

    if report.n_samples < MIN_TRAIN_SAMPLES:
        return report  # keep defaults, don't write

    # Write fitted weights + thresholds back to DB.
    try:
        for name, w in report.fitted_weights.items():
            await set_weight(f"weight.{name}", w, account_id)
        await set_weight("threshold.pass", report.pass_threshold, account_id)
        await set_weight("threshold.reject", report.reject_threshold, account_id)
        report.applied = True
    except Exception as e:
        logger.warning("train_weights: apply failed: %s", e)
        report.note = report.note + f" (apply failed: {e})"
    return report


# ── Prompt epoch co-evolution (Red Queen epoch boundary) ──

# bias_severity levels → prompt措辞注入。evolve 脚本根据近期样本 bias_check 表现在这些间切换。
# standard = epoch-1 默认；strict/very_strict = 面板偏宽松时加严；lenient = 面板过严时放宽。
BIAS_SEVERITY_LEVELS = ("lenient", "standard", "strict", "very_strict")

# Decision bands for mean bias_severity (0-100, 越高越糟).
# High mean → panel lenient (偏倚少被检出) → tighten. Low mean → panel harsh → relax.
LENIENT_BAND = 75.0
HARSH_BAND = 45.0


def next_severity(current: str, avg_bias: float | None) -> str:
    """Pick next epoch's bias_severity from current + recent bias_check mean.

    ponytail: rule-driven epoch evolution (not LLM self-rewrite). Steps one level
    at a time toward the signal; no-op if signal missing or in standard band.
    """
    if avg_bias is None:
        return current  # no samples → no evolution
    idx = BIAS_SEVERITY_LEVELS.index(current) if current in BIAS_SEVERITY_LEVELS else 1
    if avg_bias >= LENIENT_BAND and idx < len(BIAS_SEVERITY_LEVELS) - 1:
        return BIAS_SEVERITY_LEVELS[idx + 1]  # tighten
    if avg_bias <= HARSH_BAND and idx > 0:
        return BIAS_SEVERITY_LEVELS[idx - 1]  # relax
    return current  # within standard band, hold


BIAS_SEVERITY_NOTES: dict[str, str] = {
    "lenient": "（当前 epoch: 面板近期偏严，本 epoch 适度放宽对模糊表达的判定，保持与人类均衡）",
    "standard": "（当前 epoch: 标准严苛度，与人类评审同等）",
    "strict": "（当前 epoch: 面板近期偏宽松，本 epoch 加严对套路化/AI 味表达的判定）",
    "very_strict": (
        "（当前 epoch: 面板近期明显过度接受 AI 内容，本 epoch 对模糊/套路化表达从严，宁可误杀）"
    ),
}


@dataclass
class PromptEpoch:
    """One prompt epoch — pins evaluation criteria for self-improvement stability."""

    epoch_id: int
    bias_severity: str
    note: str
    active: bool
    created_at: str


async def get_active_epoch() -> PromptEpoch:
    """Return the active epoch; falls back to a synthetic default if DB unavailable."""
    from psycopg.rows import dict_row

    try:
        pool = get_pool()
        async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT * FROM evaluator_prompt_epochs WHERE active = TRUE "
                "ORDER BY epoch_id DESC LIMIT 1"
            )
            row = await cur.fetchone()
            if row:
                return PromptEpoch(
                    epoch_id=int(row["epoch_id"]),
                    bias_severity=str(row["bias_severity"]),
                    note=str(row.get("note") or ""),
                    active=True,
                    created_at=str(row.get("created_at") or ""),
                )
    except Exception as e:
        logger.debug("get_active_epoch failed, using default: %s", e)
    return PromptEpoch(0, "standard", "default (no DB)", True, "")


async def list_epochs() -> list[PromptEpoch]:
    """List all epochs, newest first."""
    from psycopg.rows import dict_row

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute("SELECT * FROM evaluator_prompt_epochs ORDER BY epoch_id DESC")
        rows = await cur.fetchall()
    return [
        PromptEpoch(
            epoch_id=int(r["epoch_id"]),
            bias_severity=str(r["bias_severity"]),
            note=str(r.get("note") or ""),
            active=bool(r["active"]),
            created_at=str(r.get("created_at") or ""),
        )
        for r in rows
    ]


async def activate_epoch(epoch_id: int) -> bool:
    """Activate one epoch, deactivating all others. Returns True if epoch existed."""
    pool = get_pool()
    async with pool.connection() as conn:
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT epoch_id FROM evaluator_prompt_epochs WHERE epoch_id = %s", (epoch_id,)
            )
            if not await cur.fetchone():
                return False
        await conn.execute("UPDATE evaluator_prompt_epochs SET active = FALSE")
        await conn.execute(
            "UPDATE evaluator_prompt_epochs SET active = TRUE WHERE epoch_id = %s", (epoch_id,)
        )
    return True


async def create_epoch(bias_severity: str, note: str = "") -> PromptEpoch:
    """Create a new epoch and activate it (deactivating others).

    ponytail: new epoch auto-activates — epoch boundary = criteria switch per
    RQGM theory (within-epoch criteria stay fixed for self-improvement stability).
    """
    if bias_severity not in BIAS_SEVERITY_LEVELS:
        raise ValueError(f"bias_severity must be one of {BIAS_SEVERITY_LEVELS}")
    now = datetime.now(UTC).isoformat()
    pool = get_pool()
    async with pool.connection() as conn:
        await conn.execute("UPDATE evaluator_prompt_epochs SET active = FALSE")
        from psycopg.rows import dict_row

        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "INSERT INTO evaluator_prompt_epochs (bias_severity, note, active, created_at) "
                "VALUES (%s, %s, TRUE, %s) RETURNING epoch_id",
                (bias_severity, note, now),
            )
            row = await cur.fetchone()
            eid = int(row["epoch_id"]) if row else -1
    return PromptEpoch(eid, bias_severity, note, True, now)


async def avg_bias_score(limit: int = 100) -> float | None:
    """Mean bias_severity across recent samples — the signal for epoch evolution.

    bias_severity = 检测到的偏倚严重度（越高越糟）。High mean → panel is lenient
    (seldom flags bias) → next epoch should tighten. Low mean → panel is harsh
    → next epoch should relax.

    旧样本无 bias_severity 字段时回退 100 - bias_check.score（score=校准建议分，
    越高越无需调整，故反推 severity）。新样本由 LLM 独立产出 bias_severity。
    """
    from psycopg.rows import dict_row

    pool = get_pool()
    async with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT dimensions FROM evaluator_samples ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        rows = await cur.fetchall()
    scores: list[float] = []
    for r in rows:
        dims = r.get("dimensions") or []
        if isinstance(dims, str):
            try:
                dims = json.loads(dims)
            except (ValueError, TypeError):
                dims = []
        for d in dims:
            if isinstance(d, dict) and d.get("dimension") == "bias_check":
                sev = _to_float_severity(d.get("bias_severity"), d.get("score"))
                scores.append(sev)
    if not scores:
        return None
    return sum(scores) / len(scores)


def _to_float_severity(sev: Any, score: Any) -> float:
    """Resolve bias_severity: explicit field wins, else fall back to 100 - score."""
    try:
        if sev is not None:
            return float(sev)
    except (TypeError, ValueError):
        pass
    try:
        return 100.0 - float(score)
    except (TypeError, ValueError):
        return 100.0  # 无法解析 → 视为最大偏倚
