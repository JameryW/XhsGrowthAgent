"""System health check routes."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter

from backend.api.responses import ApiResponse, success

logger = logging.getLogger("xhs_growth.api.system")

router = APIRouter()


def _check_env_var(name: str) -> dict[str, Any]:
    """Check if an environment variable is set."""
    value = os.environ.get(name)
    if value:
        masked = value[:4] + "..." + value[-4:] if len(value) > 12 else "***"
        return {"status": "ok", "configured": True, "preview": masked}
    return {"status": "missing", "configured": False, "preview": None}


def _check_llm_providers() -> dict[str, Any]:
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


async def _check_xhs() -> dict[str, Any]:
    """Check XHS platform credentials.

    Credentials are account-scoped DB data now (see backend.db.accounts); the
    env-backed XHS_COOKIE/XHS_USER_ID is the legacy fallback. ok when either
    source yields a usable cookie+user_id pair.
    """
    cookie, user_id = await _resolve_xhs_credentials()
    configured = bool(cookie and user_id)
    use_browser = os.environ.get("XHS_USE_BROWSER", "").lower() == "true"
    message = (
        "小红书凭证已配置" if configured else "缺少账号凭证（DB 账号或 XHS_COOKIE/XHS_USER_ID）"
    )
    return {
        "status": "ok" if configured else "warning",
        "configured": configured,
        "cookie_set": bool(cookie),
        "user_id_set": bool(user_id),
        # Exposed so the review approve modal can warn that real publishing
        # is impossible when use_browser is off (publisher.py mocks in that case).
        "use_browser": use_browser,
        "message": message,
    }


async def _resolve_xhs_credentials() -> tuple[str, str]:
    """Resolve XHS credentials: DB active account first, env fallback.

    ponytail: mirrors tools/xhs/trending._resolve_db_credentials but health-only
    — returns masked presence, never the raw value.
    """
    try:
        from backend.db.pool import is_pool_ready

        if is_pool_ready():
            from backend.db.accounts import get_account_cookie, get_active_account

            active = await get_active_account()
            if active is not None:
                cookie, user_id = await get_account_cookie(active.id)
                if cookie:
                    return cookie, user_id
    except Exception as exc:  # noqa: BLE001 — health check must never crash
        logger.warning("DB XHS credential lookup failed, falling back to env: %s", exc)

    cookie = os.environ.get("XHS_COOKIE", "")
    user_id = os.environ.get("XHS_USER_ID", "")
    return cookie, user_id


async def _check_ripple() -> dict[str, Any]:
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


def _check_search() -> dict[str, Any]:
    """Check search API availability (Tavily)."""
    tavily = os.environ.get("TAVILY_API_KEY")
    configured = bool(tavily)
    return {
        "status": "ok" if configured else "warning",
        "configured": configured,
        "message": "搜索 API 已配置"
        if configured
        else "缺少 TAVILY_API_KEY（趋势发现将使用 LLM 生成数据）",
    }


async def _check_memory_store() -> dict[str, Any]:
    """Check memory store status: backend type, semantic index, namespace counts."""
    from backend.memory.index import get_store_index

    store = None
    try:
        from backend.api.app import app as fastapi_app

        graph = getattr(fastapi_app.state, "graph", None)
        if graph is not None:
            store = getattr(graph, "store", None)
    except Exception:
        pass

    # Determine store backend
    if store is not None:
        store_type = type(store).__name__
        if "Postgres" in store_type:
            backend = "postgres"
        elif "InMemory" in store_type:
            backend = "memory"
        else:
            backend = store_type
    else:
        backend = "unavailable"

    # Check semantic index availability
    index_config = get_store_index()
    semantic_enabled = index_config is not None
    embed_model = ""
    embed_dims = 0
    if index_config:
        # embed field is an Embeddings object (not serializable) — report the
        # configured model string from env instead, for the health payload.
        embed_model = os.environ.get("XHS_EMBED_MODEL", "")
        embed_dims = index_config.get("dims", 0)

    # Count items per namespace (best-effort)
    namespace_counts: dict[str, int] = {}
    total_items = 0
    if store is not None:
        try:
            # List all namespaces and count items
            # InMemoryStore and AsyncPostgresStore both support alist with namespace prefix
            known_prefixes = [
                ("accounts",),  # All account-scoped data
                ("benchmarks",),  # Niche benchmarks
            ]
            for prefix in known_prefixes:
                try:
                    items = await store.alist(namespace_prefix=prefix, limit=1000)
                    for item in items:
                        ns_key = "/".join(str(p) for p in item.namespace)
                        namespace_counts[ns_key] = namespace_counts.get(ns_key, 0) + 1
                        total_items += 1
                except Exception:
                    pass
        except Exception:
            pass

    # Build status
    if backend == "unavailable":
        status = "warning"
        message = "Memory store 不可用"
    elif not semantic_enabled:
        status = "degraded"
        message = f"Memory store 可用（{backend}），语义索引未启用"
    else:
        status = "ok"
        message = f"Memory store 可用（{backend}），语义索引已启用"

    result: dict[str, Any] = {
        "status": status,
        "backend": backend,
        "semantic_index": semantic_enabled,
        "message": message,
    }
    if semantic_enabled:
        result["embed_model"] = embed_model
        result["embed_dims"] = embed_dims
    if namespace_counts:
        result["namespace_counts"] = namespace_counts
        result["total_items"] = total_items

    return result


@router.get("/health")
async def system_health() -> ApiResponse[Any]:
    """系统健康检查

    检查所有外部依赖的可用性：
    - LLM Provider API keys
    - XHS 平台凭证
    - Ripple CAS 引擎
    - 数据库/存储
    - 搜索 API (Tavily)
    """
    llm = _check_llm_providers()
    xhs = await _check_xhs()
    ripple = await _check_ripple()
    search = _check_search()
    memory = await _check_memory_store()

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
            elif "Sqlite" in cp_type or "SQLite" in cp_type:
                database_check = {
                    "status": "ok",
                    "mode": "sqlite",
                    "message": f"SQLite 持久化检查点（{cp_type}）",
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

    # Active account info (from DB-managed accounts, if available)
    active_account = None
    try:
        from backend.db.accounts import get_active_account

        acc = await get_active_account()
        if acc:
            active_account = {"id": acc.id, "name": acc.name}
    except Exception:
        pass

    checks = {
        "llm_providers": llm,
        "xhs_platform": xhs,
        "ripple_cas": ripple,
        "search_api": search,
        "database": database_check,
        "memory_store": memory,
    }

    result_data = {
        "status": overall,
        "checks": checks,
        "version": "0.1.0",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if active_account:
        result_data["active_account"] = active_account

    return success(data=result_data)
