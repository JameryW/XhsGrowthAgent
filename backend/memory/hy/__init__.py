"""hy-memory 集成包 — 混元双系统认知记忆的异步门面。

Components:
- settings: HyMemorySettings（HYMEMORY_ 前缀环境变量，默认关闭）
- bridge: HyMemoryBridge（SDK 异步门面：recall / remember / forget / metrics）
- recall: recall_hy_memory（→ P1b RetrievalResult 适配器）

hy_memory SDK 是**可选依赖**（pyproject 的 ``memory-hy`` extra）。本包任何
import 都不触碰 SDK —— 只有 ``HyMemoryBridge`` 真正启用时才懒加载，所以未安装
extra 的部署导入零成本。
"""

from typing import Any

# Map of re-exported names to the submodule that provides them.
# Resolved on first access via ``__getattr__`` (PEP 562) — same convention as
# ``backend.memory.__init__``: importing this package must stay cheap.
_LAZY_EXPORTS = {
    "HyMemoryBridge": ("backend.memory.hy.bridge", "HyMemoryBridge"),
    "HyMemorySettings": ("backend.memory.hy.settings", "HyMemorySettings"),
    "get_hy_memory_bridge": ("backend.memory.hy.bridge", "get_hy_memory_bridge"),
    "hy_namespace": ("backend.memory.hy.recall", "hy_namespace"),
    "recall_hy_memory": ("backend.memory.hy.recall", "recall_hy_memory"),
    "reset_hy_memory_bridge": ("backend.memory.hy.bridge", "reset_hy_memory_bridge"),
}

__all__ = [
    "HyMemoryBridge",
    "HyMemorySettings",
    "get_hy_memory_bridge",
    "hy_namespace",
    "recall_hy_memory",
    "reset_hy_memory_bridge",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
