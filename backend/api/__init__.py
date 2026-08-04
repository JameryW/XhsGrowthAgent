"""API 模块 — FastAPI 应用入口.

提供 REST API 接口:
- /api/workflow: 工作流控制
- /api/review: 人工审核
- /api/analytics: 数据分析

All re-exports are lazy via ``__getattr__`` (PEP 562). ``app`` imports the
full FastAPI application + route modules (which reach the graph builder);
``middleware`` pulls the same chain. Eagerly importing them here made every
``backend.api.X`` import pay ~0.7s. Callers now pay that only on first
attribute access. ``from backend.api import app`` etc. still work via
__getattr__; ``from backend.api import *`` works via __dir__.
"""

from typing import Any

# Map of re-exported names to the submodule that provides them.
# Resolved on first access via ``__getattr__`` (PEP 562).
_LAZY_EXPORTS = {
    "app": ("backend.api.app", "app"),
    "APIError": ("backend.api.errors", "APIError"),
    "ErrorCode": ("backend.api.errors", "ErrorCode"),
    "ReviewNotPendingError": ("backend.api.errors", "ReviewNotPendingError"),
    "ValidationError": ("backend.api.errors", "ValidationError"),
    "WorkflowNotFoundError": ("backend.api.errors", "WorkflowNotFoundError"),
    "error_handler_middleware": ("backend.api.middleware", "error_handler_middleware"),
    "ApiResponse": ("backend.api.responses", "ApiResponse"),
    "ErrorDetail": ("backend.api.responses", "ErrorDetail"),
    "error": ("backend.api.responses", "error"),
    "success": ("backend.api.responses", "success"),
}

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


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.api' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
