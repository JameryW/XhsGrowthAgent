"""Ripple integration tests.

``backend/tools/ripple/integration.py`` is the layer that turns Ripple's own
answers into the runtime's vocabulary. Three things it must get right, and they
are the three tested here: ordinary failures are *not* swallowed (the Gateway
normalises, in exactly one place), a timeout keeps the ``job_id`` (without it
there is no cancel and no resume), and a degraded service is reported as a fact
rather than passed off as a zeroed prediction.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.services.ripple_service import RippleTimeoutError, RippleUnavailableError
from backend.tools.ripple.integration import get_report, predict_spread, validate_pmf
from backend.tools.runtime import DomainOutcome
from backend.tools.runtime.catalog import build_registry
from backend.tools.runtime.gateway import ToolGateway
from backend.tools.runtime.models import ErrorKind


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


@pytest.mark.asyncio
async def test_get_report_propagates_a_service_failure():
    """取报告失败不再被写成一份"报告"。

    这里曾是 ``except Exception: return {"error": str(e)}`` —— 一份**带 error
    键的成功结果**。Gateway 没有第二个可看的字段，于是记成 ``ok=True``；调用方
    只能靠一条带外约定（``if "error" in report``）得知事实，而 trace 已经把这件
    事说成没发生过。它也是 ``scan_ref_fallbacks`` 发现的那一处：目录 ref 面此前
    不被任何登记表覆盖，因为它既不是 ``@tool``，也不在 service 表的扫描范围里。
    """
    service = _service(get_report=AsyncMock(side_effect=Exception("Connection refused")))

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        with pytest.raises(Exception, match="Connection refused"):
            await get_report(job_id="job-1")


@pytest.mark.asyncio
async def test_a_failed_report_is_not_filed_as_a_success():
    """Gateway 视角：失败的取报告不再是 ``ok=True``。

    这是整个改动的落点。此前 ``get_report`` 把异常写成 ``{"error": ...}``，
    Gateway 除了"调用返回了"没有第二个可看的字段，于是记成成功 —— 调用方
    只能靠 ``if "error" in report`` 这条带外约定得知事实，而 trace 已经把
    它说成没发生过。断言用 outcome 值收（不用 `pytest.raises` 包住整段），
    这样"没抛但回了个 error 体"会红在断言上，而不是崩在别处。
    """
    events: list[dict[str, Any]] = []

    async def trace(event: dict[str, Any]) -> None:
        events.append(dict(event))

    service = _service(get_report=AsyncMock(side_effect=Exception("Connection refused")))
    gateway = ToolGateway(build_registry(), trace=trace)

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        result = await gateway.invoke("ripple.get_report", {"job_id": "job-1"})

    assert result.ok is False
    # 不再有"带 error 键的成功结果"这种形状：失败就是失败。
    assert not (isinstance(result.value, dict) and "error" in result.value)
    assert events[-1].get("ok") is False


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


@pytest.mark.asyncio
async def test_a_degraded_prediction_is_not_filed_as_a_success():
    """降级体经 Gateway 也必须是 ``ok=False``（票 5i 的 trace 落点）。

    ``get_result`` 改动后，"拉不到产物"不再变成
    ``{"ripple_prediction": None, "ripple_error": ...}``（那份经目录回到 Gateway
    是 ``ok=True``），而是走服务自己的降级分支 → 带 ``ripple_fallback`` 的零值体
    → 集成层拒绝成 ``DomainOutcome("unavailable")``。
    """
    events: list[dict[str, Any]] = []

    async def trace(event: dict[str, Any]) -> None:
        events.append(dict(event))

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
    gateway = ToolGateway(build_registry(), trace=trace)

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        result = await gateway.invoke("ripple.predict_spread", {"topic": "测试话题"})

    assert result.ok is False
    assert result.error_kind is ErrorKind.DOMAIN
    assert result.domain.get("reason") == "unavailable"
    assert events[-1].get("ok") is False


@pytest.mark.asyncio
async def test_require_live_refuses_the_degraded_answer():
    """``require_live=True`` 关掉降级，并把"没有真模拟"变成同一个领域判决（票 5p）。

    这是 ripple-retry 迁到 Gateway 的前提：路由不能再靠直调 ``submit_and_wait``
    来"绕开 fallback" —— 它把意图作为 payload 传下来，服务层对
    ``use_fallback=False`` 抛 ``RippleUnavailableError``，集成层翻译成
    ``DomainOutcome("unavailable")``。于是"降级体"与"禁止降级时不可用"在调用方
    是同一个分支，而不是两种形状。
    """
    from backend.services.ripple_service import RippleUnavailableError

    service = _service(predict_spread=AsyncMock(side_effect=RippleUnavailableError("unreachable")))

    outcome: object = "not raised"
    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        try:
            await predict_spread(topic="测试话题", require_live=True)
        except Exception as exc:  # judged below; a different exception is a contract failure
            outcome = exc

    assert isinstance(outcome, DomainOutcome), outcome
    assert outcome.reason == "unavailable"
    assert outcome.payload["ripple_reason"] == "unreachable"
    assert service.predict_spread.await_args.kwargs.get("use_fallback") is False


@pytest.mark.asyncio
async def test_the_pmf_capability_carries_the_same_intent():
    """``require_live`` 在两支能力上同义 —— 路由并发调它们，语义不能一支一半。"""
    service = _service(validate_pmf=AsyncMock(side_effect=RippleUnavailableError("unreachable")))

    outcome: object = "not raised"
    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        try:
            await validate_pmf("产品", "品类", "描述", require_live=True)
        except Exception as exc:
            outcome = exc

    assert isinstance(outcome, DomainOutcome), outcome
    assert outcome.reason == "unavailable"
    assert outcome.payload["ripple_reason"] == "unreachable"
    assert service.validate_pmf.await_args.kwargs.get("use_fallback") is False


@pytest.mark.asyncio
async def test_the_default_path_keeps_the_service_able_to_degrade():
    """没有 ``require_live`` 的调用方（agents）行为不变：允许降级体并由集成层拒绝。"""
    service = _service(
        predict_spread=AsyncMock(return_value={"ripple_prediction": {"viral_probability": 0.3}})
    )

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = service
        result = await predict_spread(topic="测试话题")

    assert result["ripple_prediction"]["viral_probability"] == 0.3
    assert service.predict_spread.await_args.kwargs.get("use_fallback") is True
