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
    from backend.db.evaluator_config import EvaluatorWeights, _apply_override

    w = EvaluatorWeights()
    _apply_override(w, "weight.bogus", 1.0)
    _apply_override(w, "unknown.thing", 1.0)
    assert w.dimension_weights["copywriting"] == 0.25  # unchanged
