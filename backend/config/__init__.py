"""配置模块 — 项目配置管理.

Components:
- models: 任务类型、模型注册表
- settings: Pydantic Settings 配置类（lazy — pydantic_settings 较重，仅在
  实际 import backend.config.settings 时加载，不在包初始化时拉入）
- prompts: Agent 提示词 YAML
"""

from typing import Any

from backend.config.models import ModelConfig, ModelProvider, TaskType

__all__ = ["TaskType", "ModelProvider", "ModelConfig", "Settings"]


def __getattr__(name: str) -> Any:
    if name == "Settings":
        from backend.config.settings import Settings

        globals()["Settings"] = Settings
        return Settings
    raise AttributeError(f"module 'backend.config' has no attribute {name!r}")
