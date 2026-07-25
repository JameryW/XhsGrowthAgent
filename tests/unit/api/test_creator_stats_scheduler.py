from __future__ import annotations

import asyncio
import importlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.app import _CN_TZ, _clip_to_active_window, _creator_stats_scheduler, app, health

app_module = importlib.import_module("backend.api.app")


def _scheduler_app() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(graph=SimpleNamespace(store=None)),
    )


@pytest.mark.asyncio
async def test_scheduler_runs_immediately_and_records_batch_summary(monkeypatch):
    app = _scheduler_app()
    result = {
        "ok": True,
        "status": "completed",
        "active_accounts": 2,
        "succeeded": 2,
        "failed": 0,
    }
    sleep_calls: list[float] = []

    async def stop_after_first_run(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_first_run)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 0.5)

    sync.assert_awaited_once_with(store=None, period="30d")
    # Scheduler sleep carries a 0.75-1.5x random factor around the interval.
    assert len(sleep_calls) == 1
    assert 1800.0 * 0.75 * 0.99 <= sleep_calls[0] <= 1800.0 * 1.5
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "completed"
    assert state["run_count"] == 1
    assert state["last_status"] == "completed"
    assert state["last_succeeded"] == 2
    assert state["last_failed"] == 0
    assert state["last_finished_at"]
    assert state["next_run_at"]


@pytest.mark.asyncio
async def test_scheduler_records_unexpected_failure_before_retry(monkeypatch):
    app = _scheduler_app()

    async def stop_after_failure(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_failure)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(side_effect=RuntimeError("database unavailable")),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 1)

    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "failed"
    assert state["last_error"] == "database unavailable"
    assert state["last_finished_at"]
    assert state["next_run_at"]


@pytest.mark.asyncio
async def test_scheduler_surfaces_per_account_errors_in_last_error(monkeypatch):
    app = _scheduler_app()
    result = {
        "ok": False,
        "status": "completed",
        "active_accounts": 1,
        "succeeded": 0,
        "failed": 1,
        "results": [
            {
                "account_id": "acc-1",
                "account_synced": False,
                "error": "creator center login page is showing; re-login",
            }
        ],
    }

    async def stop_after_first_run(seconds: float) -> None:
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_first_run)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 1)

    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "failed"
    assert state["last_failed"] == 1
    assert "acc-1" in (state["last_error"] or "")
    assert "login page" in (state["last_error"] or "")


@pytest.mark.asyncio
async def test_health_exposes_scheduler_summary_without_raw_results(monkeypatch):
    monkeypatch.setattr(
        "backend.db.pool.is_pool_ready",
        lambda: True,
    )
    monkeypatch.setattr(
        app.state,
        "creator_stats_scheduler_status",
        {
            "enabled": True,
            "status": "completed",
            "last_status": "completed",
            "last_succeeded": 1,
            "last_failed": 0,
            "last_result": {"should_not": "be exposed"},
        },
        raising=False,
    )

    response = await health()

    assert response.success is True
    assert response.data["db"] == "connected"
    scheduler = response.data["creator_stats_scheduler"]
    assert scheduler["status"] == "completed"
    assert scheduler["last_succeeded"] == 1
    assert "last_result" not in scheduler


# ── 反风控调度：活跃窗口 / 启动延迟 / 失败退避 ──


def test_clip_to_active_window_keeps_candidate_inside_window():
    """窗口内的候选时刻原样保留。2026-01-15 02:00 UTC = 10:00 CST，在 8-23 内。"""
    candidate = datetime(2026, 1, 15, 2, 0, tzinfo=UTC)
    assert _clip_to_active_window(candidate, 8, 23) == candidate


def test_clip_to_active_window_moves_early_morning_into_same_day_window():
    """窗口前（凌晨）的候选 → 当天窗口内的随机点。20:00 UTC = 次日 04:00 CST。"""
    candidate = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)  # 2026-01-16 04:00 CST
    clipped = _clip_to_active_window(candidate, 8, 23)
    local = clipped.astimezone(_CN_TZ)
    assert local.date() == datetime(2026, 1, 16, tzinfo=UTC).astimezone(_CN_TZ).date()
    assert 8 <= local.hour < 23


def test_clip_to_active_window_moves_late_night_into_next_day_window():
    """窗口后（深夜）的候选 → 第二天窗口内的随机点。15:30 UTC = 23:30 CST。"""
    candidate = datetime(2026, 1, 15, 15, 30, tzinfo=UTC)  # 2026-01-15 23:30 CST
    clipped = _clip_to_active_window(candidate, 8, 23)
    local = clipped.astimezone(_CN_TZ)
    assert local.date() == datetime(2026, 1, 16, tzinfo=UTC).astimezone(_CN_TZ).date()
    assert 8 <= local.hour < 23


