from __future__ import annotations

import asyncio
import importlib
import math
import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from backend.api.app import (
    _CN_TZ,
    _clip_to_active_window,
    _creator_stats_scheduler,
    _effective_skip_day_chance,
    _finite_float,
    _is_riskish_error,
    _pick_scheduled_period,
    _prefer_light_for_pressure,
    _pressure_period_7d_chance,
    _pressure_skip_day_chance,
    _prune_success_timestamps,
    _quiet_cycles_to_arm,
    _risk_pressure_level,
    _weekday_skip_factor,
    _weekly_crawl_budget_exhausted,
    app,
    health,
)
from backend.db.creator_stats import _reset_memory_store

app_module = importlib.import_module("backend.api.app")


def _empty_scheduler_history() -> dict:
    return {
        "timestamps": [],
        "last_success_local_hour": None,
        "last_period": None,
        "risk_failures": [],
        "pause_until": None,
        "quiet_cycles_remaining": 0,
        "soft_risk_signals": [],
    }


@pytest.fixture(autouse=True)
def _isolate_durable_scheduler_state(monkeypatch):
    """Prevent real Postgres / leftover memory state from bleeding across tests."""
    _reset_memory_store()

    async def _empty_load():
        return _empty_scheduler_history()

    async def _noop_save(*_a, **_k):
        return None

    monkeypatch.setattr("backend.db.creator_stats.load_scheduler_success_history", _empty_load)
    monkeypatch.setattr("backend.db.creator_stats.save_scheduler_success_history", _noop_save)
    # Freshness/auth probes often import accounts — default to no active account
    # so scheduler tests don't hit live DB unless they opt in.
    monkeypatch.setattr(
        "backend.db.accounts.get_active_account",
        AsyncMock(return_value=None),
    )
    yield
    _reset_memory_store()


def _scheduler_app() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(graph=SimpleNamespace(store=None)),
    )


def test_finite_float_rejects_nonfinite_and_malformed_values():
    assert _finite_float("3.5", 1.0) == 3.5
    assert _finite_float("nan", 1.0) == 1.0
    assert _finite_float("inf", 1.0) == 1.0
    assert _finite_float("not-a-number", 1.0) == 1.0


@pytest.mark.asyncio
async def test_scheduler_nonfinite_interval_falls_back_to_safe_minimum(monkeypatch):
    app = _scheduler_app()
    result = {"ok": True, "status": "completed", "active_accounts": 0, "succeeded": 0, "failed": 0}
    sleep_calls: list[float] = []

    async def stop_after_first_run(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_first_run)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(app, float("inf"))

    assert len(sleep_calls) == 1
    assert all(math.isfinite(value) for value in sleep_calls)
    # Non-finite interval falls back to 60s floor; jitter 0.65–1.75× (+ optional long break).
    assert 60.0 * 0.65 * 0.99 <= sleep_calls[0] <= 60.0 * 1.75 * 2.8 * 1.01


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

    # Period is randomly 7d or 30d; always prefer_light=None for scheduled path.
    sync.assert_awaited_once()
    assert sync.await_args.kwargs["store"] is None
    assert sync.await_args.kwargs["prefer_light"] is None
    assert sync.await_args.kwargs.get("risk_pressure") == 0
    assert sync.await_args.kwargs["period"] in {"7d", "30d"}
    # Scheduler sleep carries a 0.65-1.75x random factor around the interval
    # (and may include pre_run settle when enabled — disabled by default in tests).
    assert len(sleep_calls) == 1
    assert 1800.0 * 0.65 * 0.99 <= sleep_calls[0] <= 1800.0 * 1.75 * 2.8 * 1.01
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "completed"
    assert state["run_count"] == 1
    assert state["last_status"] == "completed"
    assert state["last_succeeded"] == 2
    assert state["last_failed"] == 0
    assert state["last_finished_at"]
    assert state["next_run_at"]
    assert state["last_period"] in {"7d", "30d"}


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


def test_clip_to_active_window_avoids_recent_success_hour():
    """最近一次成功爬取的本地小时应被显著降权。"""
    # Window-outside candidate so we always re-sample.
    candidate = datetime(2026, 1, 15, 20, 0, tzinfo=UTC)  # 04:00 CST
    hits = 0
    samples = 800
    for _ in range(samples):
        local = _clip_to_active_window(candidate, 9, 22, avoid_hours={21}).astimezone(_CN_TZ)
        if local.hour == 21:
            hits += 1
    # Without avoidance, hour 21 weight 4.0 / sum≈30 ≈ 13%; with *0.12 residual
    # it should be rare. Allow a small number of residual hits.
    assert hits < samples * 0.05


