"""模型模块 — LLM 路由与 token 估算.

Components:
- router: 多模型路由器
- retry: ainvoke/invoke exponential-backoff wrapper
- context_cap: prompt token estimation + history trimming
- visual_types: 视觉分析数据结构

Cost tracking lives in backend.config.models.MODEL_COST_PER_1K (canonical rate
table) + backend.agents.nodes._base.llm_perf_entry (writes kind:"llm" perf_log
entries consumed by the analytics cost reader).

Lazy re-exports: importing a submodule (``from backend.models.router import
get_model``) runs the parent ``__init__.py``; the previous eager imports made
every backend.models.* import cascade-load context_cap/retry/visual_types.
Resolved on first attribute access; no consumer uses the re-exports at import
time (verified — all imports target submodules directly).
"""

from typing import Any

__all__ = [
    "ColorPalette",
    "LayoutOption",
    "ModelRouter",
    "SceneAnalysisResult",
    "StyleOption",
    "cap_context",
    "estimate_tokens",
    "get_model",
    "get_router",
    "with_retry",
]

_LAZY_EXPORTS: dict[str, tuple[str, str]] = {
    "cap_context": ("backend.models.context_cap", "cap_context"),
    "estimate_tokens": ("backend.models.context_cap", "estimate_tokens"),
    "with_retry": ("backend.models.retry", "with_retry"),
    "ModelRouter": ("backend.models.router", "ModelRouter"),
    "get_model": ("backend.models.router", "get_model"),
    "get_router": ("backend.models.router", "get_router"),
    "ColorPalette": ("backend.models.visual_types", "ColorPalette"),
    "LayoutOption": ("backend.models.visual_types", "LayoutOption"),
    "SceneAnalysisResult": ("backend.models.visual_types", "SceneAnalysisResult"),
    "StyleOption": ("backend.models.visual_types", "StyleOption"),
}


def __getattr__(name: str) -> Any:
    mapping = _LAZY_EXPORTS.get(name)
    if mapping is None:
        raise AttributeError(f"module 'backend.models' has no attribute {name!r}")
    import importlib

    module = importlib.import_module(mapping[0])
    value = getattr(module, mapping[1])
    globals()[name] = value  # cache for subsequent access
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