def test_clip_to_active_window_biases_toward_evening_hours():
    """窗口内落点按人类活跃度加权：晚间（20-22 点）应显著多于清晨（8 点）。

    均匀分布下晚间 3 小时约占 3/15=20%、8 点占 1/15≈6.7%；加权后晚间权重
    11.5 vs 8 点 1.0。3000 次采样下 8 点次数 > 晚间次数的概率可以忽略。
    """
    candidate = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)  # 凌晨 4 点 CST，窗口外
    evening = 0
    early = 0
    samples = 3000
    for _ in range(samples):
        local = _clip_to_active_window(candidate, 8, 23).astimezone(_CN_TZ)
        assert 8 <= local.hour < 23
        if local.hour in (20, 21, 22):
            evening += 1
        elif local.hour == 8:
            early += 1
    assert evening > early * 3


def test_clip_to_active_window_supports_hours_without_explicit_weights():
    """窗口包含权重表之外的小时（如 7 点）时按默认权重 1.0 处理，不报错。"""
    candidate = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)
    clipped = _clip_to_active_window(candidate, 7, 10)
    local = clipped.astimezone(_CN_TZ)
    assert 7 <= local.hour < 10


@pytest.mark.asyncio
async def test_scheduler_delays_first_run_when_startup_delay_configured(monkeypatch):
    """配置启动延迟后，首次运行前先睡一段随机延迟，不再启动即爬。"""
    app = _scheduler_app()
    result = {"ok": True, "status": "completed", "active_accounts": 1, "succeeded": 1, "failed": 0}
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 0.5, startup_delay=(5.0, 10.0))

    sync.assert_awaited_once()
    # 第一次 sleep 是启动延迟（5-10s 区间内，减去微小耗时）。
    assert 4.0 <= sleep_calls[0] <= 10.0
    # 第二次 sleep 是周期睡眠（1800s × 0.75-1.5 随机因子）。
    assert 1800.0 * 0.75 * 0.99 <= sleep_calls[1] <= 1800.0 * 1.5


@pytest.mark.asyncio
async def test_scheduler_backs_off_after_consecutive_failures(monkeypatch):
    """连续失败第二次起，下次运行间隔按 1.5-2.5× 随机放大（24h → 36-60h 节奏）。"""
    app = _scheduler_app()
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(side_effect=RuntimeError("risk control 461")),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 0.5)

    # 第一次失败：按原周期（1800s × 0.75-1.5）。
    assert 1800.0 * 0.75 * 0.99 <= sleep_calls[0] <= 1800.0 * 1.5
    # 第二次连续失败：间隔按 1.5-2.5× 随机放大（1800s × 1.5-2.5 × 0.75-1.5）。
    assert 1800.0 * 1.5 * 0.75 * 0.99 <= sleep_calls[1] <= 1800.0 * 2.5 * 1.5
    state = app.state.creator_stats_scheduler_status
    assert state["consecutive_failures"] == 2
    assert state["status"] == "failed"


@pytest.mark.asyncio
async def test_scheduler_treats_cooldown_as_non_failure(monkeypatch):
    """冷却跳过（status=cooldown）不算失败：不计入退避、间隔不翻倍。"""
    app = _scheduler_app()
    result = {
        "ok": False,
        "status": "cooldown",
        "active_accounts": 0,
        "succeeded": 0,
        "failed": 0,
    }
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 0.5)

    state = app.state.creator_stats_scheduler_status
    assert state["consecutive_failures"] == 0
    assert state["status"] == "completed"
    assert 1800.0 * 0.75 * 0.99 <= sleep_calls[0] <= 1800.0 * 1.5


@pytest.mark.asyncio
async def test_scheduler_randomly_skips_cycles_when_configured(monkeypatch):
    """skip_day_chance=1.0 时，每轮运行后下一轮整天跳过（不爬但仍按节奏睡眠）。"""
    app = _scheduler_app()
    result = {"ok": True, "status": "completed", "active_accounts": 1, "succeeded": 1, "failed": 0}
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, 0.5, skip_day_chance=1.0)

    # 第一轮正常运行，第二轮被跳过——sync 只调用一次。
    sync.assert_awaited_once()
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "skipped"
    assert state["run_count"] == 1
    assert len(sleep_calls) == 2
