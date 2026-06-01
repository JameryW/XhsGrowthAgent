"""FastAPI application — XHS Growth Engine API."""

from __future__ import annotations

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
from backend.graph.builder import compile_graph_dev

# 加载 .env 文件（必须在其他导入之前）
load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时编译图 — 基于 POSTGRES_URI 环境变量选择检查点
    db_uri = os.environ.get("POSTGRES_URI")
    checkpointer = None
    if db_uri:
        try:
            from backend.graph.builder import compile_graph_prod
            graph, checkpointer = await compile_graph_prod(db_uri)
            app.state.checkpointer = checkpointer
            app.state.graph = graph
        except Exception as e:
            logging.getLogger("xhs_growth").warning(
                f"Postgres checkpointer failed, using memory: {e}"
            )
            app.state.graph = compile_graph_dev()
    else:
        app.state.graph = compile_graph_dev()
    yield
    # Cleanup checkpointer if present
    if checkpointer is not None:
        try:
            await checkpointer.__aexit__(None, None, None)
        except Exception:
            pass


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

from backend.api.routes import analytics, auth, optimization, realtime, review, workflow  # noqa: E402
from backend.api.routes.system import router as system_router  # noqa: E402

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(workflow.router, prefix="/api/workflow", tags=["workflow"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(system_router, prefix="/api/system", tags=["system"])
app.include_router(realtime.router, tags=["realtime"])  # WebSocket 不需要 /api 前缀
app.include_router(optimization.router, prefix="/api/optimization", tags=["optimization"])


@app.get("/health")
async def health():
    return success({"status": "ok", "version": "0.1.0"})


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
