"""Ripple integration tests.

``backend/tools/ripple/integration.py`` is the layer that turns Ripple's own
answers into the runtime's vocabulary. Three things it must get right, and they
are the three tested here: ordinary failures are *not* swallowed (the Gateway
normalises, in exactly one place), a timeout keeps the ``job_id`` (without it
there is no cancel and no resume), and a degraded service is reported as a fact
rather than passed off as a zeroed prediction.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.ripple_service import RippleTimeoutError
from backend.tools.ripple.integration import predict_spread
from backend.tools.runtime import DomainOutcome


def _service(**overrides: object) -> MagicMock:
    """A ``RippleService`` double wired to report itself healthy.

    Healthy matters: ``_get_service`` skips the health check for a healthy
    service, so the double never has to answer one.
    """
    service = MagicMock()
    service.is_healthy.return_value = True
    service.health_check = AsyncMock()
    for name, value in overrides.items():
        setattr(service, name, value)
    return service


@pytest.mark.asyncio
async def test_predict_spread_propagates_a_service_failure():
    """普通异常不在这里吞掉 —— 归一化只在 Gateway 有归属地。

    这里曾把异常转成 ``{"error": ...}`` 返回，那份"软失败"随后被 Gateway 记成一
    次成功（trace 因此说谎），调用方还得猜哪个键意味着失败。
    """
    service = _service(predict_spread=AsyncMock(side_effect=Exception("Connection refused")))

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        with pytest.raises(Exception, match="Connection refused"):
            await predict_spread(topic="测试话题")


@pytest.mark.asyncio
async def test_predict_spread_reports_a_timeout_as_a_domain_outcome():
    """超时必须带着 job_id 出来。

    ``RippleTimeoutError`` 是 ``TimeoutError`` 的子类，所以若让它原样穿过
    Gateway，它会被归类成"网关自己的等待超时" —— 而那条路上 job_id 会被剥掉，
    于是这个 job 既取消不了也恢复不了。
    """
    service = _service(predict_spread=AsyncMock(side_effect=RippleTimeoutError("job-1", 900.0)))

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        with pytest.raises(DomainOutcome) as excinfo:
            await predict_spread(topic="测试话题")

    assert excinfo.value.reason == "timeout"
    assert excinfo.value.payload["ripple_job_id"] == "job-1"
    assert excinfo.value.payload["max_wait"] == 900.0


@pytest.mark.asyncio
async def test_predict_spread_reports_degradation_as_a_domain_outcome():
    """服务降级是自我宣告的事实，不能被当成一次成功的预测。

    服务的降级答复里带着一份全零的"预测"体。原样传出去，调用方读到的零点与
    真实预测无法区分 —— 事实得用调用方能分支的形状说出来。
    """
    service = _service(
        predict_spread=AsyncMock(
            return_value={
                "ripple_prediction": {"estimated_reach": 0, "viral_probability": 0.0},
                "ripple_fallback": True,
                "ripple_reason": "unreachable",
                "ripple_message": "Service unavailable, using default prediction",
            }
        )
    )

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        with pytest.raises(DomainOutcome) as excinfo:
            await predict_spread(topic="测试话题")

    assert excinfo.value.reason == "unavailable"
    assert excinfo.value.payload["ripple_reason"] == "unreachable"
    # 全零的"预测"体不进 payload：调用方自己造兜底，重复搬运只是噪音。
    assert "ripple_prediction" not in excinfo.value.payload


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
