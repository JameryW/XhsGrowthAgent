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
    # Legacy routing key retained for persisted configuration compatibility;
    # the automatic workflow agent has been removed.
    ENGAGEMENT = "engagement"
    # 新增
    VIRAL_MATCHING = "viral_matching"
    CONTENT_ANALYSIS = "content_analysis"
    VERSION_GEN = "version_gen"
    BRIEF_ANALYSIS = "brief_analysis"
    SHOOTING_PLAN = "shooting_plan"
    EVALUATION = "evaluation"  # 创作质量评估 (RQGM agent-as-a-judge 面板)
    POLISH = "polish"  # de_ai_taste 去套话润色：窄转换，降级到更轻/便宜的模型
    # blogger_scout 虚构 mock_ 博主候选，纯结构化生成，降级轻模型 (不动 trend_scout)
    MOCK_GEN = "mock_gen"


class ModelProvider(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    DASHSCOPE = "dashscope"
    XIAOMIMIMO = "xiaomimimo"
    XUNFEI = "xunfei"
    # 本机 magpie 路由网关（OpenAI 兼容，base_url = MAGPIE_BASE_URL）。
    # 所有 LLM 调用统一从这里出，具体落到哪个上游由 magpie 决定。
    MAGPIE = "magpie"


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
    # Xunfei provider 响应较慢，内容分析/简报分析需要更长超时
    "content_analysis": 120,
    "brief_analysis": 120,
    "shooting_plan": 120,
    "evaluation": 120,  # 9 维 judge 面板单次调用，多维评分需较长超时
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
    "mimo-v2.6-flash": ModelConfig(
        provider=ModelProvider.XIAOMIMIMO,
        model_name="mimo-v2.6-flash",
        temperature=0.7,
        max_tokens=4096,
    ),
    "astron-code-latest": ModelConfig(
        provider=ModelProvider.XUNFEI,
        model_name="astron-code-latest",
        temperature=0.7,
        max_tokens=4096,
        timeout=90,
    ),
    # magpie 路由 → OpenCode Go / DeepSeek V4.1 Flash。模型名必须带 provider 前缀，
    # magpie 用 `opencode-go/deepseek-v4.1-flash` 这种 ref 选上游。
    "magpie-deepseek-v4.1-flash": ModelConfig(
        provider=ModelProvider.MAGPIE,
        model_name="opencode-go/deepseek-v4.1-flash",
        temperature=0.7,
        max_tokens=4096,
    ),
    # 扫描件 PDF 的文字提取兜底：V4.1 Flash 只收图片，不收 application/pdf，
    # 这里换成能吃 PDF 的 haiku 5.5（仍经 magpie）。只在 pdfplumber 提不出文字时用。
    "magpie-pdf-ocr": ModelConfig(
        provider=ModelProvider.MAGPIE,
        model_name="opencode-go/claude-haiku-5-5",
        temperature=0.2,
        max_tokens=8192,
        timeout=180,
    ),
}

# 所有任务的默认模型（全部经 magpie 出网）。
MAGPIE_MODEL_ID = "magpie-deepseek-v4.1-flash"

# Primary model → backup model, applied only by ModelRouter after primary retries.
MODEL_FALLBACKS: dict[str, str] = {
    "mimo-v2.6-flash": "magpie-deepseek-v4.1-flash",
}


def resolve_model_id(task_type: TaskType, routing_overrides: dict[str, str] | None = None) -> str:
    """根据任务类型解析模型 ID，支持用户覆盖

    默认全部任务走 magpie 网关的 DeepSeek V4.1 Flash（上游 fallback 由 magpie 自己管），
    不再按任务分厂商——需要分流时用 routing_overrides 覆盖即可。
    """
    routing = {task: MAGPIE_MODEL_ID for task in TaskType}
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
    # magpie 路由的两个条目：OpenCode Go 是套餐额度，不按 token 计费 → 0（避免分析页
    # 用默认费率虚报成本）。真实开销看 magpie 的 usage 日志。
    "magpie-deepseek-v4.1-flash": {"input": 0.0, "output": 0.0},
    "magpie-pdf-ocr": {"input": 0.0, "output": 0.0},
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "deepseek-v4-flash": {"input": 0.00014, "output": 0.00028},
    "qwen-plus": {"input": 0.0004, "output": 0.0012},
    "mimo-v2.5-pro": {"input": 0.0002, "output": 0.0006},
    "astron-code-latest": {"input": 0.0002, "output": 0.0006},
}


def get_model_id_for_task(task_type: TaskType) -> str:
    """Get the model ID for a given task type."""
    return resolve_model_id(task_type)
