"""FastAPI application — XHS Growth Engine API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
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


async def _creator_stats_scheduler(app: FastAPI, interval_hours: float) -> None:
    """Import active-account data immediately, then repeat at a fixed interval.

    The task is deliberately detached from application startup so a slow
    browser crawl cannot block readiness.  Its small state summary is exposed
    through ``/health``; raw account results are kept out of that response.
    """
    interval_seconds = max(60.0, float(interval_hours) * 3600.0)
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

    while True:
        started_at = datetime.now(UTC)
        state.update(
            {
                "status": "running",
                "last_started_at": started_at.isoformat(),
                "last_error": None,
                "run_count": int(state.get("run_count") or 0) + 1,
            }
        )
        logger.info(
            "scheduled creator stats import started: interval_hours=%s run=%s",
            interval_hours,
            state["run_count"],
        )
        try:
            from backend.services.creator_stats.pipeline import sync_all_active_accounts

            graph = getattr(app.state, "graph", None)
            store = getattr(graph, "store", None) if graph is not None else None
            result = await sync_all_active_accounts(store=store, period="30d")
            finished_at = datetime.now(UTC)
            state.update(
                {
                    "status": "completed" if result.get("ok") else "failed",
                    "last_status": result.get("status"),
                    "last_active_accounts": result.get("active_accounts", 0),
                    "last_succeeded": result.get("succeeded", 0),
                    "last_failed": result.get("failed", 0),
                    "last_started_at": started_at.isoformat(),
                    "last_finished_at": finished_at.isoformat(),
                    "last_error": result.get("error"),
                    "next_run_at": (finished_at + timedelta(seconds=interval_seconds)).isoformat(),
                }
            )
            logger.info(
                "scheduled creator stats import finished: status=%s active=%s "
                "succeeded=%s failed=%s",
                result.get("status"),
                result.get("active_accounts", 0),
                result.get("succeeded", 0),
                result.get("failed", 0),
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
                    "next_run_at": (finished_at + timedelta(seconds=interval_seconds)).isoformat(),
                }
            )
            logger.exception("scheduled creator stats import failed")
        await asyncio.sleep(interval_seconds)


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
        interval_hours = float(settings.creator_stats.sync_interval_hours)
    except (AttributeError, TypeError, ValueError):
        interval_hours = 0.0
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
    }
    if db_uri and interval_hours > 0 and pool_ready:
        app.state.creator_stats_scheduler_status["status"] = "scheduled"
        creator_stats_scheduler = asyncio.create_task(
            _creator_stats_scheduler(app, interval_hours),
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
            "next_run_at",
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
