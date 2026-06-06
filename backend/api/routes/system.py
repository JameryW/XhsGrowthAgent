"""System health check routes."""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter

from backend.api.responses import success

router = APIRouter()


def _check_env_var(name: str) -> dict:
    """Check if an environment variable is set."""
    value = os.environ.get(name)
    if value:
        masked = value[:4] + "..." + value[-4:] if len(value) > 12 else "***"
        return {"status": "ok", "configured": True, "preview": masked}
    return {"status": "missing", "configured": False, "preview": None}


def _check_llm_providers() -> dict:
    """Check LLM provider API key availability."""
    providers = {
        "anthropic": _check_env_var("ANTHROPIC_API_KEY"),
        "openai": _check_env_var("OPENAI_API_KEY"),
        "deepseek": _check_env_var("DEEPSEEK_API_KEY"),
        "dashscope": _check_env_var("DASHSCOPE_API_KEY"),
        "xiaomimimo": _check_env_var("XIAOMIMIMO_API_KEY"),
    }
    any_configured = any(p["configured"] for p in providers.values())
    return {
        "status": "ok" if any_configured else "warning",
        "message": "至少一个 LLM Provider 已配置" if any_configured else "未配置任何 LLM Provider",
        "providers": providers,
    }


def _check_xhs() -> dict:
    """Check XHS platform credentials."""
    cookie = os.environ.get("XHS_COOKIE")
    user_id = os.environ.get("XHS_USER_ID")
    configured = bool(cookie and user_id)
    return {
        "status": "ok" if configured else "warning",
        "configured": configured,
        "cookie_set": bool(cookie),
        "user_id_set": bool(user_id),
        "message": "小红书凭证已配置" if configured else "缺少 XHS_COOKIE 或 XHS_USER_ID",
    }


async def _check_ripple() -> dict:
    """Check Ripple CAS engine availability and LLM config."""
    base_url = os.environ.get("RIPPLE_BASE_URL")
    api_token = os.environ.get("RIPPLE_API_TOKEN")
    enabled = os.environ.get("RIPPLE_ENABLED", "false").lower() == "true"

    if not enabled:
        return {
            "status": "disabled",
            "configured": False,
            "message": "Ripple 服务未启用",
            "reason": "disabled",
        }

    if not base_url:
        return {
            "status": "warning",
            "configured": False,
            "message": "Ripple CAS 未配置（可选）",
            "reason": "unconfigured",
        }

    headers = {"Accept": "application/json"}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"

    try:
        async with httpx.AsyncClient(timeout=5.0, headers=headers) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/healthz")
        if resp.status_code != 200:
            return {
                "status": "warning",
                "configured": True,
                "message": f"Ripple CAS 健康检查失败：HTTP {resp.status_code}",
                "reason": "unreachable",
            }
    except httpx.HTTPError as exc:
        return {
            "status": "warning",
            "configured": True,
            "message": f"Ripple CAS 不可达：{exc}",
            "reason": "unreachable",
        }

    # Healthz is OK — verify LLM config so simulations won't fail with "missing model_name"
    llm_platform = os.environ.get("RIPPLE_LLM_MODEL_PLATFORM", "")
    llm_name = os.environ.get("RIPPLE_LLM_MODEL_NAME", "")
    llm_key = os.environ.get("RIPPLE_LLM_API_KEY", "")
    llm_configured = bool(llm_platform and llm_name and llm_key)

    if llm_configured:
        return {
            "status": "ok",
            "configured": True,
            "message": "Ripple CAS 可用，LLM 配置完整",
            "reason": "ok",
            "llm_config": {"platform": llm_platform, "model": llm_name},
        }
    return {
        "status": "warning",
        "configured": True,
        "message": "Ripple CAS 可用但缺少 LLM 配置（模拟将失败）",
        "reason": "llm_missing",
        "llm_config": {"platform": llm_platform, "model": llm_name},
    }


def _check_search() -> dict:
    """Check search API availability (Tavily)."""
    tavily = os.environ.get("TAVILY_API_KEY")
    configured = bool(tavily)
    return {
        "status": "ok" if configured else "warning",
        "configured": configured,
        "message": "搜索 API 已配置" if configured else "缺少 TAVILY_API_KEY（趋势发现将使用 LLM 生成数据）",
    }


@router.get("/health")
async def system_health():
    """系统健康检查

    检查所有外部依赖的可用性：
    - LLM Provider API keys
    - XHS 平台凭证
    - Ripple CAS 引擎
    - 数据库/存储
    - 搜索 API (Tavily)
    """
    llm = _check_llm_providers()
    xhs = _check_xhs()
    ripple = await _check_ripple()
    search = _check_search()

    # Overall status: ok if LLM is configured (XHS is optional — preview-only without it)
    overall = "ok" if llm["status"] == "ok" else "degraded"

    # Detect checkpointer mode from app state
    try:
        from backend.api.app import app as fastapi_app

        cp = getattr(fastapi_app.state, "checkpointer", None)
        if cp is not None:
            cp_type = type(cp).__name__
            if "Postgres" in cp_type:
                database_check = {
                    "status": "ok",
                    "mode": "postgres",
                    "message": f"Postgres 检查点（{cp_type}）",
                }
            else:
                database_check = {
                    "status": "ok",
                    "mode": cp_type,
                    "message": f"检查点：{cp_type}",
                }
        else:
            database_check = {
                "status": "ok",
                "mode": "memory",
                "message": "开发模式（内存检查点）",
            }
    except Exception:
        database_check = {
            "status": "ok",
            "mode": "unknown",
            "message": "无法检测检查点模式",
        }

    checks = {
        "llm_providers": llm,
        "xhs_platform": xhs,
        "ripple_cas": ripple,
        "search_api": search,
        "database": database_check,
    }

    return success(
        data={
            "status": overall,
            "checks": checks,
            "version": "0.1.0",
            "timestamp": datetime.now(UTC).isoformat(),
        }
    )
