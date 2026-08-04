"""Service layer for XHS Growth Agent.

Services orchestrate multiple tools and handle errors/caching.
They sit between Agents (business logic) and Tools (atomic operations).
"""

from __future__ import annotations

from typing import Any

# Lazy re-exports — importing omp_bridge / optimization_service / ripple_service
# eagerly at package load costs ~0.37s (httpx, langchain chain) on every app
# cold start. RippleService is constructed in the app lifespan; the others are
# used at request time. Resolved on first attribute access, cached in globals.
_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "ClientMessageType": ("backend.services.omp_bridge", "ClientMessageType"),
    "OmpBridgeManager": ("backend.services.omp_bridge", "OmpBridgeManager"),
    "OmpSession": ("backend.services.omp_bridge", "OmpSession"),
    "ServerEventType": ("backend.services.omp_bridge", "ServerEventType"),
    "XHS_HOST_TOOLS": ("backend.services.omp_bridge", "XHS_HOST_TOOLS"),
    "get_bridge_manager": ("backend.services.omp_bridge", "get_bridge_manager"),
    "OptimizationService": (
        "backend.services.optimization_service",
        "OptimizationService",
    ),
    "RippleService": ("backend.services.ripple_service", "RippleService"),
    "RippleHealthStatus": (
        "backend.services.ripple_service",
        "RippleHealthStatus",
    ),
}

__all__ = [
    "ClientMessageType",
    "OmpBridgeManager",
    "OmpSession",
    "OptimizationService",
    "RippleService",
    "RippleHealthStatus",
    "ServerEventType",
    "XHS_HOST_TOOLS",
    "get_bridge_manager",
]


def __getattr__(name: str) -> Any:
    mapping = _LAZY_EXPORTS.get(name)
    if mapping is None:
        raise AttributeError(f"module 'backend.services' has no attribute {name!r}")
    module_path, attr = mapping
    import importlib

    module = importlib.import_module(module_path)
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
