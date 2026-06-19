"""FastAPI application — XHS Growth Engine API."""

from __future__ import annotations

import contextlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, Response

from backend.api.middleware import error_handler_middleware
from backend.api.responses import success
from backend.config.settings import Settings
from backend.graph.builder import compile_graph_dev
from backend.services.ripple_service import RippleService

# 加载 .env 文件（必须在其他导入之前）
load_dotenv(override=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── DB + checkpointer initialization ──
    db_uri = os.environ.get("POSTGRES_URI")
    checkpointer = None
    checkpoint_pool = None
    store_context = None

    if db_uri:
        try:
            # 1) Initialize app-level DB pool (for workflows table)
            from backend.db.pool import init_pool
            await init_pool()

            # 2) Ensure workflows table exists
            from backend.db.workflows import ensure_table
            await ensure_table()

            # 2b) Ensure accounts + credentials tables exist
            from backend.db.accounts import ensure_tables as ensure_account_tables
            await ensure_account_tables()

            # 2b.1) Ensure console_users + system_config tables exist
            from backend.db.console_users import (
                bootstrap_default_user,
            )
            from backend.db.console_users import (
                ensure_tables as ensure_console_users,
            )
            from backend.db.system_config import (
                bootstrap_from_environ,
                migrate_from_accounts,
            )
            from backend.db.system_config import (
                ensure_tables as ensure_system_config,
            )
            await ensure_console_users()
            await ensure_system_config()

            # 2b.2) One-shot migration: pull SYSTEM_KEYS from active account → system_config.
            # Idempotent: no-op once system_config has any rows.
            await migrate_from_accounts()

            # 2b.3) If still empty (fresh install), seed from os.environ
            await bootstrap_from_environ()

            # 2b.4) Seed default console user (admin/admin123) if none exist
            await bootstrap_default_user()

            # 2c) Load active account credentials (XHS keys) into os.environ
            from backend.db.accounts import load_active_credentials
            await load_active_credentials()

            # 2c.1) Activate system_config into os.environ
            from backend.db.system_config import activate_system_config
            await activate_system_config()

            # 3) Compile graph with production checkpointer (uses its own pool)
            from backend.graph.builder import compile_graph_prod
            graph, result = await compile_graph_prod(db_uri)
            if result is not None:
                checkpointer, checkpoint_pool, store_context = result
                app.state.checkpointer = checkpointer
            app.state.graph = graph
        except Exception as e:
            logging.getLogger("xhs_growth").warning(
                f"Postgres setup failed, using SQLite: {e}"
            )
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

    yield
    # ── Cleanup ──
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
    optimization,
    realtime,
    review,
    workflow,
)
from backend.api.routes.console_users import router as console_users_router  # noqa: E402
from backend.api.routes.system import router as system_router  # noqa: E402
from backend.api.routes.system_config import router as system_config_router  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(accounts.router, prefix="/api/accounts", tags=["accounts"])
app.include_router(console_users_router, prefix="/api/console-users", tags=["console-users"])
app.include_router(system_config_router, prefix="/api/system-config", tags=["system-config"])
app.include_router(workflow.router, prefix="/api/workflow", tags=["workflow"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(system_router, prefix="/api/system", tags=["system"])
app.include_router(realtime.router, tags=["realtime"])  # WebSocket 不需要 /api 前缀
app.include_router(optimization.router, prefix="/api/optimization", tags=["optimization"])
app.include_router(blogger.router, prefix="/api/optimization", tags=["blogger"])


@app.get("/health")
async def health():
    from backend.db.pool import is_pool_ready
    db_status = "connected" if is_pool_ready() else "unavailable"
    return success({"status": "ok", "version": "0.1.0", "db": db_status})


# 托管前端静态文件（生产环境）
frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"

if frontend_dist.exists():
    assets_dir = frontend_dist / "assets"

    # SPA catch-all: 非 API/非 WebSocket 路由返回 index.html（不缓存）
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve SPA frontend — return index.html for all non-API routes."""
        # WebSocket 和事件恢复路径不处理
        if full_path.startswith("ws") or full_path.startswith("events/"):
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
