"""工具模块 — LangChain 工具注册.

Components:
- registry: Agent 工具映射表
- ripple: Ripple CAS 模拟引擎工具
- xhs: 小红书平台工具
- content: 内容生成工具
- analysis: 分析工具
- scheduling: 调度工具

ToolRegistry is lazy via ``__getattr__`` (PEP 562). ``registry`` imports
``langchain_core.tools.BaseTool``; eagerly importing it here made every
``backend.tools.X`` import pay ~0.75s. ``from backend.tools import
ToolRegistry`` still works via __getattr__; ``from backend.tools import *``
works via __dir__.
"""

from typing import Any

_LAZY_EXPORTS = {
    "ToolRegistry": ("backend.tools.registry", "ToolRegistry"),
}

__all__ = ["ToolRegistry"]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.tools' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
