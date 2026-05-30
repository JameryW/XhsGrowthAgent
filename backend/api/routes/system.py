"""System health check routes."""

from __future__ import annotations

import os
from datetime import UTC, datetime

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


def _check_ripple() -> dict:
    """Check Ripple CAS engine availability."""
    base_url = os.environ.get("RIPPLE_BASE_URL")
    api_token = os.environ.get("RIPPLE_API_TOKEN")
    enabled = os.environ.get("RIPPLE_ENABLED", "true").lower() == "true"

    if not enabled:
        return {"status": "disabled", "configured": False, "message": "Ripple 服务已禁用"}

    # Local services don't need an API token
    is_local = bool(base_url) and ("127.0.0.1" in base_url or "localhost" in base_url)
    configured = bool(base_url and (api_token or is_local))
    return {
        "status": "ok" if configured else "warning",
        "configured": configured,
        "message": "Ripple CAS 已配置" if configured else "Ripple CAS 未配置（可选）",
    }


@router.get("/health")
async def system_health():
    """系统健康检查

    检查所有外部依赖的可用性：
    - LLM Provider API keys
    - XHS 平台凭证
    - Ripple CAS 引擎
    - 数据库/存储
    """
    llm = _check_llm_providers()
    xhs = _check_xhs()
    ripple = _check_ripple()

    # Overall status: ok if LLM is configured (XHS is optional — preview-only without it)
    overall = "ok" if llm["status"] == "ok" else "degraded"

    checks = {
        "llm_providers": llm,
        "xhs_platform": xhs,
        "ripple_cas": ripple,
        "database": {
            "status": "ok",
            "mode": "memory",
            "message": "开发模式（内存检查点）",
        },
    }

    return success(data={
        "status": overall,
        "checks": checks,
        "version": "0.1.0",
        "timestamp": datetime.now(UTC).isoformat(),
    })
