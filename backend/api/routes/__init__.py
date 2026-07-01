"""API 路由模块 — 各功能路由定义."""

from backend.api.routes.analytics import router as analytics_router
from backend.api.routes.blogger import router as blogger_router
from backend.api.routes.evaluation import router as evaluation_router
from backend.api.routes.review import router as review_router
from backend.api.routes.workflow import router as workflow_router

__all__ = [
    "workflow_router",
    "review_router",
    "analytics_router",
    "blogger_router",
    "evaluation_router",
]