def test_weekly_crawl_budget_counts_rolling_seven_days():
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    stamps = [
        "2026-07-25T10:00:00+00:00",
        "2026-07-27T10:00:00+00:00",
        "2026-07-29T10:00:00+00:00",
        "2026-07-20T10:00:00+00:00",  # outside 7d window
    ]
    kept = _prune_success_timestamps(stamps, now=now, days=7)
    assert len(kept) == 3
    assert _weekly_crawl_budget_exhausted(stamps, max_per_week=3, now=now) is True
    assert _weekly_crawl_budget_exhausted(stamps, max_per_week=4, now=now) is False
    assert _weekly_crawl_budget_exhausted(stamps, max_per_week=0, now=now) is False


def test_effective_skip_day_chance_escalates_with_weekly_successes():
    base = 0.25
    assert _effective_skip_day_chance(base, 0) == base
    assert _effective_skip_day_chance(base, 1) > base
    assert _effective_skip_day_chance(base, 2) > _effective_skip_day_chance(base, 1)
    assert _effective_skip_day_chance(base, 2) <= 0.90


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
    # 第二次 sleep 是周期睡眠（1800s × 0.65-1.75 随机因子，成功后或有长休）。
    assert 1800.0 * 0.65 * 0.99 <= sleep_calls[1] <= 1800.0 * 1.75 * 2.8 * 1.01


@pytest.mark.asyncio
async def test_scheduler_backs_off_after_consecutive_failures(monkeypatch):
    """Risk/auth failures use a stronger 3–6× interval multiplier and arm a quiet window."""
    app = _scheduler_app()
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    # Force risk skip arm so the second cycle is a quiet window, not a re-crawl.
    monkeypatch.setattr(app_module.random, "random", lambda: 0.0)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(side_effect=RuntimeError("risk control 461")),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            0.5,
            risk_skip_next_chance=1.0,
            skip_day_chance=0.0,
            post_success_long_break_chance=0.0,
        )

    # Only one crawl attempt — the next cycle is the armed risk skip.
    sync.assert_awaited_once()
    # Risk-shaped errors: interval × triangular(0.65,1.75) × uniform(3,6).
    lo = 1800.0 * 0.65 * 3.0 * 0.99
    hi = 1800.0 * 1.75 * 6.0
    assert lo <= sleep_calls[0] <= hi
    state = app.state.creator_stats_scheduler_status
    assert state["consecutive_failures"] == 1
    assert state["status"] == "skipped"
    assert state.get("last_risk_skip_armed") is True


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
    assert 1800.0 * 0.65 * 0.99 <= sleep_calls[0] <= 1800.0 * 1.75 * 2.8 * 1.01


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
    # 固定星期权重为 1.0，隔离星期加权对本用例的干扰。
    monkeypatch.setattr(app_module, "_weekday_skip_factor", lambda _weekday: 1.0)
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


def test_weekday_skip_factor_weekends_lower_than_monday():
    """周末（5=周六、6=周日）的跳过权重低于周一（0），工作日居中。"""
    assert _weekday_skip_factor(5) < _weekday_skip_factor(0)
    assert _weekday_skip_factor(6) < _weekday_skip_factor(0)
    assert _weekday_skip_factor(0) > _weekday_skip_factor(2)
    assert _weekday_skip_factor(-1) == 1.0
    assert _weekday_skip_factor(7) == 1.0


def test_interval_jitter_stays_within_triangular_bounds():
    """三角分布的间隔抖动在 0.65-1.75× 区间内（峰值 1×）。"""
    samples = [random.triangular(0.65, 1.75, 1.0) for _ in range(2000)]
    assert all(0.65 <= s <= 1.75 for s in samples)
    # 峰值在 1×：样本均值应靠近 mode，明显低于区间中点 1.2。
    mean = sum(samples) / len(samples)
    assert 1.0 <= mean <= 1.2


def test_pick_scheduled_period_respects_chance_extremes():
    assert _pick_scheduled_period(0.0) == "30d"
    assert _pick_scheduled_period(1.0) == "7d"
    # Mid chance yields both over enough trials.
    seen = {_pick_scheduled_period(0.5) for _ in range(80)}
    assert seen == {"7d", "30d"}


