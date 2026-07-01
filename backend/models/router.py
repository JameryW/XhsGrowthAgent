"""Multi-model router — dispatches LLM calls to the right provider."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from backend.config.models import ModelConfig, ModelProvider, TaskType, resolve_model_id
from backend.models.retry import with_retry

# 加载 .env 文件（确保环境变量可用）
_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env", override=True)

_PROVIDER_ENV_VARS: dict[ModelProvider, str] = {
    ModelProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
    ModelProvider.OPENAI: "OPENAI_API_KEY",
    ModelProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
    ModelProvider.DASHSCOPE: "DASHSCOPE_API_KEY",
    ModelProvider.XIAOMIMIMO: "XIAOMIMIMO_API_KEY",
    ModelProvider.XUNFEI: "XUNFEI_API_KEY",
}


def _create_model(config: ModelConfig, timeout: int | None = None) -> BaseChatModel:
    """根据 ModelConfig 创建对应的 ChatModel 实例"""
    env_var = _PROVIDER_ENV_VARS.get(config.provider)
    api_key = os.environ.get(env_var, "") if env_var else ""
    if not api_key:
        raise ValueError(
            f"Missing API key for {config.provider.value} provider (model: {config.model_name}). "
            f"Set the {env_var} environment variable or add it to your .env file."
        )

    effective_timeout = timeout or config.timeout

    match config.provider:
        case ModelProvider.ANTHROPIC:
            return ChatAnthropic(  # type: ignore[call-arg]
                model=config.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=effective_timeout,
                api_key=SecretStr(api_key),
            )
        case ModelProvider.OPENAI:
            return ChatOpenAI(  # type: ignore[call-arg]
                model=config.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=effective_timeout,
                api_key=SecretStr(api_key),
            )
        case ModelProvider.DEEPSEEK:
            return ChatOpenAI(  # type: ignore[call-arg]
                model=config.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=effective_timeout,
                api_key=SecretStr(api_key),
                base_url="https://api.deepseek.com",
            )
        case ModelProvider.DASHSCOPE:
            return ChatOpenAI(  # type: ignore[call-arg]
                model=config.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=effective_timeout,
                api_key=SecretStr(api_key),
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            )
        case ModelProvider.XIAOMIMIMO:
            return ChatOpenAI(  # type: ignore[call-arg]
                model=config.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=effective_timeout,
                api_key=SecretStr(api_key),
                base_url=os.environ.get(
                    "XIAOMIMIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"
                ),
            )
        case ModelProvider.XUNFEI:
            return ChatOpenAI(  # type: ignore[call-arg]
                model=config.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=effective_timeout,
                api_key=SecretStr(api_key),
                base_url=os.environ.get(
                    "XUNFEI_BASE_URL", "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"
                ),
            )


class ModelRouter:
    """按任务类型路由到不同 LLM"""

    def __init__(self, routing_overrides: dict[str, str] | None = None):
        self._overrides = routing_overrides
        self._cache: dict[str, BaseChatModel] = {}

    def get_model(self, task_type: TaskType) -> BaseChatModel:
        """获取任务对应的模型实例（惰性初始化 + 缓存）"""
        from backend.config.models import TASK_TIMEOUT_OVERRIDES, get_model_config

        model_id = resolve_model_id(task_type, self._overrides)

        # Use task-specific timeout if configured
        task_timeout = TASK_TIMEOUT_OVERRIDES.get(task_type.value)
        # Cache key includes timeout to avoid reusing wrong timeout
        cache_key = f"{model_id}:{task_timeout}" if task_timeout else model_id

        if cache_key not in self._cache:
            config = get_model_config(model_id)
            self._cache[cache_key] = with_retry(_create_model(config, timeout=task_timeout))
        return self._cache[cache_key]

    def get_model_for_task(self, task: str) -> BaseChatModel:
        """字符串任务名 → 模型"""
        return self.get_model(TaskType(task))


# 全局单例
_router: ModelRouter | None = None


def get_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


def get_model(task: str) -> BaseChatModel:
    """快捷方式：按任务名获取模型"""
    return get_router().get_model_for_task(task)
