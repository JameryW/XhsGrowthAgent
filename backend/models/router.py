"""Multi-model router — dispatches LLM calls to the right provider."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, cast

from dotenv import load_dotenv
from pydantic import SecretStr

if TYPE_CHECKING:
    # BaseChatModel only appears in annotations. Importing langchain_core
    # .language_models at module load pulls langsmith.run_trees (~0.4s) on
    # every import of backend.models.router (pulled by agents.base). Deferred.
    from langchain_core.language_models import BaseChatModel

from backend.config.models import (
    MODEL_FALLBACKS,
    ModelConfig,
    ModelProvider,
    TaskType,
    resolve_model_id,
)
from backend.harness.runtime import get_policy, is_default_policy, policy_generation
from backend.models.retry import with_fallback, with_retry

# ChatAnthropic / ChatOpenAI are imported lazily inside _create_model (see
# below). Importing them at module load drags in langchain_anthropic +
# langchain_openai (~0.8s of one-time langchain cost) on every import of
# backend.models.router, which is pulled by backend.agents.base — i.e. every
# agent/route import, including test collection. They are only needed when a
# model instance is actually constructed (request time), so deferring them
# keeps the import chain light with no behavior change.

# 加载 .env 文件（确保环境变量可用）
# override=False：不覆盖已设的 os.environ——host 跑 launcher 时 shell export 的
# POSTGRES_URI=localhost 不被 .env 的 postgres-xhs 覆盖（host/容器 URL 区分）。
# 容器内 deploy.sh podman -e 传的值同样保留。.env 仅作未设时的 fallback。
_project_root = Path(__file__).resolve().parent.parent.parent
load_dotenv(_project_root / ".env", override=False)

_PROVIDER_ENV_VARS: dict[ModelProvider, str] = {
    ModelProvider.ANTHROPIC: "ANTHROPIC_API_KEY",
    ModelProvider.OPENAI: "OPENAI_API_KEY",
    ModelProvider.DEEPSEEK: "DEEPSEEK_API_KEY",
    ModelProvider.DASHSCOPE: "DASHSCOPE_API_KEY",
    ModelProvider.XIAOMIMIMO: "XIAOMIMIMO_API_KEY",
    ModelProvider.XUNFEI: "XUNFEI_API_KEY",
    ModelProvider.MAGPIE: "MAGPIE_API_KEY",
}

# magpie 网关地址默认值（容器内 → 宿主机 eth0；宿主机原生跑则覆盖成 127.0.0.1）。
_MAGPIE_DEFAULT_BASE_URL = "http://10.0.0.10:3425/v1"


def _create_model(config: ModelConfig, timeout: int | None = None) -> BaseChatModel:
    """根据 ModelConfig 创建对应的 ChatModel 实例"""
    # Lazy import — see module docstring note above.
    from langchain_anthropic import ChatAnthropic
    from langchain_openai import ChatOpenAI

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
            # 2026-11-02: 禁止直连 DeepSeek API，所有 LLM 统一经 magpie。
            raise ValueError(
                "Direct DeepSeek API is disabled; use ModelProvider.MAGPIE "
                "(opencode-go/deepseek-v4.1-flash) instead."
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
        case ModelProvider.MAGPIE:
            return ChatOpenAI(  # type: ignore[call-arg]
                model=config.model_name,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                timeout=effective_timeout,
                api_key=SecretStr(api_key),
                base_url=os.environ.get("MAGPIE_BASE_URL", _MAGPIE_DEFAULT_BASE_URL),
            )


class ModelRouter:
    """按任务类型路由到不同 LLM"""

    def __init__(self, routing_overrides: dict[str, str] | None = None):
        self._overrides = routing_overrides
        self._cache: dict[str, BaseChatModel] = {}

    def _candidate_model_ids(self, task_type: TaskType) -> list[str]:
        """The model chain for ``task_type``, highest priority first.

        The routed id comes from the router's explicit overrides first (so
        ``ModelRouter({"writing": ...})`` keeps winning), then the active policy.
        ``MODEL_FALLBACKS`` contributes today's single fallback, and a non-default
        policy may append escalation targets.  Ids are deduplicated, order kept;
        unknown ids are deliberately not filtered — ``get_model_config`` raises
        for them, which is the loud behaviour a typo deserves.
        """
        policy = get_policy()
        overrides = self._overrides or {}
        primary_id = overrides.get(task_type.value) or policy.route_model(task_type)
        candidates = [primary_id]
        fallback_id = MODEL_FALLBACKS.get(primary_id)
        if fallback_id:
            candidates.append(fallback_id)
        for target in policy.escalation_targets(task_type):
            if target not in candidates:
                candidates.append(target)
        return candidates

    def get_model(self, task_type: TaskType) -> BaseChatModel:
        """获取任务对应的模型实例（惰性初始化 + 缓存）"""
        from backend.config.models import TASK_TIMEOUT_OVERRIDES, get_model_config

        candidates = self._candidate_model_ids(task_type)
        model_id = candidates[0]
        fallback_id = MODEL_FALLBACKS.get(model_id)
        # Candidate ids are not filtered: a policy typo must fail loudly instead
        # of being silently skipped.  Looking the config up validates the id
        # without building a model, so the fallback itself keeps today's exact
        # lazy construction below.
        for candidate in candidates[1:]:
            if candidate != fallback_id:
                get_model_config(candidate)

        # Use task-specific timeout if configured
        task_timeout = TASK_TIMEOUT_OVERRIDES.get(task_type.value)
        # Cache key includes timeout to avoid reusing wrong timeout, and the
        # policy generation so configure_policy()/reset_policy() can never serve
        # a model built from a superseded routing/escalation decision.
        base_key = f"{model_id}:{task_timeout}" if task_timeout else model_id
        cache_key = f"{base_key}:{policy_generation()}"

        if cache_key not in self._cache:

            def build(index: int) -> BaseChatModel:
                """Model at ``index``, with the rest of the chain nested as fallbacks.

                Every model is ``with_retry``-wrapped and every fallback is built
                lazily (only after the preceding model failed retryably), which
                is exactly today's single-fallback shape for the default policy.
                """
                config = get_model_config(candidates[index])
                model = with_retry(_create_model(config, timeout=task_timeout))
                if index + 1 >= len(candidates):
                    return cast("BaseChatModel", model)
                next_index = index + 1
                next_model: BaseChatModel | None = None

                def create_next() -> BaseChatModel:
                    nonlocal next_model
                    if next_model is None:
                        next_model = build(next_index)
                    return next_model

                return cast(
                    "BaseChatModel",
                    with_fallback(
                        model,
                        create_next,
                        primary_model_id=candidates[index],
                        fallback_model_id=candidates[next_index],
                    ),
                )

            self._cache[cache_key] = build(0)
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


_PROVIDER_MODULES: dict[ModelProvider, str] = {
    ModelProvider.ANTHROPIC: "langchain_anthropic",
    ModelProvider.OPENAI: "langchain_openai",
    ModelProvider.DASHSCOPE: "langchain_openai",
    ModelProvider.XIAOMIMIMO: "langchain_openai",
    ModelProvider.XUNFEI: "langchain_openai",
    ModelProvider.MAGPIE: "langchain_openai",
}


def _providers_in_use() -> set[ModelProvider]:
    """Providers referenced by the current routing table (primary + fallbacks)."""
    from backend.config.models import get_model_config

    providers: set[ModelProvider] = set()
    for task in TaskType:
        try:
            providers.add(get_model_config(resolve_model_id(task, None)).provider)
        except Exception:
            continue
    for fallback_id in MODEL_FALLBACKS.values():
        try:
            providers.add(get_model_config(fallback_id).provider)
        except Exception:
            continue
    # A policy may escalate to a stronger model, so its SDK must be importable
    # before a run starts.  Best-effort like the rest of this function: preload
    # is an optimization and must never break boot.
    if not is_default_policy(get_policy()):
        policy = get_policy()
        for task in TaskType:
            try:
                for target in policy.escalation_targets(task):
                    providers.add(get_model_config(target).provider)
            except Exception:
                continue
    return providers


def preload_model_providers() -> None:
    """Import the provider SDKs needed by the current routing table.

    ``_create_model`` imports ``langchain_anthropic``/``langchain_openai`` lazily.
    The first import can spend seconds in import machinery (on Windows the openai
    chain pulls transformers/torch: ~20s cold); when it happens inside an async
    graph node it blocks the whole event loop, so API requests and checkpoint
    writes stall behind it.  Importing at startup fixes that, but *awaiting* it
    would make every boot pay the full cost, so callers use
    :func:`start_model_provider_preload` (daemon thread) instead.

    Only provider modules referenced by the routing table are imported (default
    routing is all-magpie → ``langchain_openai`` only).  Idempotent
    (``sys.modules`` caches).
    """
    modules = {
        _PROVIDER_MODULES[provider]
        for provider in _providers_in_use()
        if provider in _PROVIDER_MODULES
    }
    for module in sorted(modules):
        __import__(module)


def _preload_model_providers_safely() -> None:
    try:
        preload_model_providers()
    except Exception as exc:  # pragma: no cover - defensive: preload must never break boot
        logging.getLogger("xhs_growth.models").warning(
            "model provider preload failed: %s: %s", type(exc).__name__, exc
        )


def start_model_provider_preload() -> threading.Thread:
    """Warm the provider SDK imports in a daemon thread (non-blocking startup).

    A daemon thread (not ``asyncio.to_thread``) so interpreter shutdown never
    waits for a slow import.  If a workflow starts before the import finishes,
    the first ``_create_model`` waits on the import lock for the remainder — one
    bounded stall instead of every boot paying ~20s of startup.
    """
    thread = threading.Thread(
        target=_preload_model_providers_safely,
        name="model-provider-preload",
        daemon=True,
    )
    thread.start()
    return thread


def get_model_by_id(model_id: str) -> BaseChatModel:
    """按注册表 id 直接取模型实例（不经任务路由）。

    给「同一个任务里需要换上游」的窄场景用（例：扫描件 PDF 的文字提取需要能吃
    ``application/pdf`` 的模型，而默认主模型只收图片）。
    """
    from backend.config.models import get_model_config

    return cast(BaseChatModel, with_retry(_create_model(get_model_config(model_id))))