def test_pick_scheduled_period_avoids_back_to_back_same_window():
    # After a 7d run, next picks should strongly prefer 30d.
    picks = [_pick_scheduled_period(0.5, last_period="7d") for _ in range(80)]
    assert picks.count("30d") > picks.count("7d")
    # After a 30d run, 7d share should rise vs always-30d baseline.
    picks2 = [_pick_scheduled_period(0.35, last_period="30d") for _ in range(120)]
    assert "7d" in picks2


def test_circuit_pause_and_risk_failure_trip():
    from backend.api.app import _circuit_pause_active, _record_risk_failure

    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    failures, pause = _record_risk_failure([], now=now, trip_count=2)
    assert len(failures) == 1
    assert pause is None
    failures2, pause2 = _record_risk_failure(failures, now=now, trip_count=2)
    assert len(failures2) == 2
    assert pause2 is not None
    assert _circuit_pause_active(pause2, now=now) is True
    assert _circuit_pause_active(pause2, now=now + timedelta(days=10)) is False


def test_is_riskish_error_detects_auth_and_risk_tokens():
    assert _is_riskish_error("401 unauthorized re-login")
    assert _is_riskish_error("触发风控 300012")
    assert _is_riskish_error("CDP connect failed: socket hang up")
    assert not _is_riskish_error("database unavailable")
    assert not _is_riskish_error(None)


def test_risk_pressure_level_escalates_with_failures_and_budget():
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    assert _risk_pressure_level([], successes_last_7d=0, now=now) == 0
    assert _risk_pressure_level([], successes_last_7d=2, now=now) == 1
    assert (
        _risk_pressure_level(
            [(now - timedelta(hours=1)).isoformat()],
            successes_last_7d=0,
            now=now,
        )
        == 1
    )
    assert (
        _risk_pressure_level(
            [
                (now - timedelta(hours=2)).isoformat(),
                (now - timedelta(hours=1)).isoformat(),
            ],
            successes_last_7d=0,
            now=now,
        )
        == 2
    )
    assert (
        _risk_pressure_level(
            [],
            successes_last_7d=0,
            pause_until=(now + timedelta(days=2)).isoformat(),
            now=now,
        )
        == 2
    )
    soft = [(now - timedelta(hours=1)).isoformat()]
    assert _risk_pressure_level([], soft_risk_signals=soft, now=now) == 1
    soft3 = [(now - timedelta(hours=i)).isoformat() for i in (3, 2, 1)]
    assert _risk_pressure_level([], soft_risk_signals=soft3, now=now) == 2


def test_pressure_helpers_tighten_period_skip_and_light():
    assert _prefer_light_for_pressure(0) is None
    assert _prefer_light_for_pressure(1) is True
    assert _pressure_period_7d_chance(0.35, 0) == 0.35
    assert _pressure_period_7d_chance(0.35, 1) > 0.35
    assert _pressure_period_7d_chance(0.35, 2) >= 0.80
    assert _pressure_skip_day_chance(0.25, 1) > 0.25
    assert _pressure_skip_day_chance(0.25, 2) > _pressure_skip_day_chance(0.25, 1)


def test_quiet_cycles_to_arm_respects_chance(monkeypatch):
    monkeypatch.setattr(app_module.random, "random", lambda: 0.99)
    assert _quiet_cycles_to_arm(0, risk_skip_next_chance=0.5) == 0
    monkeypatch.setattr(app_module.random, "random", lambda: 0.0)
    # Always hit the base arm; pressure path may roll a second cycle.
    assert _quiet_cycles_to_arm(0, risk_skip_next_chance=1.0) == 1


@pytest.mark.asyncio
async def test_scheduler_settles_before_crawl_when_pre_run_delay_set(monkeypatch):
    """Wake → settle → crawl, not crawl immediately on timer fire."""
    app = _scheduler_app()
    result = {"ok": True, "status": "completed", "active_accounts": 1, "succeeded": 1, "failed": 0}
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # First sleep is pre-run settle; second is post-run interval → stop.
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(app_module.random, "uniform", lambda a, b: (a + b) / 2)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            0.5,
            pre_run_delay=(60.0, 120.0),
            post_success_long_break_chance=0.0,
            risk_skip_next_chance=0.0,
            skip_day_chance=0.0,
            period_7d_chance=0.0,
        )

    sync.assert_awaited_once_with(store=None, period="30d", prefer_light=None, risk_pressure=0)
    # Pre-run settle mid of [60,120] = 90 (pressure=0 — no stretch).
    assert sleep_calls[0] == 90.0
    assert app.state.creator_stats_scheduler_status["last_period"] == "30d"
    assert app.state.creator_stats_scheduler_status.get("risk_pressure") == 0


