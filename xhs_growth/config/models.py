from enum import Enum
from typing import Any

from pydantic import BaseModel


class TaskType(str, Enum):
    """任务类型 → 模型路由键"""

    ROUTING = "routing"
    SCOUTING = "scouting"
    STRATEGY = "strategy"
    WRITING = "writing"
    VISUAL = "visual"
    ANALYSIS = "analysis"
    PUBLISHING = "publishing"
    ENGAGEMENT = "engagement"


class ModelProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"


class ModelConfig(BaseModel):
    """单个模型配置"""

    provider: ModelProvider
    model_name: str
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60


# 模型注册表 — model_id → ModelConfig
MODEL_REGISTRY: dict[str, ModelConfig] = {
    "claude-sonnet-4-20250514": ModelConfig(
        provider=ModelProvider.ANTHROPIC,
        model_name="claude-sonnet-4-20250514",
        temperature=0.7,
        max_tokens=4096,
    ),
    "gpt-4o": ModelConfig(
        provider=ModelProvider.OPENAI,
        model_name="gpt-4o",
        temperature=0.5,
        max_tokens=4096,
    ),
    "deepseek-chat": ModelConfig(
        provider=ModelProvider.DEEPSEEK,
        model_name="deepseek-chat",
        temperature=0.6,
        max_tokens=4096,
    ),
    "qwen-plus": ModelConfig(
        provider=ModelProvider.DASHSCOPE,
        model_name="qwen-plus",
        temperature=0.5,
        max_tokens=4096,
    ),
}


def resolve_model_id(task_type: TaskType, routing_overrides: dict[str, str] | None = None) -> str:
    """根据任务类型解析模型 ID，支持用户覆盖"""
    routing = {
        TaskType.ROUTING: "deepseek-chat",
        TaskType.SCOUTING: "deepseek-chat",
        TaskType.STRATEGY: "claude-sonnet-4-20250514",
        TaskType.WRITING: "claude-sonnet-4-20250514",
        TaskType.VISUAL: "gpt-4o",
        TaskType.ANALYSIS: "gpt-4o",
        TaskType.PUBLISHING: "qwen-plus",
        TaskType.ENGAGEMENT: "deepseek-chat",
    }
    if routing_overrides:
        for k, v in routing_overrides.items():
            routing[TaskType(k)] = v
    return routing[task_type]


def get_model_config(model_id: str) -> ModelConfig:
    """获取模型配置，不存在则抛出 KeyError"""
    if model_id not in MODEL_REGISTRY:
        raise KeyError(f"Unknown model: {model_id}. Available: {list(MODEL_REGISTRY.keys())}")
    return MODEL_REGISTRY[model_id]
