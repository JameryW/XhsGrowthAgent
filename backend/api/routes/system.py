"""System health check routes."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from backend.api.deps import get_current_user
from backend.api.responses import ApiResponse, success

logger = logging.getLogger("xhs_growth.api.system")

router = APIRouter()

# Short-lived response cache so /start page mounts don't re-probe every visit.
_HEALTH_CACHE_TTL_S = 15.0
_health_cache: dict[str, Any] | None = None
_health_cache_at: float = 0.0
# Coalesce concurrent cold probes (first request after process start).
_ripple_probe_lock = asyncio.Lock()
_ripple_probe_task: asyncio.Task[None] | None = None


def clear_health_cache() -> None:
    """Drop cached health payload (tests / forced refresh)."""
    global _health_cache, _health_cache_at
    _health_cache = None
    _health_cache_at = 0.0


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


def _ripple_llm_config_payload() -> tuple[bool, dict[str, str]]:
    llm_platform = os.environ.get("RIPPLE_LLM_MODEL_PLATFORM", "")
    llm_name = os.environ.get("RIPPLE_LLM_MODEL_NAME", "")
    llm_key = os.environ.get("RIPPLE_LLM_API_KEY", "")
    return bool(llm_platform and llm_name and llm_key), {
        "platform": llm_platform,
        "model": llm_name,
    }


def _map_ripple_cached_status() -> dict[str, Any] | None:
    """Map RippleService background health cache → API payload, or None if cold."""
    try:
        from backend.services.ripple_service import RippleService

        hs = RippleService.get_instance()._health_status
    except Exception:
        return None

    if not hs.last_check:
        return None

    llm_ok, llm_cfg = _ripple_llm_config_payload()

    if hs.reason == "disabled" or hs.last_check == "disabled":
        return {
            "status": "disabled",
            "configured": False,
            "message": "Ripple 服务未启用",
            "reason": "disabled",
        }

    if hs.is_healthy:
        if llm_ok:
            return {
                "status": "ok",
                "configured": True,
                "message": "Ripple CAS 可用，LLM 配置完整",
                "reason": "ok",
                "llm_config": llm_cfg,
                "latency_ms": hs.latency_ms,
            }
        return {
            "status": "warning",
            "configured": True,
            "message": "Ripple CAS 可用但缺少 LLM 配置（模拟将失败）",
            "reason": "llm_missing",
            "llm_config": llm_cfg,
            "latency_ms": hs.latency_ms,
        }

    return {
        "status": "warning",
        "configured": True,
        "message": hs.error or f"Ripple CAS 不可用（{hs.last_check}）",
        "reason": hs.reason or "unreachable",
    }


def _schedule_ripple_probe() -> None:
    """Kick a background health_check if none is in flight (non-blocking)."""
    global _ripple_probe_task

    async def _run() -> None:
        try:
            from backend.services.ripple_service import RippleService

            async with _ripple_probe_lock:
                await RippleService.get_instance().health_check()
        except Exception as exc:
            logger.debug("background ripple probe failed: %s", exc)

    if _ripple_probe_task is None or _ripple_probe_task.done():
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        _ripple_probe_task = loop.create_task(_run())


async def _check_ripple() -> dict[str, Any]:
    """Check Ripple CAS using background-cached status (no request-path HTTP wait).

    Falls back to a non-blocking pending state when the process has never probed.
    """
    base_url = os.environ.get("RIPPLE_BASE_URL")
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

    cached = _map_ripple_cached_status()
    if cached is not None:
        return cached

    # Cold process: schedule probe, do not block the page-load health request.
    _schedule_ripple_probe()
    return {
        "status": "warning",
        "configured": True,
        "message": "Ripple 健康状态探测中（后台）",
        "reason": "pending",
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
    """Check memory store status: backend type + semantic index (env only).

    Intentionally avoids ``get_store_index()`` (may load HF models) and
    ``store.alist(limit=1000)`` (expensive on Postgres under page-load path).
    """
    from backend.memory.index import semantic_index_status

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

    # Env-only semantic index check — no Embeddings construction.
    sem = semantic_index_status()
    semantic_enabled = bool(sem.get("enabled"))
    embed_model = str(sem.get("embed_model") or "")
    embed_dims = int(sem.get("embed_dims") or 0)

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

    return result


async def _build_health_payload() -> dict[str, Any]:
    """Assemble the full health payload (uncached)."""
    llm = _check_llm_providers()
    # Ripple + memory are both non-blocking / cheap; run concurrently with
    # active-account lookup.
    ripple_task = asyncio.create_task(_check_ripple())
    memory_task = asyncio.create_task(_check_memory_store())
    search = _check_search()

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

    # Creator stats background import (active accounts). Operators historically
    # only looked at /api/system/health — keep the scheduler summary here too.
    scheduler_check: dict[str, Any] = {
        "status": "disabled",
        "message": "定时同步未启用",
    }
    try:
        from backend.api.app import app as fastapi_app

        scheduler_state = getattr(fastapi_app.state, "creator_stats_scheduler_status", None)
        if isinstance(scheduler_state, dict):
            enabled = bool(scheduler_state.get("enabled"))
            status = str(scheduler_state.get("status") or "disabled")
            last_failed = int(scheduler_state.get("last_failed") or 0)
            last_error = scheduler_state.get("last_error")
            if not enabled:
                scheduler_check = {
                    "status": "disabled",
                    "message": "定时同步未启用",
                    "interval_hours": scheduler_state.get("interval_hours"),
                }
            elif status == "running":
                scheduler_check = {
                    "status": "ok",
                    "message": "定时同步进行中",
                    "run_count": scheduler_state.get("run_count"),
                    "last_started_at": scheduler_state.get("last_started_at"),
                }
            elif last_failed > 0 or status == "failed":
                scheduler_check = {
                    "status": "warning",
                    "message": last_error or "最近一轮同步存在失败账号",
                    "last_failed": last_failed,
                    "last_succeeded": scheduler_state.get("last_succeeded"),
                    "last_finished_at": scheduler_state.get("last_finished_at"),
                    "next_run_at": scheduler_state.get("next_run_at"),
                    "run_count": scheduler_state.get("run_count"),
                }
            else:
                scheduler_check = {
                    "status": "ok",
                    "message": "定时同步正常",
                    "last_succeeded": scheduler_state.get("last_succeeded"),
                    "last_finished_at": scheduler_state.get("last_finished_at"),
                    "next_run_at": scheduler_state.get("next_run_at"),
                    "run_count": scheduler_state.get("run_count"),
                    "interval_hours": scheduler_state.get("interval_hours"),
                }
    except Exception as exc:
        scheduler_check = {
            "status": "warning",
            "message": f"无法读取定时同步状态: {exc}",
        }

    ripple = await ripple_task
    memory = await memory_task

    # Overall status: ok if LLM is configured.
    overall = "ok" if llm["status"] == "ok" else "degraded"

    checks = {
        "llm_providers": llm,
        "ripple_cas": ripple,
        "search_api": search,
        "database": database_check,
        "memory_store": memory,
        "creator_stats_scheduler": scheduler_check,
    }

    # Soft-degrade overall when the scheduler is enabled but last run failed.
    if overall == "ok" and scheduler_check.get("status") == "warning":
        overall = "degraded"

    # Anti-risk observability: CDP holders + cool-down gates (non-blocking).
    risk_control: dict[str, Any] = {
        "status": "ok",
        "message": "反风控门控正常",
        "cdp_sessions": [],
        "risk_gates": {},
    }
    try:
        from backend.services.cdp_session_lock import snapshot_cdp_sessions
        from backend.services.xhs_risk_gate import snapshot_risk_gates

        sessions = snapshot_cdp_sessions()
        gates = snapshot_risk_gates()
        active = list(gates.get("active") or [])
        risk_control = {
            "status": "ok" if not sessions and not active else "warning",
            "message": (
                f"CDP 占用中（{len(sessions)}）"
                if sessions
                else (f"冷却中 {len(active)} 项" if active else "无本地 CDP 占用")
            ),
            "cdp_sessions": sessions,
            "risk_gates": gates,
            "active": active[:20],
            "active_count": len(active),
            "max_retry_after_seconds": gates.get("max_retry_after_seconds", 0),
            "active_browser_cooldowns": gates.get("active_browser_cooldowns", 0),
            "active_sync_auth_blocks": gates.get("active_sync_auth_blocks", 0),
            "durable": gates.get("durable", False),
        }
        if gates.get("active_sync_auth_blocks"):
            risk_control["status"] = "warning"
            risk_control["message"] = "存在鉴权冷却中的账号"
    except Exception as exc:
        risk_control = {
            "status": "warning",
            "message": f"无法读取反风控状态: {exc}",
            "cdp_sessions": [],
            "risk_gates": {},
        }
    checks["risk_control"] = risk_control

    result_data: dict[str, Any] = {
        "status": overall,
        "checks": checks,
        "version": "0.1.0",
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if active_account:
        result_data["active_account"] = active_account

    return result_data


@router.get("/health")
async def system_health(
    fresh: Annotated[bool, Query(description="跳过短时缓存，强制重新组装")] = False,
) -> ApiResponse[Any]:
    """系统健康检查

    检查所有外部依赖的可用性：
    - LLM Provider API keys
    - Ripple CAS 引擎（读后台缓存，不阻塞页面）
    - 数据库/存储
    - 搜索 API (Tavily)

    默认缓存 15s，避免 /start 挂载重复探测。``?fresh=1`` 强制刷新。
    """
    global _health_cache, _health_cache_at

    now = time.monotonic()
    if not fresh and _health_cache is not None and (now - _health_cache_at) < _HEALTH_CACHE_TTL_S:
        return success(data=_health_cache)

    result_data = await _build_health_payload()
    _health_cache = result_data
    _health_cache_at = now
    return success(data=result_data)


class ClearRiskGatesRequest(BaseModel):
    """Clear cool-downs for one account or the whole process."""

    account_id: str = Field(default="", description="Empty = all accounts/keys")
    kinds: list[str] = Field(
        default_factory=list,
        description=(
            "Optional kinds: browser_action, publish, engagement, "
            "sync_auth, qr_risk, qr_attempt. Empty = all kinds."
        ),
    )


@router.get("/risk-gates")
async def get_risk_gates(
    account_id: Annotated[str, Query(description="可选，仅返回该账号相关冷却")] = "",
    _: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """List active anti-risk cool-downs with remaining seconds."""
    from backend.services.cdp_session_lock import snapshot_cdp_sessions
    from backend.services.xhs_risk_gate import (
        get_cooldown_policy,
        list_active_cooldowns,
        snapshot_risk_gates,
    )

    gates = snapshot_risk_gates()
    active = list_active_cooldowns(account_id=account_id)
    aid = (account_id or "").strip()
    return success(
        {
            "risk_gates": gates,
            "active": active,
            "cdp_sessions": snapshot_cdp_sessions(),
            "account_id": aid or None,
            "policy": get_cooldown_policy(aid) if aid else None,
        }
    )


@router.post("/risk-gates/clear")
async def clear_risk_gates(
    body: ClearRiskGatesRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Manually clear cool-downs (ops escape hatch after false positives)."""
    from backend.services.xhs_risk_gate import clear_account_cooldowns, list_active_cooldowns

    result = clear_account_cooldowns(
        body.account_id,
        kinds=list(body.kinds or []),
    )
    clear_health_cache()
    logger.info(
        "risk gates cleared by user=%s account=%s kinds=%s total=%s",
        user.get("username") or user.get("id"),
        body.account_id or "*",
        body.kinds or ["*"],
        result.get("total"),
    )
    return success(
        {
            **result,
            "remaining_active": list_active_cooldowns(account_id=body.account_id),
        }
    )


