"""配置模块 — 项目配置管理.

Components:
- models: 任务类型、模型注册表
- settings: Pydantic Settings 配置类
- prompts: Agent 提示词 YAML
"""

from xhs_growth.config.models import TaskType, ModelProvider, ModelConfig
from xhs_growth.config.settings import Settings

__all__ = ["TaskType", "ModelProvider", "ModelConfig", "Settings"]