"""API 路由模块 — 各功能路由定义."""

from backend.api.routes.analytics import router as analytics_router
from backend.api.routes.blogger import router as blogger_router
from backend.api.routes.evaluation import router as evaluation_router
from backend.api.routes.free import router as free_router
from backend.api.routes.public_showcase import router as public_showcase_router
from backend.api.routes.public_telemetry import router as public_telemetry_router
from backend.api.routes.review import router as review_router
from backend.api.routes.workflow import router as workflow_router

__all__ = [
    "workflow_router",
    "review_router",
    "analytics_router",
    "blogger_router",
    "evaluation_router",
    "free_router",
    "public_showcase_router",
    "public_telemetry_router",
]
