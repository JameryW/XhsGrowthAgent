"""Ripple MCP client — wraps Ripple HTTP API as LangChain tools for XHS Growth Agent."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from langchain_core.tools import tool

logger = logging.getLogger("xhs_growth.tools.ripple")


def _get_config() -> dict[str, Any]:
    """从 Settings 读取 Ripple 配置"""
    from backend.config.settings import Settings

    s = Settings()
    return {
        "base_url": s.ripple.base_url,
        "api_token": s.ripple.api_token,
        "timeout": s.ripple.request_timeout,
        "enabled": s.ripple.enabled,
    }


def _llm_config() -> dict[str, Any] | None:
    """构建 Ripple 引擎需要的 llm_config，自动从环境变量解析可用的 API key 和 URL"""
    import os

    from backend.config.settings import Settings

    s = Settings()
    model = s.ripple.llm_model
    url = s.ripple.llm_url
    api_key = s.ripple.llm_api_key

    # Auto-resolve from model provider if not explicitly set
    if not api_key or not url:
        from backend.config.models import _PROVIDER_ENV_VARS, MODEL_REGISTRY
        from backend.models.router import ModelProvider

        cfg = MODEL_REGISTRY.get(model)
        if cfg:
            env_var = _PROVIDER_ENV_VARS.get(cfg.provider)
            if env_var and not api_key:
                api_key = os.environ.get(env_var, "")
            if not url:
                # Resolve base_url per provider
                provider_urls = {
                    ModelProvider.DEEPSEEK: "https://api.deepseek.com",
                    ModelProvider.OPENAI: "https://api.openai.com/v1",
                    ModelProvider.DASHSCOPE: "https://dashscope.aliyuncs.com/compatible-mode/v1",
                    ModelProvider.XIAOMIMIMO: os.environ.get(
                        "XIAOMIMIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"
                    ),
                    ModelProvider.XUNFEI: os.environ.get(
                        "XUNFEI_BASE_URL", "https://maas-coding-api.cn-huabei-1.xf-yun.com/v2"
                    ),
                }
                url = provider_urls.get(cfg.provider, "")

    if not api_key or not url:
        return None

    role_config = {
        "model_name": model,
        "url": url,
        "api_key": api_key,
        "max_tokens": 16384,
        "json_mode": True,
    }
    return {
        "omniscient": role_config,
        "dynamics": role_config,
        "star": role_config,
        "sea": role_config,
    }


def _headers() -> dict[str, str]:
    config = _get_config()
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if config["api_token"]:
        h["Authorization"] = f"Bearer {config['api_token']}"
    return h


# ── 创建模拟 ──


@tool
async def ripple_predict_content_spread(
    topic: str,
    content_type: str = "图文笔记",
    tags: list[str] | None = None,
    tone: str = "真诚种草",
    description: str = "",
    platform: str = "xiaohongshu",
    max_waves: int = 0,
    simulation_horizon: str = "",
    ensemble_runs: int = 0,
) -> dict[str, Any]:
    """预测小红书内容传播效果 — 使用 Ripple CAS 引擎模拟内容在平台上的传播路径、互动数据和爆发概率。

    输入内容信息，返回传播预测结果（含置信度）。
    """
    # ponytail: read from env (set by system_config UI) with sensible defaults
    import os

    if max_waves <= 0:
        max_waves = int(os.environ.get("RIPPLE_MAX_WAVES", "4"))
    if not simulation_horizon:
        simulation_horizon = os.environ.get("RIPPLE_SIMULATION_HORIZON", "48h")
    if ensemble_runs <= 0:
        ensemble_runs = int(os.environ.get("RIPPLE_ENSEMBLE_RUNS", "1"))
    if tags is None:
        tags = []
    cfg = _get_config()
    event = {
        "topic": topic,
        "content_type": content_type,
        "tags": tags,
        "tone": tone,
        "description": description,
    }
    request_body = {
        "skill": "social-media",
        "platform": platform,
        "event": event,
        "max_waves": max_waves,
        "simulation_horizon": simulation_horizon,
        "ensemble_runs": ensemble_runs,
    }
    llm = _llm_config()
    if llm:
        request_body["llm_config"] = llm
    async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
        resp = await client.post(
            f"{cfg['base_url']}/v1/simulations",
            headers=_headers(),
            json=request_body,
        )
        resp.raise_for_status()
        return resp.json()


@tool
async def ripple_validate_pmf(
    product_name: str,
    category: str,
    description: str,
    differentiators: list[str] | None = None,
    competitive_landscape: str = "",
    channel: str = "content-seeding",
    vertical: str = "fmcg",
    platform: str = "xiaohongshu",
    simulation_horizon: str = "72h",
) -> dict[str, Any]:
    """验证产品在小红书渠道的市场契合度(PMF) — 使用 Ripple CAS 引擎模拟目标消费者群体的真实反应。

    输入产品信息，返回 PMF 评分、风险诊断和改进策略。
    """
    if differentiators is None:
        differentiators = []
    cfg = _get_config()
    event = {
        "name": product_name,
        "category": category,
        "description": description,
        "differentiators": differentiators,
        "competitive_landscape": competitive_landscape,
    }
    request_body = {
        "skill": "pmf-validation",
        "channel": channel,
        "vertical": vertical,
        "platform": platform,
        "event": event,
        "simulation_horizon": simulation_horizon,
    }
    llm = _llm_config()
    if llm:
        request_body["llm_config"] = llm
    async with httpx.AsyncClient(timeout=cfg["timeout"]) as client:
        resp = await client.post(
            f"{cfg['base_url']}/v1/simulations",
            headers=_headers(),
            json=request_body,
        )
        resp.raise_for_status()
        return resp.json()


# ── 查询模拟 ──


@tool
async def ripple_get_simulation_status(job_id: str) -> dict[str, Any]:
    """获取 Ripple 模拟任务的状态和进度"""
    cfg = _get_config()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{cfg['base_url']}/v1/simulations/{job_id}",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


@tool
async def ripple_get_simulation_result(job_id: str) -> dict[str, Any]:
    """获取 Ripple 模拟任务的完整输出 JSON — 包含传播预测数据、互动指标和相态分析"""
    cfg = _get_config()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{cfg['base_url']}/v1/simulations/{job_id}/artifacts/output-json",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


@tool
async def ripple_get_simulation_log(job_id: str) -> str:
    """获取 Ripple 模拟任务的紧凑日志 — 每轮 Wave 的关键事件摘要"""
    cfg = _get_config()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{cfg['base_url']}/v1/simulations/{job_id}/artifacts/compact-log",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.text


@tool
async def ripple_generate_report(
    job_id: str,
    rounds: list[str] | None = None,
    role: str = "omniscient",
) -> dict[str, Any]:
    """为已完成的 Ripple 模拟任务生成结构化报告 — 包含传播预测总结、动力学诊断和优化建议"""
    if rounds is None:
        rounds = ["summary", "diagnosis"]
    cfg = _get_config()
    payload = {
        "rounds": [{"label": r, "system_prompt": "", "extra_user_context": ""} for r in rounds],
        "role": role,
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{cfg['base_url']}/v1/simulations/{job_id}/report",
            headers=_headers(),
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()


# ── 取消模拟 ──


@tool
async def ripple_cancel_simulation(job_id: str) -> dict[str, Any]:
    """取消 Ripple 模拟任务 — 使用两步取消协议，并对旧服务回退 DELETE。

    适用于模拟超时后清理遗留任务。
    """
    try:
        from backend.services.ripple_service import RippleService

        service = RippleService.get_instance()
        return await service.cancel_simulation(job_id)
    except Exception as e:
        return {"cancelled": False, "job_id": job_id, "status": "error", "error": str(e)}
