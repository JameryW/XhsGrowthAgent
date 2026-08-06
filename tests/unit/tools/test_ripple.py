"""Ripple integration tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.ripple.integration import predict_spread


@pytest.mark.asyncio
async def test_predict_spread_handles_failure():
    """传播预测失败时返回错误"""
    mock_service = MagicMock()
    mock_service.is_healthy.return_value = True
    mock_service.predict_spread = AsyncMock(side_effect=Exception("Connection refused"))
    mock_service.health_check = AsyncMock()

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = mock_service
        result = await predict_spread(topic="测试话题")
        assert "error" in result
        assert result["ripple_prediction"] is None


def test_ripple_settings_default(monkeypatch):
    """Ripple 配置默认值"""
    from backend.config.settings import RippleSettings

    for key in (
        "RIPPLE_BASE_URL",
        "RIPPLE_API_TOKEN",
        "RIPPLE_DEFAULT_MAX_WAVES",
        "RIPPLE_DEFAULT_SIMULATION_HORIZON",
        "RIPPLE_REQUEST_TIMEOUT",
        "RIPPLE_WORKFLOW_TIMEOUT",
        "RIPPLE_ENABLED",
    ):
        monkeypatch.delenv(key, raising=False)

    s = RippleSettings(_env_file=None)
    assert s.base_url == "http://127.0.0.1:8080"
    assert s.enabled is False
    assert s.default_max_waves == 3
    assert s.default_simulation_horizon == "12h"
    assert s.request_timeout == 300
    assert s.workflow_timeout == 1800
