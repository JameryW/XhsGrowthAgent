"""FastAPI application — XHS Growth Engine API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import math
import os
import random
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, Response

from backend.api.middleware import error_handler_middleware
from backend.api.responses import ApiResponse, success
from backend.config.settings import Settings
from backend.graph.builder import compile_graph_dev
from backend.services.ripple_service import RippleService

# 加载 .env 文件（必须在其他导入之前）
load_dotenv(override=True)


# 小红书创作者在中国——活跃窗口按中国本地时间（UTC+8）计算，与容器 TZ 无关。
_CN_TZ = timezone(timedelta(hours=8))

# 窗口内时刻的人类活跃度权重（中国本地小时 → 相对权重）：晚间（20-22 点）
# 创作者最活跃，上午/下午次之，清晨与午休最低。窗口内均匀分布本身也是
# 机器特征——人看创作者中心的时刻集中在休息时段。
_HOUR_ACTIVITY_WEIGHTS: dict[int, float] = {
    8: 1.0,
    9: 2.5,
    10: 3.0,
    11: 3.0,
    12: 1.5,
    13: 1.0,
    14: 2.5,
    15: 3.0,
    16: 3.0,
    17: 2.5,
    18: 2.0,
    19: 2.0,
    20: 3.5,
    21: 4.0,
    22: 4.0,
}

# 跳过概率的星期权重（周一→周日）：周末创作者更活跃、更可能看数据，跳过
# 更少；周一跳过最多。固定的跳过概率本身不区分星期，也是一种规律。
_WEEKDAY_SKIP_FACTORS: tuple[float, ...] = (1.2, 1.0, 1.0, 1.0, 0.9, 0.8, 0.8)


def _finite_float(value: Any, default: float) -> float:
    """Return a finite float, falling back when configuration is malformed."""
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    return parsed if math.isfinite(parsed) else default


def _weekday_skip_factor(weekday: int) -> float:
    """返回该星期几对应的跳过概率权重；越界输入按 1.0 处理。"""
    if 0 <= weekday < len(_WEEKDAY_SKIP_FACTORS):
        return _WEEKDAY_SKIP_FACTORS[weekday]
    return 1.0


def _hour_weight(hour: int, avoid_hours: set[int] | None = None) -> float:
    """Human activity weight for a local hour, optionally down-ranking recent hours."""
    base = _HOUR_ACTIVITY_WEIGHTS.get(hour, 1.0)
    if avoid_hours and hour in avoid_hours:
        # Same-hour-of-day repeats are a machine fingerprint; keep a residual
        # weight so the hour is still possible, just unlikely.
        return max(0.05, base * 0.12)
    return base


def _clip_to_active_window(
    candidate: datetime,
    start_hour: int,
    end_hour: int,
    *,
    avoid_hours: set[int] | None = None,
) -> datetime:
    """把候选运行时刻限制在中国本地时间的每日活跃窗口内。

    风控视角下，凌晨准时打开创作者中心是典型的机器行为。候选时刻落在窗口外
    时，平移到下一个窗口内的一个随机点（不是窗口起点——起点本身又会成为
    新的固定模式）。窗口内的落点按人类活跃度加权（晚间高、清晨低），
    而不是均匀分布——任何整窗等概率的时刻分布都是可识别的机器特征。
    ``avoid_hours`` 进一步压低最近一次成功爬取的本地小时，避免"永远 21 点"。
    """
    local = candidate.astimezone(_CN_TZ)
    day_start = local.replace(hour=start_hour, minute=0, second=0, microsecond=0)
    day_end = local.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    if day_start <= local < day_end:
        # Inside the window: still re-jitter within ±45min and re-weight if the
        # candidate hour is one we should avoid (e.g. last crawl was 21:xx).
        if not avoid_hours or local.hour not in avoid_hours:
            return candidate
    base = day_start if local < day_end else day_start + timedelta(days=1)
    if local >= day_end:
        base = day_start + timedelta(days=1)
    elif local < day_start:
        base = day_start
    hours = list(range(start_hour, end_hour))
    weights = [_hour_weight(h, avoid_hours) for h in hours]
    if not hours or sum(weights) <= 0:
        hour = start_hour
    else:
        hour = random.choices(hours, weights=weights, k=1)[0]
    picked = base + timedelta(hours=hour - start_hour, seconds=random.uniform(0.0, 3600.0))
    return picked.astimezone(UTC)


def _prune_success_timestamps(timestamps: list[str], *, now: datetime, days: int = 7) -> list[str]:
    """Keep ISO success timestamps within the last ``days`` days."""
    cutoff = now - timedelta(days=days)
    kept: list[str] = []
    for raw in timestamps:
        try:
            ts = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts.astimezone(UTC) >= cutoff:
                kept.append(ts.astimezone(UTC).isoformat())
        except (TypeError, ValueError):
            continue
    return kept


def _weekly_crawl_budget_exhausted(
    success_timestamps: list[str],
    *,
    max_per_week: int,
    now: datetime | None = None,
) -> bool:
    """True when successful crawls in the last 7 days already hit the budget."""
    if max_per_week <= 0:
        return False
    now_utc = (now or datetime.now(UTC)).astimezone(UTC)
    kept = _prune_success_timestamps(success_timestamps, now=now_utc, days=7)
    return len(kept) >= max_per_week


def _pick_scheduled_period(period_7d_chance: float) -> str:
    """Pick a Creator Center stats window for one scheduled run.

    Always requesting ``30d`` is itself a fingerprint. Prefer a mix of lighter
    ``7d`` reads and full ``30d`` windows, weighted toward 30d so analytics
    monthly cards stay reasonably fresh.
    """
    chance = max(0.0, min(1.0, _finite_float(period_7d_chance, 0.35)))
    return "7d" if random.random() < chance else "30d"


def _is_riskish_error(message: str | None) -> bool:
    """True when the error text looks like auth / platform risk control."""
    text = str(message or "").lower()
    return any(
        token in text
        for token in (
            "401",
            "403",
            "auth",
            "login",
            "re-login",
            "300012",
            "risk",
            "风控",
            "安全限制",
            "empty",
            "cdp connect failed",
            "socket hang up",
        )
    )


async def _creator_stats_scheduler(
    app: FastAPI,
    interval_hours: float,
    *,
    startup_delay: tuple[float, float] | None = None,
    active_window: tuple[int, int] | None = None,
    skip_day_chance: float = 0.0,
    pre_run_delay: tuple[float, float] | None = None,
    period_7d_chance: float = 0.35,
    post_success_long_break_chance: float = 0.18,
    risk_skip_next_chance: float = 0.85,
    max_successful_crawls_per_week: int = 3,
) -> None:
    """Import active-account data on a human-looking schedule.

    The task is deliberately detached from application startup so a slow
    browser crawl cannot block readiness.  Its small state summary is exposed
    through ``/health``; raw account results are kept out of that response.

    反风控调度策略（核心：不允许任何可被识别的规律性）：
      1. 启动后不立即爬——先随机延迟 ``startup_delay``，避免"部署/重启即爬"
         的机器模式；``None`` 表示启动即跑（测试/手动语义）。
      2. 间隔不固定：每轮间隔在 0.65-1.75× ``interval_hours`` 间按三角分布
         取值（峰值 1×——人有"大致每天看一次"的习惯，均匀分布反而是毫无
         习惯的机器特征），且运行时刻被 ``active_window`` 限制在中国本地
         时间的每日活跃窗口内，深夜不爬；``None`` 表示不限制。
      3. 随机跳过：每轮以 ``skip_day_chance`` 概率整天跳过（按星期加权——
         周末创作者更活跃、跳过更少），"每天必爬一次"本身就是规律。
         跳过不算失败。
      4. 连续失败退避：第二次起连续失败间隔按 1.5-2.5× 随机放大，被风控/登录态
         失效时自动降频，成功一次即复位；风控失败还可强制再空一窗。
      5. 唤醒后开浏览器前再静默 ``pre_run_delay``；周期在 7d/30d 间随机，
         避免永远同一深链参数。
      6. 成功后以小概率进入长休（间隔再放大），模拟人几天不看数据。
      7. 滚动 7 天成功爬取次数封顶；快照仍新鲜时调度层直接跳过（不开浏览器）。
      8. 下次落点避开最近一次成功爬取的本地小时，打破"永远同一时刻"指纹。
    """
    interval_seconds = max(60.0, _finite_float(interval_hours, 0.0) * 3600.0)
    logger = logging.getLogger("xhs_growth.creator_stats.scheduler")
    # Uvicorn's default logging config does not install a root handler for
    # application loggers.  Keep this operational summary visible in
    # container logs without changing the logging setup for the whole app.
    if not logger.handlers:
        logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False
    state = getattr(app.state, "creator_stats_scheduler_status", None)
    if not isinstance(state, dict):
        state = {}
        app.state.creator_stats_scheduler_status = state
    success_history: list[str] = list(state.get("success_timestamps") or [])
    last_success_local_hour: int | None = state.get("last_success_local_hour")
    if isinstance(last_success_local_hour, str):
        with contextlib.suppress(ValueError):
            last_success_local_hour = int(last_success_local_hour)
    if not isinstance(last_success_local_hour, int):
        last_success_local_hour = None

    def _avoid_hours() -> set[int] | None:
        if last_success_local_hour is None:
            return None
        # Also soft-avoid adjacent hours so the distribution does not snap to
        # hour±1 as a new fixed pattern.
        return {
            (last_success_local_hour + delta) % 24
            for delta in (-1, 0, 1)
        }

    def _next_run(candidate: datetime) -> datetime:
        if active_window is not None:
            return _clip_to_active_window(
                candidate,
                active_window[0],
                active_window[1],
                avoid_hours=_avoid_hours(),
            )
        return candidate

    async def _sleep_until(target: datetime) -> None:
        state["next_run_at"] = target.isoformat()
        delay = max(1.0, (target - datetime.now(UTC)).total_seconds())
        await asyncio.sleep(delay)

    async def _active_snapshot_is_fresh() -> tuple[bool, int]:
        """Scheduler-level freshness gate: skip before settle/browser work."""
        try:
            from backend.db.accounts import get_active_account
            from backend.services.creator_stats.pipeline import _account_freshness_skip

            account = await get_active_account()
            if account is None:
                return False, 0
            return await _account_freshness_skip(str(account.id))
        except Exception as exc:
            logger.debug("scheduler freshness probe skipped: %s", exc)
            return False, 0

    # 1. 启动随机延迟：部署/重启后不再立刻爬取。
    if startup_delay is not None:
        delay_min = max(0.0, _finite_float(startup_delay[0], 0.0))
        delay_max = max(delay_min, _finite_float(startup_delay[1], delay_min))
        if delay_max > 0:
            candidate = datetime.now(UTC) + timedelta(seconds=random.uniform(delay_min, delay_max))
            target = _next_run(candidate)
            logger.info("creator stats scheduler first run delayed until %s", target.isoformat())
            await _sleep_until(target)

    consecutive_failures = 0
    skip_next_run = False
    while True:
        started_at = datetime.now(UTC)
        succeeded = False
        ran_crawl = False
        live_success = False
        success_history = _prune_success_timestamps(success_history, now=started_at)
        state["success_timestamps"] = success_history
        state["successes_last_7d"] = len(success_history)

        if skip_next_run:
            # 3. 随机跳过：本轮不爬，直接排下一轮。跳过不算失败、不触发退避。
            skip_next_run = False
            state.update(
                {
                    "status": "skipped",
                    "last_skipped_at": started_at.isoformat(),
                    "last_skip_reason": "armed",
                }
            )
            logger.info("scheduled creator stats import skipped this cycle (irregular cadence)")
        elif _weekly_crawl_budget_exhausted(
            success_history,
            max_per_week=int(max_successful_crawls_per_week or 0),
            now=started_at,
        ):
            state.update(
                {
                    "status": "skipped",
                    "last_skipped_at": started_at.isoformat(),
                    "last_skip_reason": "weekly_budget",
                }
            )
            logger.info(
                "scheduled creator stats import skipped: weekly budget exhausted "
                "(%s successes in 7d, max=%s)",
                len(success_history),
                max_successful_crawls_per_week,
            )
        else:
            fresh, retry_s = await _active_snapshot_is_fresh()
            if fresh:
                state.update(
                    {
                        "status": "skipped",
                        "last_skipped_at": started_at.isoformat(),
                        "last_skip_reason": "fresh_snapshot",
                        "last_status": "fresh",
                        "last_error": None,
                    }
                )
                logger.info(
                    "scheduled creator stats import skipped: snapshot still fresh "
                    "(retry_after≈%ss)",
                    retry_s,
                )
            else:
                ran_crawl = True
                # 5. 醒来后先静默再开浏览器——人从"想起来"到点开页面有空隙。
                if pre_run_delay is not None:
                    settle_min = max(0.0, _finite_float(pre_run_delay[0], 0.0))
                    settle_max = max(settle_min, _finite_float(pre_run_delay[1], settle_min))
                    if settle_max > 0:
                        settle = random.uniform(settle_min, settle_max)
                        state["status"] = "settling"
                        state["pre_run_delay_seconds"] = round(settle, 1)
                        logger.info(
                            "creator stats scheduler settling %.0fs before crawl", settle
                        )
                        await asyncio.sleep(settle)

                period = _pick_scheduled_period(period_7d_chance)
                state.update(
                    {
                        "status": "running",
                        "last_started_at": datetime.now(UTC).isoformat(),
                        "last_error": None,
                        "last_period": period,
                        "run_count": int(state.get("run_count") or 0) + 1,
                    }
                )
                logger.info(
                    "scheduled creator stats import started: interval_hours=%s run=%s period=%s",
                    interval_hours,
                    state["run_count"],
                    period,
                )
                try:
                    from backend.services.creator_stats.pipeline import (
                        _has_successful_live_sync,
                        sync_all_active_accounts,
                    )

                    graph = getattr(app.state, "graph", None)
                    store = getattr(graph, "store", None) if graph is not None else None
                    # Let CREATOR_STATS_SCHEDULED_FORCE_LIGHT decide whether the
                    # scheduled batch is forced list-only (default remains safe).
                    result = await sync_all_active_accounts(
                        store=store, period=period, prefer_light=None
                    )
                    finished_at = datetime.now(UTC)
                    last_error = result.get("error")
                    if not last_error and int(result.get("failed") or 0) > 0:
                        # Batch completed with per-account failures — surface the first
                        # few messages so /health is actionable (not just failed=N).
                        account_errors: list[str] = []
                        for item in result.get("results") or []:
                            if not isinstance(item, dict):
                                continue
                            err = item.get("error")
                            if not err or item.get("account_synced"):
                                continue
                            account_id = str(item.get("account_id") or "?").strip() or "?"
                            account_errors.append(f"{account_id}: {err}")
                            if len(account_errors) >= 3:
                                break
                        if account_errors:
                            last_error = "; ".join(account_errors)
                    # cooldown（冷却期内跳过）不是失败——不计入退避序列。
                    succeeded = bool(result.get("ok")) or result.get("status") == "cooldown"
                    live_success = _has_successful_live_sync(result)
                    if live_success:
                        success_history.append(finished_at.isoformat())
                        success_history = _prune_success_timestamps(
                            success_history, now=finished_at
                        )
                        last_success_local_hour = finished_at.astimezone(_CN_TZ).hour
                        state["last_success_local_hour"] = last_success_local_hour
                        state["success_timestamps"] = success_history
                        state["successes_last_7d"] = len(success_history)
                    state.update(
                        {
                            "status": "completed" if succeeded else "failed",
                            "last_status": result.get("status"),
                            "last_active_accounts": result.get("active_accounts", 0),
                            "last_succeeded": result.get("succeeded", 0),
                            "last_failed": result.get("failed", 0),
                            "last_started_at": started_at.isoformat(),
                            "last_finished_at": finished_at.isoformat(),
                            "last_error": last_error,
                            "last_period": period,
                        }
                    )
                    logger.info(
                        "scheduled creator stats import finished: status=%s active=%s "
                        "succeeded=%s failed=%s period=%s error=%s",
                        result.get("status"),
                        result.get("active_accounts", 0),
                        result.get("succeeded", 0),
                        result.get("failed", 0),
                        period,
                        last_error,
                    )
                except asyncio.CancelledError:
                    state.update(
                        {
                            "status": "cancelled",
                            "last_finished_at": datetime.now(UTC).isoformat(),
                        }
                    )
                    raise
                except Exception as exc:
                    finished_at = datetime.now(UTC)
                    state.update(
                        {
                            "status": "failed",
                            "last_finished_at": finished_at.isoformat(),
                            "last_error": str(exc),
                        }
                    )
                    logger.exception("scheduled creator stats import failed")
                # 4. 失败退避计数：成功即复位，第二次连续失败起才放大间隔。
                consecutive_failures = 0 if succeeded else consecutive_failures + 1
                state["consecutive_failures"] = consecutive_failures
        # 4. 失败退避：第二次连续失败起间隔按 1.5-2.5× 随机放大（固定倍数
        # 本身也是可预测的退避节律），成功即复位。
        # Auth/risk-shaped errors get a stronger multi-day-scale pause so we
        # do not re-hammer creator center right after a ban/401.
        last_err = str(state.get("last_error") or "")
        # Only score risk/backoff from a crawl we actually attempted this cycle.
        # A skipped window must not re-apply the previous failure's risk backoff.
        riskish = ran_crawl and (not succeeded) and _is_riskish_error(last_err)
        if riskish:
            backoff = random.uniform(3.0, 6.0)
            # Extra quiet window after risk/auth — do not schedule crawl→crawl.
            if random.random() < max(
                0.0, min(1.0, _finite_float(risk_skip_next_chance, 0.85))
            ):
                skip_next_run = True
                state["last_risk_skip_armed"] = True
        elif consecutive_failures <= 1:
            backoff = 1.0
        else:
            backoff = random.uniform(1.5, 2.5)
        # 6. 成功后偶尔长休——人不会永远按同一节奏回来。
        if (
            live_success
            and random.random()
            < max(0.0, min(1.0, _finite_float(post_success_long_break_chance, 0.18)))
        ):
            backoff *= random.uniform(1.8, 2.8)
            state["last_long_break"] = True
        # 2. 间隔按 0.65-1.75× 三角分布取值（峰值 1×，模拟人的习惯节律）；
        # active_window 再把落点限制在人类活动时段。
        if skip_day_chance > 0 and not skip_next_run:
            factor = _weekday_skip_factor(datetime.now(_CN_TZ).weekday())
            if random.random() < min(1.0, skip_day_chance * factor):
                skip_next_run = True
        candidate = datetime.now(UTC) + timedelta(
            seconds=interval_seconds * random.triangular(0.65, 1.75, 1.0) * backoff
        )
        await _sleep_until(_next_run(candidate))


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ── DB + checkpointer initialization ──
    db_uri = os.environ.get("POSTGRES_URI")
    checkpointer = None
    checkpoint_pool = None
    store_context = None
    creator_stats_scheduler: asyncio.Task[None] | None = None

    if db_uri:
        try:
            # 1) Initialize app-level DB pool (for workflows table)
            from backend.db.pool import init_pool

            await init_pool()

            # 2) Ensure all tables exist + compile graph — run in parallel
            #    (ensure_table calls are idempotent and use their own connections)
            from backend.db.accounts import ensure_tables as ensure_account_tables
            from backend.db.console_users import (
                bootstrap_default_user,
            )
            from backend.db.console_users import (
                ensure_tables as ensure_console_users,
            )
            from backend.db.creative_memory import ensure_tables as ensure_creative_memory
            from backend.db.creator_stats import ensure_tables as ensure_creator_stats
            from backend.db.evaluator_config import (
                ensure_tables as ensure_evaluator_config,
            )
            from backend.db.public_telemetry import ensure_tables as ensure_public_telemetry
            from backend.db.quality_evaluations import (
                ensure_tables as ensure_quality_evaluations,
            )
            from backend.db.system_config import (
                bootstrap_from_environ,
                migrate_from_accounts,
            )
            from backend.db.system_config import (
                ensure_tables as ensure_system_config,
            )
            from backend.db.workflows import ensure_table
            from backend.graph.builder import compile_graph_prod

            # ponytail: parallel ensure_tables + graph compile; bootstrap steps
            # depend on system_config table existing so they run after ensure.
            ensure_coros = [
                ensure_table(),
                ensure_account_tables(),
                ensure_console_users(),
                ensure_system_config(),
                ensure_evaluator_config(),
                ensure_quality_evaluations(),
                ensure_creator_stats(),
                ensure_creative_memory(),
                ensure_public_telemetry(),
            ]
            graph_task = compile_graph_prod(db_uri)
            results = await asyncio.gather(*ensure_coros, graph_task)

            gresult = cast("tuple[Any, Any]", results[-1])  # graph_task is last in gather
            graph, result = gresult
            if result is not None:
                checkpointer, checkpoint_pool, store_context = result
                app.state.checkpointer = checkpointer
            app.state.graph = graph

            # Bootstrap steps (depend on tables existing above)
            await migrate_from_accounts()
            await bootstrap_from_environ()
            await bootstrap_default_user()

            from backend.db.system_config import activate_system_config

            await activate_system_config()
        except Exception as e:
            logging.getLogger("xhs_growth").warning(f"Postgres setup failed, using SQLite: {e}")
            graph = await compile_graph_dev()
            app.state.graph = graph
            app.state.checkpointer = graph.checkpointer
    else:
        graph = await compile_graph_dev()
        app.state.graph = graph
        # Expose checkpointer for health check (SQLite in dev mode)
        app.state.checkpointer = graph.checkpointer

    # Start Ripple background health check
    settings = Settings()
    ripple = RippleService.get_instance()
    interval = settings.ripple.health_check_interval
    ripple.start_background_health_check(interval_seconds=interval)

    # Start omp RPC bridge manager (best-effort — not fatal if omp unavailable)
    try:
        from backend.services.omp_bridge import get_bridge_manager

        bridge_manager = get_bridge_manager()
        await bridge_manager.start()
        app.state.omp_bridge_manager = bridge_manager
    except Exception as e:
        logging.getLogger("xhs_growth").warning(f"omp bridge manager not started: {e}")
        app.state.omp_bridge_manager = None

    # Import only enabled accounts in the background.  The scheduler is
    # deliberately started after DB/bootstrap and bridge initialization so it
    # cannot race account table creation or Chrome startup.  A non-positive
    # interval disables it while leaving the manual API available.
    pool_ready = False
    try:
        from backend.db.pool import is_pool_ready

        pool_ready = is_pool_ready()
        interval_hours = _finite_float(settings.creator_stats.sync_interval_hours, 0.0)
    except (AttributeError, TypeError, ValueError):
        interval_hours = 0.0
    # 反风控调度参数（启动随机延迟 + 中国时间活跃窗口 + 随机跳过 + 唤醒静默
    # + 周期随机）；读取失败时退化为旧行为（启动即跑、不限窗口、不跳过）。
    startup_delay: tuple[float, float] | None = None
    active_window: tuple[int, int] | None = None
    skip_day_chance = 0.0
    pre_run_delay: tuple[float, float] | None = None
    period_7d_chance = 0.35
    post_success_long_break_chance = 0.18
    risk_skip_next_chance = 0.85
    max_successful_crawls_per_week = 3
    try:
        cs_settings = settings.creator_stats
        startup_delay = (
            _finite_float(cs_settings.startup_delay_min_seconds, 600.0),
            _finite_float(cs_settings.startup_delay_max_seconds, 2400.0),
        )
        active_window = (
            int(cs_settings.active_window_start_hour),
            int(cs_settings.active_window_end_hour),
        )
        skip_day_chance = max(0.0, min(1.0, _finite_float(cs_settings.skip_day_chance, 0.25)))
        pre_run_delay = (
            _finite_float(cs_settings.pre_run_delay_min_seconds, 45.0),
            _finite_float(cs_settings.pre_run_delay_max_seconds, 240.0),
        )
        period_7d_chance = max(
            0.0, min(1.0, _finite_float(cs_settings.period_7d_chance, 0.35))
        )
        post_success_long_break_chance = max(
            0.0,
            min(1.0, _finite_float(cs_settings.post_success_long_break_chance, 0.18)),
        )
        risk_skip_next_chance = max(
            0.0, min(1.0, _finite_float(cs_settings.risk_skip_next_chance, 0.85))
        )
        max_successful_crawls_per_week = max(
            0, int(cs_settings.max_successful_crawls_per_week)
        )
    except (AttributeError, TypeError, ValueError):
        startup_delay = None
        active_window = None
        skip_day_chance = 0.0
        pre_run_delay = None
        period_7d_chance = 0.35
        post_success_long_break_chance = 0.18
        risk_skip_next_chance = 0.85
        max_successful_crawls_per_week = 3
    app.state.creator_stats_scheduler_status = {
        "enabled": bool(db_uri and interval_hours > 0 and pool_ready),
        "interval_hours": interval_hours,
        "status": "disabled",
        "run_count": 0,
        "last_started_at": None,
        "last_finished_at": None,
        "last_status": None,
        "last_active_accounts": 0,
        "last_succeeded": 0,
        "last_failed": 0,
        "last_error": None,
        "next_run_at": None,
        "last_period": None,
        "success_timestamps": [],
        "successes_last_7d": 0,
        "last_success_local_hour": None,
    }
    if db_uri and interval_hours > 0 and pool_ready:
        app.state.creator_stats_scheduler_status["status"] = "scheduled"
        creator_stats_scheduler = asyncio.create_task(
            _creator_stats_scheduler(
                app,
                interval_hours,
                startup_delay=startup_delay,
                active_window=active_window,
                skip_day_chance=skip_day_chance,
                pre_run_delay=pre_run_delay,
                period_7d_chance=period_7d_chance,
                post_success_long_break_chance=post_success_long_break_chance,
                risk_skip_next_chance=risk_skip_next_chance,
                max_successful_crawls_per_week=max_successful_crawls_per_week,
            ),
            name="creator-stats-active-account-scheduler",
        )
        app.state.creator_stats_scheduler = creator_stats_scheduler
    else:
        app.state.creator_stats_scheduler = None

    yield
    # ── Cleanup ──
    if creator_stats_scheduler is not None:
        creator_stats_scheduler.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await creator_stats_scheduler

    # Stop omp bridge manager
    if getattr(app.state, "omp_bridge_manager", None):
        with contextlib.suppress(Exception):
            await app.state.omp_bridge_manager.stop()

    # Stop Ripple background health check + close connections
    ripple.stop_background_health_check()
    with contextlib.suppress(Exception):
        await ripple.close()

    # Close graph persistence resources first (own their connections)
    if store_context is not None:
        with contextlib.suppress(Exception):
            await store_context.__aexit__(None, None, None)
    if checkpoint_pool is not None:
        with contextlib.suppress(Exception):
            await checkpoint_pool.close()
    # Close app-level DB pool
    with contextlib.suppress(Exception):
        from backend.db.pool import close_pool

        await close_pool()


app = FastAPI(
    title="小红书增长引擎",
    description="XHS Growth Engine Agent API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.middleware("http")(error_handler_middleware)

from backend.api.routes import (  # noqa: E402
    accounts,
    analytics,
    auth,
    blogger,
    evaluation,
    free,
    inbox,
    optimization,
    public_showcase,
    public_telemetry,
    realtime,
    review,
    workflow,
)
from backend.api.routes.agent import router as agent_router  # noqa: E402
from backend.api.routes.console_users import router as console_users_router  # noqa: E402
from backend.api.routes.system import router as system_router  # noqa: E402
from backend.api.routes.system_config import router as system_config_router  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["accounts"])
app.include_router(console_users_router, prefix="/api/console-users", tags=["console-users"])
app.include_router(system_config_router, prefix="/api/system-config", tags=["system-config"])
app.include_router(workflow.router, prefix="/api/workflow", tags=["workflow"])
app.include_router(public_showcase.router, prefix="/api/public", tags=["public-showcase"])
app.include_router(public_telemetry.router, prefix="/api/public", tags=["public-telemetry"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(system_router, prefix="/api/system", tags=["system"])
app.include_router(realtime.router, tags=["realtime"])  # WebSocket 不需要 /api 前缀
app.include_router(agent_router, tags=["agent"])  # WebSocket at /api/agent/ws
app.include_router(optimization.router, prefix="/api/optimization", tags=["optimization"])
app.include_router(blogger.router, prefix="/api/optimization", tags=["blogger"])
app.include_router(free.router, prefix="/api/free", tags=["free"])
app.include_router(inbox.router, prefix="/api", tags=["inbox"])


@app.get("/health")
async def health() -> ApiResponse[Any]:
    from backend.db.pool import is_pool_ready

    db_status = "connected" if is_pool_ready() else "unavailable"
    scheduler_state = getattr(app.state, "creator_stats_scheduler_status", None)
    scheduler = None
    if isinstance(scheduler_state, dict):
        health_fields = (
            "enabled",
            "interval_hours",
            "status",
            "run_count",
            "last_started_at",
            "last_finished_at",
            "last_status",
            "last_active_accounts",
            "last_succeeded",
            "last_failed",
            "last_error",
            "last_period",
            "next_run_at",
            "successes_last_7d",
            "last_skip_reason",
            "last_success_local_hour",
        )
        scheduler = {key: scheduler_state.get(key) for key in health_fields}
    return success(
        {
            "status": "ok",
            "version": "0.1.0",
            "db": db_status,
            "creator_stats_scheduler": scheduler,
        }
    )


# 托管前端静态文件（生产环境）
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"


@app.get("/favicon.svg", include_in_schema=False)
async def serve_favicon() -> Response:
    """Serve the browser favicon instead of falling through to the SPA shell."""
    favicon_path = frontend_dist / "favicon.svg"
    if not favicon_path.is_file():
        return Response(status_code=404)
    return FileResponse(
        str(favicon_path),
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"

    # SPA catch-all: 非 API/非 WebSocket 路由返回 index.html（不缓存）
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> Response:
        """Serve SPA frontend — return index.html for all non-API routes."""
        # API、WebSocket 和事件恢复路径不处理
        if (
            full_path.startswith("api/")
            or full_path.startswith("ws")
            or full_path.startswith("events/")
        ):
            return Response(status_code=404)
        # assets 目录提供静态文件（带缓存头）
        if full_path.startswith("assets/"):
            file_path = assets_dir / full_path.removeprefix("assets/")
            if file_path.is_file():
                return FileResponse(
                    str(file_path),
                    headers={"Cache-Control": "public, max-age=31536000, immutable"},
                )
        # 其他路由返回 index.html
        return Response(
            content=(frontend_dist / "index.html").read_bytes(),
            media_type="text/html",
            headers={"Cache-Control": "no-cache"},
        )
