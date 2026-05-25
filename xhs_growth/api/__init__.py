"""API 模块 — FastAPI 应用入口.

提供 REST API 接口:
- /api/workflow: 工作流控制
- /api/review: 人工审核
- /api/analytics: 数据分析
"""

from xhs_growth.api.app import app
from xhs_growth.api.responses import ApiResponse, ErrorDetail, success, error
from xhs_growth.api.errors import (
    ErrorCode,
    APIError,
    WorkflowNotFoundError,
    ReviewNotPendingError,
    ValidationError,
)
from xhs_growth.api.middleware import error_handler_middleware

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