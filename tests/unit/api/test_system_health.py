from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _clear_health_cache():
    from backend.api.routes import system

    system.clear_health_cache()
    yield
    system.clear_health_cache()


@pytest.mark.asyncio
async def test_system_health_omits_xhs_platform(monkeypatch):
    """System health no longer reports legacy XHS credential status."""
    from backend.api.routes import system

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        system,
        "_check_ripple",
        AsyncMock(return_value={"status": "disabled", "configured": False, "message": "off"}),
    )
    monkeypatch.setattr(
        system,
        "_check_memory_store",
        AsyncMock(
            return_value={
                "status": "ok",
                "backend": "memory",
                "semantic_index": False,
                "message": "ok",
            }
        ),
    )

    response = await system.system_health()

    assert response.success is True
    assert response.data is not None
    checks = response.data["checks"]
    assert "xhs_platform" not in checks
    assert "llm_providers" in checks
    assert "ripple_cas" in checks


@pytest.mark.asyncio
async def test_system_health_uses_short_ttl_cache(monkeypatch):
    """Second call within TTL reuses the first payload without rebuilding."""
    from backend.api.routes import system

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    build = AsyncMock(
        side_effect=[
            {
                "status": "ok",
                "checks": {"llm_providers": {"status": "ok"}},
                "version": "0.1.0",
                "timestamp": "t1",
            },
            {
                "status": "ok",
                "checks": {"llm_providers": {"status": "ok"}},
                "version": "0.1.0",
                "timestamp": "t2",
            },
        ]
    )
    monkeypatch.setattr(system, "_build_health_payload", build)

    first = await system.system_health()
    second = await system.system_health()

    assert first.data is second.data
    assert first.data["timestamp"] == "t1"
    assert build.await_count == 1

    third = await system.system_health(fresh=True)
    assert build.await_count == 2
    assert third.data is not None
    assert third.data["timestamp"] == "t2"


@pytest.mark.asyncio
async def test_check_ripple_uses_cached_service_status(monkeypatch):
    """When RippleService already has a probe result, do not block on HTTP."""
    from backend.api.routes import system
    from backend.services.ripple_service import RippleHealthStatus, RippleService

    monkeypatch.setenv("RIPPLE_ENABLED", "true")
    monkeypatch.setenv("RIPPLE_BASE_URL", "http://ripple.local")
    monkeypatch.setenv("RIPPLE_LLM_MODEL_PLATFORM", "openai")
    monkeypatch.setenv("RIPPLE_LLM_MODEL_NAME", "gpt-test")
    monkeypatch.setenv("RIPPLE_LLM_API_KEY", "sk-ripple")

    svc = MagicMock()
    svc._health_status = RippleHealthStatus(
        is_healthy=True,
        last_check="ok",
        latency_ms=12.0,
        reason="",
    )
    monkeypatch.setattr(RippleService, "get_instance", classmethod(lambda cls: svc))

    result = await system._check_ripple()
    assert result["status"] == "ok"
    assert result["reason"] == "ok"
    assert result["latency_ms"] == 12.0


@pytest.mark.asyncio
async def test_check_memory_store_uses_env_only_semantic_status(monkeypatch):
    """Memory health uses env-only semantic status — no Embeddings / alist."""
    from backend.api.routes import system

    monkeypatch.setattr(
        "backend.memory.index.semantic_index_status",
        lambda: {
            "enabled": True,
            "embed_model": "local:BAAI/bge-small-zh-v1.5",
            "embed_dims": 512,
            "reason": "ok",
        },
    )

    result = await system._check_memory_store()
    assert result["semantic_index"] is True
    assert result["embed_model"] == "local:BAAI/bge-small-zh-v1.5"
    assert result["embed_dims"] == 512
    assert "namespace_counts" not in result