@pytest.mark.asyncio
async def test_scheduler_arms_skip_after_riskish_failure(monkeypatch):
    """Auth/risk failures should often force an extra quiet window."""
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
                "error": "re-login required / 风控",
            }
        ],
    }
    sleep_calls: list[float] = []
    phases: list[str] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        state = app.state.creator_stats_scheduler_status
        phases.append(str(state.get("status")))
        if len(sleep_calls) >= 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        app_module.random, "random", lambda: 0.0
    )  # always arm skip / no long-break chance roll fail
    monkeypatch.setattr(app_module.random, "uniform", lambda a, b: a)
    monkeypatch.setattr(app_module.random, "triangular", lambda a, b, c: 1.0)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            1.0,
            pre_run_delay=None,
            post_success_long_break_chance=0.0,
            risk_skip_next_chance=1.0,
            skip_day_chance=0.0,
            period_7d_chance=0.0,
        )

    # First cycle crawl failed; second cycle should be skipped without another sync.
    sync.assert_awaited_once()
    assert app.state.creator_stats_scheduler_status["status"] == "skipped"
    assert app.state.creator_stats_scheduler_status.get("last_risk_skip_armed") is True


@pytest.mark.asyncio
async def test_scheduler_skips_when_weekly_budget_exhausted(monkeypatch):
    app = _scheduler_app()
    app.state.creator_stats_scheduler_status = {
        "success_timestamps": [
            "2026-07-29T10:00:00+00:00",
            "2026-07-30T10:00:00+00:00",
            "2026-07-31T01:00:00+00:00",
        ]
    }
    sleep_calls: list[float] = []

    async def stop_after_interval(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_interval)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            1.0,
            pre_run_delay=None,
            skip_day_chance=0.0,
            risk_skip_next_chance=0.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=3,
        )

    sync.assert_not_awaited()
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "skipped"
    assert state["last_skip_reason"] == "weekly_budget"


@pytest.mark.asyncio
async def test_scheduler_skips_when_auth_cooldown_active(monkeypatch):
    app = _scheduler_app()
    sleep_calls: list[float] = []

    async def stop_after_interval(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_interval)
    block = SimpleNamespace(
        message="auth cooldown active",
        retry_after_seconds=900,
        risk_code="sync_auth_cooldown",
    )
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(),
        ) as sync,
        patch(
            "backend.db.accounts.get_active_account",
            new=AsyncMock(return_value=SimpleNamespace(id="acc-1")),
        ),
        patch(
            "backend.services.creator_stats.pipeline._account_freshness_skip",
            new=AsyncMock(return_value=(False, 0)),
        ),
        patch(
            "backend.services.xhs_risk_gate.check_sync_auth_cooldown",
            return_value=block,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            1.0,
            pre_run_delay=(30.0, 60.0),
            skip_day_chance=0.0,
            risk_skip_next_chance=0.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=0,
        )

    sync.assert_not_awaited()
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "skipped"
    assert state["last_skip_reason"] == "auth_cooldown"


@pytest.mark.asyncio
async def test_scheduler_success_history_persists_to_db_helper(monkeypatch):
    """Live success should call durable save so weekly budget survives restarts."""
    app = _scheduler_app()
    result = {
        "ok": True,
        "status": "completed",
        "active_accounts": 1,
        "succeeded": 1,
        "failed": 0,
        "results": [
            {
                "account_id": "acc-1",
                "account_synced": True,
                "notes_imported": 1,
            }
        ],
    }
    saved: list[tuple] = []

    async def fake_sleep(seconds: float) -> None:
        raise asyncio.CancelledError

    async def fake_save(timestamps, **kwargs):
        saved.append((list(timestamps), kwargs))

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr("backend.db.creator_stats.save_scheduler_success_history", fake_save)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ),
        patch(
            "backend.services.creator_stats.pipeline._has_successful_live_sync",
            return_value=True,
        ),
        patch(
            "backend.services.creator_stats.pipeline._account_freshness_skip",
            new=AsyncMock(return_value=(False, 0)),
        ),
        patch(
            "backend.db.accounts.get_active_account",
            new=AsyncMock(return_value=SimpleNamespace(id="acc-1")),
        ),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new=AsyncMock(return_value="http://127.0.0.1:9222"),
        ),
        patch(
            "backend.services.chrome_launcher.probe_port",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.services.chrome_launcher.count_open_pages",
            return_value=2,
        ),
        patch(
            "backend.services.xhs_risk_gate.check_sync_auth_cooldown",
            return_value=None,
        ),
        patch(
            "backend.services.chrome_launcher.hygiene_browser_pages_all",
            new=AsyncMock(return_value=[]),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            0.5,
            pre_run_delay=None,
            skip_day_chance=0.0,
            risk_skip_next_chance=0.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=0,
            period_7d_chance=0.0,
        )

    assert saved, "expected durable success history write"
    assert len(saved[0][0]) >= 1
    assert app.state.creator_stats_scheduler_status["successes_last_7d"] >= 1


