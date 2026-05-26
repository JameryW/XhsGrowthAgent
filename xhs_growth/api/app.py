"""FastAPI application — XHS Growth Engine API."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from xhs_growth.api.middleware import error_handler_middleware
from xhs_growth.api.responses import success
from xhs_growth.graph.builder import compile_graph_dev


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时编译图
    app.state.graph = compile_graph_dev()
    yield


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

from xhs_growth.api.routes import workflow, review, analytics, realtime  # noqa: E402

app.include_router(workflow.router, prefix="/api/workflow", tags=["workflow"])
app.include_router(review.router, prefix="/api/review", tags=["review"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["analytics"])
app.include_router(realtime.router, prefix="/api", tags=["realtime"])


@app.get("/health")
async def health():
    return success({"status": "ok", "version": "0.1.0"})


# 托管前端静态文件（生产环境）
import os
from pathlib import Path

frontend_dist = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_dist.exists():
    from fastapi.staticfiles import StaticFiles
    # 注意：API 路由已注册，静态文件挂载在最后
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