class CooldownPolicyRequest(BaseModel):
    """Per-account cool-down policy overrides (seconds unless noted)."""

    account_id: str = Field(..., min_length=1, description="Account to configure")
    browser_action_seconds: float | None = Field(default=None, ge=0)
    publish_seconds: float | None = Field(default=None, ge=0)
    engagement_seconds: float | None = Field(default=None, ge=0)
    sync_auth_minutes: float | None = Field(default=None, ge=0)
    qr_cooldown_seconds: float | None = Field(default=None, ge=0)
    qr_risk_block_seconds: float | None = Field(default=None, ge=0)
    min_risk_pressure: float | None = Field(
        default=None,
        ge=0,
        le=2,
        description="Creator-stats SAFE_MODE floor: 0=normal, 1=safe, 2=list-only",
    )
    replace: bool = Field(
        default=False,
        description="When true, replace the whole override map (omit = default).",
    )


@router.get("/risk-gates/policy")
async def get_risk_gate_policy(
    account_id: Annotated[str, Query(description="账号 ID；空=仅全局默认")] = "",
    _: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Return effective cool-down policy (global defaults + account overrides)."""
    from backend.services.xhs_risk_gate import get_cooldown_policy, global_cooldown_defaults

    if not (account_id or "").strip():
        return success(
            {
                "account_id": None,
                "defaults": global_cooldown_defaults(),
                "overrides": {},
                "effective": global_cooldown_defaults(),
            }
        )
    return success(get_cooldown_policy(account_id))


@router.put("/risk-gates/policy")
async def put_risk_gate_policy(
    body: CooldownPolicyRequest,
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Create/update per-account cool-down policy overrides."""
    from backend.services.xhs_risk_gate import set_cooldown_policy

    try:
        policy = set_cooldown_policy(
            body.account_id,
            browser_action_seconds=body.browser_action_seconds,
            publish_seconds=body.publish_seconds,
            engagement_seconds=body.engagement_seconds,
            sync_auth_minutes=body.sync_auth_minutes,
            qr_cooldown_seconds=body.qr_cooldown_seconds,
            qr_risk_block_seconds=body.qr_risk_block_seconds,
            min_risk_pressure=body.min_risk_pressure,
            replace=bool(body.replace),
        )
    except ValueError as exc:
        from backend.api.responses import error as api_error

        return api_error(code="invalid_policy", message=str(exc))
    clear_health_cache()
    logger.info(
        "risk gate policy updated by user=%s account=%s overrides=%s",
        user.get("username") or user.get("id"),
        body.account_id,
        policy.get("overrides"),
    )
    return success(policy)


@router.delete("/risk-gates/policy")
async def delete_risk_gate_policy(
    account_id: Annotated[str, Query(description="账号 ID；空=清除全部账号策略")] = "",
    user: dict[str, Any] = Depends(get_current_user),
) -> ApiResponse[Any]:
    """Remove per-account cool-down overrides (revert to global defaults)."""
    from backend.services.xhs_risk_gate import (
        clear_cooldown_policy,
        get_cooldown_policy,
        global_cooldown_defaults,
    )

    result = clear_cooldown_policy(account_id)
    clear_health_cache()
    logger.info(
        "risk gate policy cleared by user=%s account=%s removed=%s",
        user.get("username") or user.get("id"),
        account_id or "*",
        result.get("removed"),
    )
    if (account_id or "").strip():
        policy = get_cooldown_policy(account_id)
    else:
        defaults = global_cooldown_defaults()
        policy = {
            "account_id": None,
            "defaults": defaults,
            "overrides": {},
            "effective": defaults,
        }
    return success({**result, "policy": policy})
