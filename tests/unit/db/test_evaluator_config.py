"""Tests for evaluator_config DB module (unit-level, mock-based).

Covers: default fallback, per-account override resolution, set_weight upsert,
insert_sample, export_samples. No real PostgreSQL needed.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_mock_pool(conn):
    mock_pool = MagicMock()

    @asynccontextmanager
    async def conn_ctx(*_args, **_kwargs):
        yield conn

    mock_pool.connection = conn_ctx
    return mock_pool


def _make_mock_conn(cursor=None, execute_mock=None):
    mock_conn = MagicMock()

    @asynccontextmanager
    async def cursor_ctx(*_args, **_kwargs):
        yield cursor

    mock_conn.cursor = cursor_ctx
    mock_conn.execute = execute_mock or AsyncMock()
    return mock_conn


@pytest.mark.asyncio
async def test_load_weights_defaults_when_no_rows():
    """No DB rows → returns all defaults."""
    from backend.db.evaluator_config import DEFAULT_WEIGHTS, EvaluatorWeights, load_weights

    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[])
    conn = _make_mock_conn(cursor=cursor)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        w = await load_weights("acct1")
    assert isinstance(w, EvaluatorWeights)
    assert w.pass_threshold == DEFAULT_WEIGHTS["threshold.pass"]
    assert w.dimension_weights["copywriting"] == DEFAULT_WEIGHTS["weight.copywriting"]
    assert w.required_dimensions == [
        "copywriting",
        "visual",
        "compliance",
        "reach",
        "audience",
        "ai_taste",
        "image_quality",
        "commercial_tone",
        "altruism",
        "bias_check",
    ]


@pytest.mark.asyncio
async def test_load_weights_per_account_overrides_global():
    """Account row wins over global row on key clash; both win over defaults."""
    from backend.db.evaluator_config import load_weights

    rows = [
        {"weight_key": "weight.copywriting", "weight_value": 0.30},  # global
        {"weight_key": "threshold.pass", "weight_value": 75.0},  # global
        {"weight_key": "weight.copywriting", "weight_value": 0.40},  # account wins
    ]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    conn = _make_mock_conn(cursor=cursor)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        w = await load_weights("acct1")
    assert w.dimension_weights["copywriting"] == 0.40  # account override
    assert w.pass_threshold == 75.0  # global, no account override


@pytest.mark.asyncio
async def test_load_weights_falls_back_on_db_error():
    """DB exception → defaults, no raise (non-blocking contract)."""
    from backend.db.evaluator_config import EvaluatorWeights, load_weights

    pool = MagicMock()
    pool.connection = MagicMock(side_effect=RuntimeError("db down"))
    with patch("backend.db.evaluator_config.get_pool", return_value=pool):
        w = await load_weights("acct1")
    assert isinstance(w, EvaluatorWeights)
    assert w.pass_threshold == 70.0  # default


@pytest.mark.asyncio
async def test_set_weight_validates_key_and_upserts():
    """Unknown key raises; valid key issues INSERT ... ON CONFLICT."""
    from backend.db.evaluator_config import set_weight

    execute_mock = AsyncMock()
    conn = _make_mock_conn(execute_mock=execute_mock)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        await set_weight("weight.copywriting", 0.35, account_id="acct1")
    execute_mock.assert_awaited_once()
    # args: (sql, (key, value, account_id, updated_at))
    args = execute_mock.await_args.args
    assert args[1][0] == "weight.copywriting"
    assert args[1][1] == 0.35
    assert args[1][2] == "acct1"

    with pytest.raises(ValueError):
        await set_weight("weight.bogus", 1.0)


@pytest.mark.asyncio
async def test_insert_sample_persists_and_returns_id():
    from backend.db.evaluator_config import EvaluatorSample, insert_sample

    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value={"id": 42})
    conn = _make_mock_conn(cursor=cursor)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        sid = await insert_sample(
            EvaluatorSample(
                account_id="acct1",
                thread_id="t1",
                dimensions=[{"dimension": "copywriting", "score": 80}],
                overall_score=80.0,
                decision="approved",
                label_source="evaluator",
            )
        )
    assert sid == 42
    # 2nd positional arg is the params tuple; dimensions serialized to JSON
    params = cursor.execute.await_args.args[1]
    assert params[0] == "acct1"
    assert params[1] == "t1"
    assert json.loads(params[2]) == [{"dimension": "copywriting", "score": 80}]
    assert params[4] == "approved"
    assert params[5] == "evaluator"


@pytest.mark.asyncio
async def test_export_samples_returns_rows():
    from backend.db.evaluator_config import export_samples

    rows = [{"id": 1, "thread_id": "t1", "decision": "approved"}]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    conn = _make_mock_conn(cursor=cursor)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        out = await export_samples("acct1", limit=50)
    assert out == rows


@pytest.mark.asyncio
async def test_backfill_engagement_updates_latest_sample():
    """backfill_engagement UPDATEs the most recent sample for a thread."""
    from backend.db.evaluator_config import backfill_engagement

    cursor = MagicMock()
    cursor.rowcount = 1
    conn = MagicMock()
    conn.execute = AsyncMock(return_value=cursor)

    @asynccontextmanager
    async def conn_ctx(*_args, **_kwargs):
        yield conn

    pool = MagicMock()
    pool.connection = conn_ctx
    with patch("backend.db.evaluator_config.get_pool", return_value=pool):
        n = await backfill_engagement("t1", {"likes": 50, "comments": 3})
    assert n == 1
    sql_args = conn.execute.await_args.args
    assert "UPDATE evaluator_samples" in sql_args[0]
    assert sql_args[1][0] == json.dumps({"likes": 50, "comments": 3})
    assert sql_args[1][1] == "t1"


def test_apply_override_unknown_key_ignored():
    """Unknown keys are silently skipped (forward-compat with new DB rows)."""
    from backend.db.evaluator_config import (
        DEFAULT_DIMENSION_WEIGHTS,
        EvaluatorWeights,
        _apply_override,
    )

    w = EvaluatorWeights()
    _apply_override(w, "weight.bogus", 1.0)
    _apply_override(w, "unknown.thing", 1.0)
    assert w.dimension_weights["copywriting"] == DEFAULT_DIMENSION_WEIGHTS["copywriting"]
    assert "altruism" in w.dimension_weights


# ── Online weight training (fit_weights) ──


def _sample(dim_scores: dict[str, float], views: int, likes: int) -> dict:
    """Build a sample row shape: dimensions + engagement weak label."""
    return {
        "dimensions": [{"dimension": name, "score": sc} for name, sc in dim_scores.items()]
        + [{"dimension": "bias_check", "score": 80}],
        "engagement": {"views": views, "likes": likes, "collects": 0, "comments": 0, "shares": 0},
        "overall_score": sum(dim_scores.values()) / len(dim_scores),
        "decision": "approved",
    }


def test_fit_weights_too_few_samples_keeps_defaults():
    """Below MIN_TRAIN_SAMPLES → defaults returned, no fit."""
    from backend.db.evaluator_config import DEFAULT_DIMENSION_WEIGHTS, fit_weights

    samples = [
        _sample(
            {"copywriting": 90, "visual": 80, "compliance": 90, "reach": 70, "audience": 85},
            1000,
            50,
        )
    ]
    rep = fit_weights(samples)
    assert rep.n_samples == 1
    assert rep.fitted_weights == DEFAULT_DIMENSION_WEIGHTS
    assert "keeping defaults" in rep.note


def test_fit_weights_no_engagement_label_keeps_defaults():
    """Samples without engagement label are skipped → effective n too low."""
    from backend.db.evaluator_config import DEFAULT_DIMENSION_WEIGHTS, fit_weights

    samples = [{"dimensions": [], "engagement": None} for _ in range(20)]
    rep = fit_weights(samples)
    assert rep.fitted_weights == DEFAULT_DIMENSION_WEIGHTS
    assert rep.n_samples == 0


def test_fit_weights_recovers_predictive_dimension():
    """When one dimension strongly predicts engagement, its fitted weight should
    be the largest (or at least non-default and skewed toward it)."""
    # copywriting score alone determines engagement; others random-ish.
    import random

    from backend.db.evaluator_config import fit_weights

    rng = random.Random(42)
    samples = []
    for _ in range(40):
        cw = rng.uniform(40, 100)
        # engagement rate tracks copywriting score
        rate = cw / 100.0 * 0.2
        views = 1000
        likes = int(rate * views)
        samples.append(
            _sample(
                {
                    "copywriting": cw,
                    "visual": rng.uniform(40, 100),
                    "compliance": rng.uniform(40, 100),
                    "reach": rng.uniform(40, 100),
                    "audience": rng.uniform(40, 100),
                },
                views,
                likes,
            )
        )
    rep = fit_weights(samples)
    assert rep.n_samples == 40
    assert rep.r_squared > 0.3  # copywriting explains most variance
    # copywriting should be the dominant fitted weight
    assert rep.fitted_weights["copywriting"] == max(rep.fitted_weights.values())
    # weights sum ~1
    total = sum(rep.fitted_weights.values())
    assert abs(total - 1.0) < 0.01


def test_fit_weights_degenerate_uniform_returns_defaults():
    """All-identical features → std=0 → lstsq still works via safe-divide; weights
    may be uniform. Verify no crash and weights sum to 1 (or defaults)."""
    from backend.db.evaluator_config import fit_weights

    samples = [
        _sample(
            {"copywriting": 80, "visual": 80, "compliance": 80, "reach": 80, "audience": 80},
            1000,
            100,
        )
        for _ in range(15)
    ]
    rep = fit_weights(samples)
    # Either defaults (if total=0 fallback) or uniform-ish; both acceptable.
    total = sum(rep.fitted_weights.values())
    assert abs(total - 1.0) < 0.01 or rep.fitted_weights["copywriting"] == 0.25


def test_engagement_rate_helper():
    from backend.db.evaluator_config import _engagement_rate

    assert _engagement_rate(None) is None
    assert _engagement_rate({"views": 0, "likes": 10}) is None
    assert (
        _engagement_rate({"views": 1000, "likes": 50, "collects": 10, "comments": 5, "shares": 2})
        == 0.067
    )


# ── Prompt epoch co-evolution ──


def test_next_severity_no_signal_holds():
    """No samples → no evolution."""
    from backend.db.evaluator_config import next_severity

    assert next_severity("standard", None) == "standard"


def test_next_severity_lenient_panel_tightens():
    """High mean bias_severity (panel lenient, bias seldom flagged) → step stricter."""
    from backend.db.evaluator_config import next_severity

    assert next_severity("standard", 80.0) == "strict"
    assert next_severity("strict", 80.0) == "very_strict"
    # already max → hold
    assert next_severity("very_strict", 95.0) == "very_strict"


def test_next_severity_harsh_panel_relaxes():
    """Low mean bias_severity (panel harsh) → step lenient."""
    from backend.db.evaluator_config import next_severity

    assert next_severity("standard", 40.0) == "lenient"
    assert next_severity("strict", 40.0) == "standard"
    # already min → hold
    assert next_severity("lenient", 10.0) == "lenient"


def test_next_severity_standard_band_holds():
    """Mid-band signal → no change."""
    from backend.db.evaluator_config import next_severity

    assert next_severity("standard", 60.0) == "standard"
    assert next_severity("strict", 60.0) == "strict"


@pytest.mark.asyncio
async def test_get_active_epoch_falls_back_on_no_db():
    """No pool / DB error → synthetic default epoch (standard)."""
    from backend.db.evaluator_config import PromptEpoch, get_active_epoch

    pool = MagicMock()
    pool.connection = MagicMock(side_effect=RuntimeError("db down"))
    with patch("backend.db.evaluator_config.get_pool", return_value=pool):
        ep = await get_active_epoch()
    assert isinstance(ep, PromptEpoch)
    assert ep.bias_severity == "standard"
    assert ep.epoch_id == 0


@pytest.mark.asyncio
async def test_create_epoch_validates_severity():
    """Unknown severity raises; valid severity inserts + activates."""
    from backend.db.evaluator_config import create_epoch

    with pytest.raises(ValueError):
        await create_epoch("bogus", note="x")

    cur = MagicMock()
    cur.execute = AsyncMock()
    cur.fetchone = AsyncMock(return_value={"epoch_id": 7})
    conn = _make_mock_conn(cursor=cur)  # conn.execute is AsyncMock by default

    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        ep = await create_epoch("strict", note="test")
    assert ep.epoch_id == 7
    assert ep.bias_severity == "strict"
    assert ep.active is True
    # conn.execute deactivates existing; cur.execute inserts returning epoch_id
    assert "UPDATE" in conn.execute.await_args.args[0]
    assert "INSERT" in cur.execute.await_args.args[0]


@pytest.mark.asyncio
async def test_avg_bias_score_extracts_bias_dim():
    """avg_bias_score reads bias_severity; falls back to 100 - score for old samples."""
    import json as _json

    from backend.db.evaluator_config import avg_bias_score

    rows = [
        {
            "dimensions": _json.dumps(
                [
                    {"dimension": "copywriting", "score": 80},
                    # old sample: no bias_severity → fall back 100 - 70 = 30
                    {"dimension": "bias_check", "score": 70},
                ]
            )
        },
        # old sample: score 50 → fall back 50
        {"dimensions": _json.dumps([{"dimension": "bias_check", "score": 50}])},
        # new sample: explicit bias_severity wins over score
        {
            "dimensions": _json.dumps(
                [{"dimension": "bias_check", "score": 90, "bias_severity": 20}]
            )
        },
        {"dimensions": _json.dumps([{"dimension": "visual", "score": 90}])},  # no bias_check
    ]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    conn = _make_mock_conn(cursor=cursor)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        avg = await avg_bias_score(limit=100)
    # (30 + 50 + 20) / 3
    assert avg == 100.0 / 3


@pytest.mark.asyncio
async def test_avg_bias_score_no_samples_returns_none():
    from backend.db.evaluator_config import avg_bias_score

    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=[])
    conn = _make_mock_conn(cursor=cursor)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        avg = await avg_bias_score(limit=100)
    assert avg is None


# ── Trend ──


@pytest.mark.asyncio
async def test_fetch_trend_returns_asc_rows():
    """fetch_trend returns minimal fields in ascending time order."""
    from backend.db.evaluator_config import fetch_trend

    rows = [
        {
            "created_at": "2026-07-01T01:00:00",
            "overall_score": 80.0,
            "decision": "approved",
            "dimensions": [],
        },
        {
            "created_at": "2026-07-01T02:00:00",
            "overall_score": 55.0,
            "decision": "needs_revision",
            "dimensions": [],
        },
    ]
    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchall = AsyncMock(return_value=rows)
    conn = _make_mock_conn(cursor=cursor)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        out = await fetch_trend("acct1", limit=50)
    assert out == rows
    # ASC ordering requested
    sql = cursor.execute.await_args.args[0]
    assert "ORDER BY created_at ASC" in sql


# ── Online co-evolution: maybe_evolve ──


@pytest.mark.asyncio
async def test_count_labeled_since_counts_engagement_rows():
    """count_labeled_since issues parameterized COUNT with since_iso cutoff."""
    from backend.db.evaluator_config import count_labeled_since

    cursor = MagicMock()
    cursor.execute = AsyncMock()
    cursor.fetchone = AsyncMock(return_value=(7,))
    conn = _make_mock_conn(cursor=cursor)
    with patch("backend.db.evaluator_config.get_pool", return_value=_make_mock_pool(conn)):
        n = await count_labeled_since("2026-07-01T00:00:00", "acct1")
    assert n == 7
    sql = cursor.execute.await_args.args[0]
    assert "COUNT(*)" in sql
    assert "engagement IS NOT NULL" in sql
    assert "created_at > %s" in sql
    assert "account_id = %s" in sql


@pytest.mark.asyncio
async def test_maybe_evolve_skips_below_threshold():
    """Fewer than MIN_EVOLVE_SAMPLES new samples → no refit, no epoch change."""
    from backend.db.evaluator_config import MIN_EVOLVE_SAMPLES, maybe_evolve

    with (
        patch(
            "backend.db.evaluator_config.get_active_epoch",
            AsyncMock(return_value=MagicMock(created_at="t0", bias_severity="standard")),
        ),
        patch(
            "backend.db.evaluator_config.count_labeled_since",
            AsyncMock(return_value=MIN_EVOLVE_SAMPLES - 1),
        ),
        patch("backend.db.evaluator_config.train_weights", AsyncMock()) as tw,
        patch("backend.db.evaluator_config.create_epoch", AsyncMock()) as ce,
    ):
        report = await maybe_evolve("acct1")
    assert report["action"] == "skip"
    assert "below threshold" in report["reason"]
    tw.assert_not_awaited()
    ce.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_evolve_refits_and_advances_epoch_when_signal_moves():
    """Enough new samples + bias out of band → refit weights + new epoch."""
    from backend.db.evaluator_config import MIN_EVOLVE_SAMPLES, maybe_evolve

    epoch = MagicMock(created_at="t0", bias_severity="standard")
    train_report = MagicMock(applied=True, n_samples=15, r_squared=0.42)
    new_epoch = MagicMock(epoch_id=99, bias_severity="strict")
    with (
        patch("backend.db.evaluator_config.get_active_epoch", AsyncMock(return_value=epoch)),
        patch(
            "backend.db.evaluator_config.count_labeled_since",
            AsyncMock(return_value=MIN_EVOLVE_SAMPLES + 5),
        ),
        patch(
            "backend.db.evaluator_config.train_weights", AsyncMock(return_value=train_report)
        ) as tw,
        patch("backend.db.evaluator_config.avg_bias_score", AsyncMock(return_value=80.0)),
        patch("backend.db.evaluator_config.create_epoch", AsyncMock(return_value=new_epoch)) as ce,
    ):
        report = await maybe_evolve("acct1")
    assert report["action"] == "evolved"
    tw.assert_awaited_once_with("acct1", apply=True)
    ce.assert_awaited_once()  # severity advanced standard→strict (80>=LENIENT_BAND)
    assert report["epoch"] == {"from": "standard", "to": "strict", "created": 99}


@pytest.mark.asyncio
async def test_maybe_evolve_holds_epoch_when_signal_in_band():
    """Enough samples but bias in standard band → refit weights only, no new epoch."""
    from backend.db.evaluator_config import MIN_EVOLVE_SAMPLES, maybe_evolve

    epoch = MagicMock(created_at="t0", bias_severity="standard")
    train_report = MagicMock(applied=True, n_samples=15, r_squared=0.5)
    with (
        patch("backend.db.evaluator_config.get_active_epoch", AsyncMock(return_value=epoch)),
        patch(
            "backend.db.evaluator_config.count_labeled_since",
            AsyncMock(return_value=MIN_EVOLVE_SAMPLES + 5),
        ),
        patch("backend.db.evaluator_config.train_weights", AsyncMock(return_value=train_report)),
        patch("backend.db.evaluator_config.avg_bias_score", AsyncMock(return_value=60.0)),
        patch("backend.db.evaluator_config.create_epoch", AsyncMock()) as ce,
    ):
        report = await maybe_evolve("acct1")
    assert report["action"] == "evolved"
    ce.assert_not_awaited()  # 60 is in standard band → no epoch advance


@pytest.mark.asyncio
async def test_maybe_evolve_reentry_guard_skips_concurrent():
    """A second maybe_evolve for the same account while one is running is skipped."""
    from backend.db.evaluator_config import _EVOLVING, maybe_evolve

    _EVOLVING.add("acct1")
    try:
        with (
            patch("backend.db.evaluator_config.get_active_epoch", AsyncMock()) as ga,
            patch("backend.db.evaluator_config.train_weights", AsyncMock()) as tw,
        ):
            report = await maybe_evolve("acct1")
        assert report["action"] == "skip"
        assert report["reason"] == "already-evolving"
        ga.assert_not_awaited()
        tw.assert_not_awaited()
    finally:
        _EVOLVING.discard("acct1")


@pytest.mark.asyncio
async def test_maybe_evolve_degrades_on_failure():
    """Any inner exception → action=error, guard released, no raise."""
    from backend.db.evaluator_config import maybe_evolve

    with (
        patch(
            "backend.db.evaluator_config.get_active_epoch",
            AsyncMock(side_effect=RuntimeError("db down")),
        ),
        patch("backend.db.evaluator_config.train_weights", AsyncMock()) as tw,
    ):
        report = await maybe_evolve("acct1")
    assert report["action"] == "error"
    assert "db down" in report["reason"]
    tw.assert_not_awaited()
    # guard must be released so a later run can proceed
    from backend.db.evaluator_config import _EVOLVING

    assert "acct1" not in _EVOLVING


# ── Online co-evolution: event emission ──


@pytest.mark.asyncio
async def test_maybe_evolve_emits_event_on_evolve():
    """A successful evolve emits EVALUATOR_EPOCH_EVOLVED with epoch/weight info."""
    from backend.db.evaluator_config import MIN_EVOLVE_SAMPLES, maybe_evolve

    epoch = MagicMock(created_at="t0", bias_severity="standard")
    train_report = MagicMock(applied=True, n_samples=15, r_squared=0.42)
    new_epoch = MagicMock(epoch_id=99, bias_severity="strict")
    with (
        patch("backend.db.evaluator_config.get_active_epoch", AsyncMock(return_value=epoch)),
        patch(
            "backend.db.evaluator_config.count_labeled_since",
            AsyncMock(return_value=MIN_EVOLVE_SAMPLES + 5),
        ),
        patch("backend.db.evaluator_config.train_weights", AsyncMock(return_value=train_report)),
        patch("backend.db.evaluator_config.avg_bias_score", AsyncMock(return_value=80.0)),
        patch("backend.db.evaluator_config.create_epoch", AsyncMock(return_value=new_epoch)),
        patch("backend.realtime.EventBusService") as bus_cls,
    ):
        await maybe_evolve("acct1")
    bus_cls.get_instance.return_value.emit.assert_called_once()
    args, kwargs = bus_cls.get_instance.return_value.emit.call_args
    assert args[0].value == "evaluator.epoch_evolved"
    payload = args[2] if len(args) > 2 else kwargs["payload"]
    assert payload["action"] == "evolved"
    assert payload["epoch"] == {"from": "standard", "to": "strict", "created": 99}
    assert payload["weight_training"]["r_squared"] == 0.42
    assert payload["account_id"] == "acct1"


@pytest.mark.asyncio
async def test_maybe_evolve_no_emit_on_skip_below_threshold():
    """Below-threshold skip does NOT emit (avoid noise)."""
    from backend.db.evaluator_config import MIN_EVOLVE_SAMPLES, maybe_evolve

    with (
        patch(
            "backend.db.evaluator_config.get_active_epoch",
            AsyncMock(return_value=MagicMock(created_at="t0", bias_severity="standard")),
        ),
        patch(
            "backend.db.evaluator_config.count_labeled_since",
            AsyncMock(return_value=MIN_EVOLVE_SAMPLES - 1),
        ),
        patch("backend.realtime.EventBusService") as bus_cls,
    ):
        await maybe_evolve("acct1")
    bus_cls.get_instance.return_value.emit.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_evolve_no_emit_on_reentry_skip():
    """Already-evolving skip does NOT emit."""
    from backend.db.evaluator_config import _EVOLVING, maybe_evolve

    _EVOLVING.add("acct1")
    try:
        with patch("backend.realtime.EventBusService") as bus_cls:
            await maybe_evolve("acct1")
        bus_cls.get_instance.return_value.emit.assert_not_called()
    finally:
        _EVOLVING.discard("acct1")


@pytest.mark.asyncio
async def test_maybe_evolve_no_emit_on_error():
    """Failure path does NOT emit (only logs)."""
    from backend.db.evaluator_config import maybe_evolve

    with (
        patch(
            "backend.db.evaluator_config.get_active_epoch",
            AsyncMock(side_effect=RuntimeError("db down")),
        ),
        patch("backend.realtime.EventBusService") as bus_cls,
    ):
        await maybe_evolve("acct1")
    bus_cls.get_instance.return_value.emit.assert_not_called()
