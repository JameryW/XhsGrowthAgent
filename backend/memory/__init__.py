"""记忆模块 — LangGraph BaseStore 管理.

Components:
- store: MemoryManager 中心管理器
- creative: CreativeMemory 创作记忆三层读写
- types: TypedDict 定义 (StyleDNA, ConversionPlay, MaterialEntry, NicheBenchmark)
- scene_database: 场景分析数据存储
- index: Store index config for semantic search

All re-exports are lazy via ``__getattr__`` (PEP 562). ``creative`` and
``store`` pull in langgraph (BaseStore); ``index`` pulls langchain embeddings
config. Eagerly importing them here made every ``backend.memory.types`` /
``backend.memory.store`` import pay ~1.3s. Callers now pay that only on first
attribute access. ``from backend.memory import MemoryManager`` etc. still work
via __getattr__; ``from backend.memory import *`` works via __dir__.
"""

from typing import Any

# Map of re-exported names to the submodule that provides them.
# Resolved on first access via ``__getattr__`` (PEP 562).
_LAZY_EXPORTS = {
    "CreativeMemory": ("backend.memory.creative", "CreativeMemory"),
    "SceneDatabase": ("backend.memory.scene_database", "SceneDatabase"),
    "MemoryManager": ("backend.memory.store", "MemoryManager"),
    "clear_store_index_cache": ("backend.memory.index", "clear_store_index_cache"),
    "get_store_index": ("backend.memory.index", "get_store_index"),
    "get_prod_store_index": ("backend.memory.index", "get_prod_store_index"),
    "semantic_index_status": ("backend.memory.index", "semantic_index_status"),
}

__all__ = [
    "CreativeMemory",
    "MemoryManager",
    "SceneDatabase",
    "clear_store_index_cache",
    "get_store_index",
    "get_prod_store_index",
    "semantic_index_status",
]


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        import importlib

        module_name, attr = _LAZY_EXPORTS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr)
        globals()[name] = value  # cache for subsequent access
        return value
    raise AttributeError(f"module 'backend.memory' has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS))