@pytest.mark.asyncio
async def test_scheduler_skips_when_cdp_unavailable(monkeypatch):
    """CDP-down is infrastructure — skip without opening the risk circuit."""
    app = _scheduler_app()
    sleep_calls: list[float] = []

    async def stop_after_interval(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_interval)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(),
        ) as sync,
        patch(
            "backend.db.accounts.get_active_account",
            new=AsyncMock(return_value=SimpleNamespace(id="acc-1")),
        ),
        patch(
            "backend.services.creator_stats.pipeline._account_freshness_skip",
            new=AsyncMock(return_value=(False, 0)),
        ),
        patch(
            "backend.services.xhs_risk_gate.check_sync_auth_cooldown",
            return_value=None,
        ),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new=AsyncMock(return_value="http://127.0.0.1:9222"),
        ),
        patch(
            "backend.services.chrome_launcher.probe_port",
            new=AsyncMock(return_value=False),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            1.0,
            pre_run_delay=(30.0, 60.0),
            skip_day_chance=0.0,
            risk_skip_next_chance=0.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=0,
        )

    sync.assert_not_awaited()
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "skipped"
    assert state["last_skip_reason"] == "cdp_unavailable"
    assert not state.get("risk_failures")
    # No pre-run settle — only the post-cycle interval sleep.
    assert len(sleep_calls) == 1


@pytest.mark.asyncio
async def test_scheduler_forces_light_under_pressure(monkeypatch):
    """Recent risk failure → pressure≥1 → prefer_light=True list-only crawl."""
    app = _scheduler_app()
    now = datetime.now(UTC)
    app.state.creator_stats_scheduler_status = {
        "risk_failures": [(now - timedelta(hours=2)).isoformat()],
    }
    result = {
        "ok": True,
        "status": "completed",
        "active_accounts": 1,
        "succeeded": 1,
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
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            0.5,
            pre_run_delay=None,
            skip_day_chance=0.0,
            risk_skip_next_chance=0.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=0,
            period_7d_chance=0.0,
        )

    sync.assert_awaited_once()
    assert sync.await_args.kwargs.get("prefer_light") is True
    assert sync.await_args.kwargs.get("risk_pressure") == 1
    assert app.state.creator_stats_scheduler_status.get("risk_pressure") == 1


@pytest.mark.asyncio
async def test_scheduler_skips_when_snapshot_still_fresh(monkeypatch):
    app = _scheduler_app()
    sleep_calls: list[float] = []

    async def stop_after_interval(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_interval)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(),
        ) as sync,
        patch(
            "backend.db.accounts.get_active_account",
            new=AsyncMock(return_value=SimpleNamespace(id="acc-1")),
        ),
        patch(
            "backend.services.creator_stats.pipeline._account_freshness_skip",
            new=AsyncMock(return_value=(True, 3600)),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            1.0,
            pre_run_delay=(30.0, 60.0),  # must not settle if freshness short-circuits
            skip_day_chance=0.0,
            risk_skip_next_chance=0.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=0,
        )

    sync.assert_not_awaited()
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "skipped"
    assert state["last_skip_reason"] == "fresh_snapshot"
    # Only the post-cycle interval sleep — no pre-run settle sleep.
    assert len(sleep_calls) == 1


