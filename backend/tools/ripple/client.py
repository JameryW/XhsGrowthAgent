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
    max_waves: int = 8,
    simulation_horizon: str = "48h",
    ensemble_runs: int = 1,
) -> dict[str, Any]:
    """预测小红书内容传播效果 — 使用 Ripple CAS 引擎模拟内容在平台上的传播路径、互动数据和爆发概率。

    输入内容信息，返回传播预测结果（含置信度）。
    """
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
    """取消 Ripple 模拟任务 — 乐观尝试 DELETE，对不支持取消的服务端做优雅降级。

    适用于模拟超时后清理遗留任务。
    """
    cfg = _get_config()
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.delete(
                f"{cfg['base_url']}/v1/simulations/{job_id}",
                headers=_headers(),
            )

            if resp.status_code in (200, 204):
                return {"cancelled": True, "job_id": job_id, "status": "cancelled"}
            if resp.status_code == 404:
                return {"cancelled": False, "job_id": job_id, "status": "not_found"}
            if resp.status_code == 405:
                return {"cancelled": False, "job_id": job_id, "status": "not_supported"}

            return {
                "cancelled": False,
                "job_id": job_id,
                "status": "error",
                "error": f"HTTP {resp.status_code}",
            }

        except httpx.ConnectError as e:
            return {"cancelled": False, "job_id": job_id, "status": "error", "error": str(e)}

        except Exception as e:
            return {"cancelled": False, "job_id": job_id, "status": "error", "error": str(e)}
