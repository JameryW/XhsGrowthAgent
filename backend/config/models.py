from enum import StrEnum

from pydantic import BaseModel


class TaskType(StrEnum):
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
    BRIEF_ANALYSIS = "brief_analysis"
    SHOOTING_PLAN = "shooting_plan"


class ModelProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"
    XIAOMIMIMO = "xiaomimimo"
    XUNFEI = "xunfei"


class ModelConfig(BaseModel):
    """单个模型配置"""

    provider: ModelProvider
    model_name: str
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 60


# 任务类型特定的超时覆盖（秒）
TASK_TIMEOUT_OVERRIDES: dict[str, int] = {
    # 版本生成需要生成 A/B/C 三个完整版本，耗时较长
    "version_gen": 180,
}


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
    "astron-code-latest": ModelConfig(
        provider=ModelProvider.XUNFEI,
        model_name="astron-code-latest",
        temperature=0.7,
        max_tokens=4096,
    ),
}


def resolve_model_id(task_type: TaskType, routing_overrides: dict[str, str] | None = None) -> str:
    """根据任务类型解析模型 ID，支持用户覆盖"""
    routing = {
        TaskType.ROUTING: "astron-code-latest",
        TaskType.SCOUTING: "astron-code-latest",
        TaskType.STRATEGY: "astron-code-latest",
        TaskType.WRITING: "astron-code-latest",
        TaskType.VISUAL: "astron-code-latest",
        TaskType.ANALYSIS: "astron-code-latest",
        TaskType.PUBLISHING: "astron-code-latest",
        TaskType.ENGAGEMENT: "astron-code-latest",
        # 新增
        TaskType.VIRAL_MATCHING: "astron-code-latest",
        TaskType.CONTENT_ANALYSIS: "astron-code-latest",
        TaskType.VERSION_GEN: "astron-code-latest",
        TaskType.BRIEF_ANALYSIS: "astron-code-latest",
        TaskType.SHOOTING_PLAN: "astron-code-latest",
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


# Approximate cost per 1K tokens (USD) for analytics estimation
MODEL_COST_PER_1K: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "qwen-plus": {"input": 0.0004, "output": 0.0012},
    "mimo-v2.5-pro": {"input": 0.0002, "output": 0.0006},
    "astron-code-latest": {"input": 0.0002, "output": 0.0006},
}


def get_model_id_for_task(task_type: TaskType) -> str:
    """Get the model ID for a given task type."""
    return resolve_model_id(task_type)
