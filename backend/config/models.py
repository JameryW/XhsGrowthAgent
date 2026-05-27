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
    # 新增
    VIRAL_MATCHING = "viral_matching"
    CONTENT_ANALYSIS = "content_analysis"
    VERSION_GEN = "version_gen"


class ModelProvider(str, Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"
    XIAOMIMIMO = "xiaomimimo"


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
    "mimo-v2.5-pro": ModelConfig(
        provider=ModelProvider.XIAOMIMIMO,
        model_name="mimo-v2.5-pro",
        temperature=0.7,
        max_tokens=4096,
    ),
}


def resolve_model_id(task_type: TaskType, routing_overrides: dict[str, str] | None = None) -> str:
    """根据任务类型解析模型 ID，支持用户覆盖"""
    routing = {
        TaskType.ROUTING: "mimo-v2.5-pro",
        TaskType.SCOUTING: "mimo-v2.5-pro",
        TaskType.STRATEGY: "mimo-v2.5-pro",
        TaskType.WRITING: "mimo-v2.5-pro",
        TaskType.VISUAL: "mimo-v2.5-pro",
        TaskType.ANALYSIS: "mimo-v2.5-pro",
        TaskType.PUBLISHING: "mimo-v2.5-pro",
        TaskType.ENGAGEMENT: "mimo-v2.5-pro",
        # 新增
        TaskType.VIRAL_MATCHING: "mimo-v2.5-pro",
        TaskType.CONTENT_ANALYSIS: "mimo-v2.5-pro",
        TaskType.VERSION_GEN: "mimo-v2.5-pro",
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
