from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


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
