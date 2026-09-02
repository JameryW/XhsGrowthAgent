"""API 路由模块 — 各功能路由定义.

All router re-exports are lazy via ``__getattr__`` (PEP 562). Each route
module reaches the graph builder / model router; eagerly importing them
here made every ``backend.api.routes.X`` import pay ~0.4s. Callers now pay
that only on first attribute access. Submodule imports (``from
backend.api.routes import analytics as analytics_routes``) resolve
normally without touching __getattr__ (Python resolves submodules
directly); ``import *`` works via __dir__.
"""

from typing import Any

_LAZY_EXPORTS = {
    "analytics_router": ("backend.api.routes.analytics", "router"),
    "blogger_router": ("backend.api.routes.blogger", "router"),
    "creator_agent_router": ("backend.api.routes.creator_agent", "router"),
    "evaluation_router": ("backend.api.routes.evaluation", "router"),
    "free_router": ("backend.api.routes.free", "router"),
    "public_showcase_router": ("backend.api.routes.public_showcase", "router"),
    "public_telemetry_router": ("backend.api.routes.public_telemetry", "router"),
    "review_router": ("backend.api.routes.review", "router"),
    "workflow_router": ("backend.api.routes.workflow", "router"),
}

__all__ = [
    "workflow_router",
    "review_router",
    "analytics_router",
    "blogger_router",
    "creator_agent_router",
    "evaluation_router",
    "free_router",
    "public_showcase_router",
    "public_telemetry_router",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.api.routes' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
