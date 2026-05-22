"""API 路由模块 — 各功能路由定义."""

from xhs_growth.api.routes.workflow import router as workflow_router
from xhs_growth.api.routes.review import router as review_router
from xhs_growth.api.routes.analytics import router as analytics_router

__all__ = ["workflow_router", "review_router", "analytics_router"]