@pytest.mark.asyncio
async def test_scheduler_soft_risk_empty_shell_cools_without_live_success(monkeypatch):
    """Empty-shell soft risk must not clear the fuse as a healthy success."""
    app = _scheduler_app()
    result = {
        "ok": True,
        "status": "completed",
        "active_accounts": 1,
        "succeeded": 1,
        "failed": 0,
        "results": [
            {
                "account_id": "acc-1",
                "account_synced": True,
                "notes_imported": 0,
                "soft_risk": True,
                "soft_risk_reason": "empty shell risk: note list collapsed",
                "error": "empty shell risk: note list collapsed",
                "error_code": "EMPTY_SHELL",
            }
        ],
    }
    saved: list[dict] = []

    async def fake_sleep(seconds: float) -> None:
        raise asyncio.CancelledError

    async def fake_save(timestamps, **kwargs):
        saved.append({"timestamps": list(timestamps), **kwargs})

    monkeypatch.setattr(app_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(app_module.random, "random", lambda: 0.0)
    monkeypatch.setattr("backend.db.creator_stats.save_scheduler_success_history", fake_save)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(return_value=result),
        ),
        patch(
            "backend.services.creator_stats.pipeline._has_successful_live_sync",
            return_value=False,
        ),
        patch(
            "backend.services.creator_stats.pipeline._batch_has_soft_risk",
            return_value=True,
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            0.5,
            pre_run_delay=None,
            skip_day_chance=0.0,
            risk_skip_next_chance=1.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=0,
            period_7d_chance=0.0,
        )

    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "soft_risk"
    assert state.get("last_soft_risk") is True
    assert state.get("last_risk_skip_armed") is True
    assert int(state.get("quiet_cycles_remaining") or 0) >= 1
    assert state.get("soft_risk_signals")
    # Soft risk should not append a healthy success timestamp.
    assert state.get("successes_last_7d", 0) == 0
    assert saved, "expected durable quiet/soft-risk write"


@pytest.mark.asyncio
async def test_scheduler_skips_when_page_budget_exceeded(monkeypatch):
    """Too many open tabs after hygiene → skip without crawl or risk trip."""
    app = _scheduler_app()
    sleep_calls: list[float] = []

    async def stop_after_interval(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_interval)
    monkeypatch.setenv("CREATOR_STATS_MAX_OPEN_PAGES", "3")
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(),
        ) as sync,
        patch(
            "backend.db.accounts.get_active_account",
            new=AsyncMock(
                return_value=SimpleNamespace(
                    id="acc-1", cdp_port=9222, chrome_profile_path="/tmp/p"
                )
            ),
        ),
        patch(
            "backend.services.creator_stats.pipeline._account_freshness_skip",
            new=AsyncMock(return_value=(False, 0)),
        ),
        patch(
            "backend.services.xhs_risk_gate.check_sync_auth_cooldown",
            return_value=None,
        ),
        patch(
            "backend.db.accounts.get_account_cdp_endpoint",
            new=AsyncMock(return_value="http://127.0.0.1:9222"),
        ),
        patch(
            "backend.services.chrome_launcher.probe_port",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "backend.services.chrome_launcher.count_open_pages",
            side_effect=[12, 10],  # still over after hygiene
        ),
        patch(
            "backend.services.chrome_launcher.hygiene_browser_pages_all",
            new=AsyncMock(return_value=[]),
        ),
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            1.0,
            pre_run_delay=(30.0, 60.0),
            skip_day_chance=0.0,
            risk_skip_next_chance=0.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=0,
        )

    sync.assert_not_awaited()
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "skipped"
    assert state["last_skip_reason"] == "page_budget"
    assert not state.get("risk_failures")


@pytest.mark.asyncio
async def test_scheduler_restores_quiet_cycles_from_durable_state(monkeypatch):
    """Quiet arms survive restart via durable scheduler state."""
    app = _scheduler_app()
    app.state.creator_stats_scheduler_status = {"quiet_cycles_remaining": 0}
    sleep_calls: list[float] = []

    async def stop_after_interval(seconds: float) -> None:
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    async def seeded_load():
        return {
            "timestamps": [],
            "last_success_local_hour": None,
            "last_period": None,
            "risk_failures": [],
            "pause_until": None,
            "quiet_cycles_remaining": 2,
            "soft_risk_signals": [],
        }

    monkeypatch.setattr(app_module.asyncio, "sleep", stop_after_interval)
    monkeypatch.setattr("backend.db.creator_stats.load_scheduler_success_history", seeded_load)
    with (
        patch(
            "backend.services.creator_stats.pipeline.sync_all_active_accounts",
            new=AsyncMock(),
        ) as sync,
        pytest.raises(asyncio.CancelledError),
    ):
        await _creator_stats_scheduler(
            app,
            1.0,
            pre_run_delay=None,
            skip_day_chance=0.0,
            risk_skip_next_chance=0.0,
            post_success_long_break_chance=0.0,
            max_successful_crawls_per_week=0,
        )

    sync.assert_not_awaited()
    state = app.state.creator_stats_scheduler_status
    assert state["status"] == "skipped"
    assert state["last_skip_reason"] == "armed"
    assert state["quiet_cycles_remaining"] == 1
