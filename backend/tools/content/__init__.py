"""内容工具模块 — 文案与视觉生成.

Tools:
- de_ai_taste: 去 AI 味润色 (LLM 增强 + 算法降级)
- layout_recommender: 排版布局推荐 (基于场景分析)
- style_library: 视觉风格库 (基于场景分析)

Helpers:
- get_default_layouts: 默认布局配置 (降级使用)
- get_default_styles: 默认风格配置 (降级使用)
- polish_copy / algorithmic_de_ai: 供 agent 直调的去 AI 味接口

All re-exports are lazy via ``__getattr__`` (PEP 562). ``de_ai_taste`` pulls
in langchain_openai (LLM); eagerly importing it here made every
``backend.tools.content.X`` import pay ~1.8s of one-time langchain cost
before the suite hit it elsewhere. Callers now pay that only on first
attribute access. ``from backend.tools.content import layout_recommender``
etc. still work via __getattr__; ``import *`` works via __dir__.
"""

from typing import Any

# Map of re-exported names to the submodule that provides them.
# Resolved on first access via ``__getattr__`` (PEP 562).
_LAZY_EXPORTS = {
    "de_ai_taste": ("backend.tools.content.de_ai_taste", "de_ai_taste"),
    "algorithmic_de_ai": ("backend.tools.content.de_ai_taste", "algorithmic_de_ai"),
    "polish_copy": ("backend.tools.content.de_ai_taste", "polish_copy"),
    "layout_recommender": ("backend.tools.content.layout", "layout_recommender"),
    "get_default_layouts": ("backend.tools.content.layout", "get_default_layouts"),
    "style_library": ("backend.tools.content.style", "style_library"),
    "get_default_styles": ("backend.tools.content.style", "get_default_styles"),
}

__all__ = [
    "de_ai_taste",
    "polish_copy",
    "algorithmic_de_ai",
    "layout_recommender",
    "get_default_layouts",
    "style_library",
    "get_default_styles",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.tools.content' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
