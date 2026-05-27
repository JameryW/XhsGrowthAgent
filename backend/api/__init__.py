"""API 模块 — FastAPI 应用入口.

提供 REST API 接口:
- /api/workflow: 工作流控制
- /api/review: 人工审核
- /api/analytics: 数据分析
"""

from backend.api.app import app
from backend.api.responses import ApiResponse, ErrorDetail, success, error
from backend.api.errors import (
    ErrorCode,
    APIError,
    WorkflowNotFoundError,
    ReviewNotPendingError,
    ValidationError,
)
from backend.api.middleware import error_handler_middleware

__all__ = [
    "app",
    "ApiResponse",
    "ErrorDetail",
    "success",
    "error",
    "ErrorCode",
    "APIError",
    "WorkflowNotFoundError",
    "ReviewNotPendingError",
    "ValidationError",
    "error_handler_middleware",
]