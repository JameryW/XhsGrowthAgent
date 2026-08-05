"""Ripple integration tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.tools.ripple.integration import (
    cancel_simulation,
    parse_pmf_result,
    parse_spread_prediction,
    predict_spread,
    recover_result,
)


def test_parse_spread_prediction_success():
    """解析传播预测结果"""
    result = {
        "job_id": "test-job-123",
        "output": {
            "metrics": {
                "estimated_reach": 5000,
                "total_engagement": 800,
                "viral_probability": 0.35,
                "confidence": 0.85,
            },
            "phase_analysis": {
                "phase": "growth",
                "spread_path": [{"wave": 1, "reach": 100}],
            },
        },
    }
    parsed = parse_spread_prediction(result)
    assert parsed["ripple_job_id"] == "test-job-123"
    assert parsed["ripple_prediction"]["estimated_reach"] == 5000
    assert parsed["ripple_prediction"]["viral_probability"] == 0.35
    assert parsed["ripple_prediction"]["phase"] == "growth"


def test_parse_spread_prediction_current_ripple_shape():
    """解析当前 Ripple 传播预测结构"""
    result = {
        "job_id": "test-job-current",
        "prediction": {
            "impact": "圈层热度上升",
            "relative_estimate": {
                "views_relative": "+15%~+30%",
                "engagements_relative": "+20%~+40%",
                "confidence": "medium",
            },
            "verdict": "growth",
        },
        "observation": {"phase_vector": {"heat": "growth"}},
        "timeline": [{"wave": 1, "event": "首轮扩散"}],
    }
    parsed = parse_spread_prediction(result)
    prediction = parsed["ripple_prediction"]

    assert parsed["ripple_job_id"] == "test-job-current"
    assert prediction["viral_probability"] == 0.55
    assert prediction["views_relative"] == "+15%~+30%"
    assert prediction["confidence"] == 0.6


def test_parse_spread_prediction_error():
    """解析传播预测错误"""
    result = {"error": "Connection refused"}
    parsed = parse_spread_prediction(result)
    assert parsed["ripple_prediction"] is None
    assert parsed["ripple_error"] == "Connection refused"


def test_parse_pmf_result_success():
    """解析 PMF 验证结果"""
    result = {
        "job_id": "pmf-job-456",
        "output": {
            "pmf_score": 0.72,
            "risk_factors": ["竞争激烈"],
            "improvement_strategies": ["差异化定位"],
            "confidence": 0.8,
        },
    }
    parsed = parse_pmf_result(result)
    assert parsed["ripple_job_id"] == "pmf-job-456"
    assert parsed["ripple_pmf"]["pmf_score"] == 0.72
    assert "竞争激烈" in parsed["ripple_pmf"]["risk_factors"]


def test_parse_pmf_result_current_ripple_shape():
    """解析当前 Ripple PMF 结构"""
    result = {
        "job_id": "pmf-job-current",
        "prediction": {
            "impact": "品类需求明确",
            "relative_estimate": {
                "engagements_relative": "+15%~+25%",
                "confidence": "high",
            },
            "verdict": "growth",
        },
        "observation": {
            "phase_vector": {"heat": "growth"},
            "topology_recommendations": ["强调安全背书"],
        },
        "bifurcation_points": [{"turning_point": "成分争议会降低转化"}],
    }
    parsed = parse_pmf_result(result)
    pmf = parsed["ripple_pmf"]

    assert parsed["ripple_job_id"] == "pmf-job-current"
    assert pmf["pmf_score"] == 0.68
    assert pmf["confidence"] == 0.8
    assert pmf["risk_factors"] == ["成分争议会降低转化"]
    assert pmf["improvement_strategies"] == ["强调安全背书"]


def test_parse_pmf_result_error():
    """解析 PMF 验证错误"""
    result = {"error": "Timeout"}
    parsed = parse_pmf_result(result)
    assert parsed["ripple_pmf"] is None
    assert parsed["ripple_error"] == "Timeout"


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


@pytest.mark.asyncio
async def test_cancel_simulation_wrapper():
    """integration.py cancel_simulation 包装器"""
    mock_service = MagicMock()
    mock_service.is_healthy.return_value = True
    mock_service.health_check = AsyncMock()
    mock_service.cancel_simulation = AsyncMock(
        return_value={"cancelled": True, "job_id": "job-123", "status": "cancelled"}
    )

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = mock_service
        result = await cancel_simulation("job-123")

    assert result["cancelled"] is True
    assert result["job_id"] == "job-123"
    mock_service.cancel_simulation.assert_called_once_with("job-123")


@pytest.mark.asyncio
async def test_cancel_simulation_wrapper_handles_failure():
    """integration.py cancel_simulation 包装器处理异常"""
    mock_service = MagicMock()
    mock_service.is_healthy.return_value = True
    mock_service.health_check = AsyncMock()
    mock_service.cancel_simulation = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = mock_service
        result = await cancel_simulation("job-123")

    assert result["cancelled"] is False
    assert result["status"] == "error"
    assert "Connection refused" in result["error"]


@pytest.mark.asyncio
async def test_recover_result_wrapper():
    """integration.py recover_result 包装器"""
    from backend.services.ripple_service import RecoveryStatus

    mock_service = MagicMock()
    mock_service.is_healthy.return_value = True
    mock_service.health_check = AsyncMock()
    mock_service.recover_result = AsyncMock(
        return_value=RecoveryStatus(job_id="job-456", status="completed", result={"data": 1})
    )

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = mock_service
        result = await recover_result("job-456")

    assert result["job_id"] == "job-456"
    assert result["status"] == "completed"
    assert result["result"]["data"] == 1
    mock_service.recover_result.assert_called_once_with("job-456")


@pytest.mark.asyncio
async def test_recover_result_wrapper_handles_failure():
    """integration.py recover_result 包装器处理异常"""
    mock_service = MagicMock()
    mock_service.is_healthy.return_value = True
    mock_service.health_check = AsyncMock()
    mock_service.recover_result = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("backend.tools.ripple.integration.RippleService") as mock_cls:
        mock_cls.get_instance.return_value = mock_service
        result = await recover_result("job-789")

    assert result["job_id"] == "job-789"
    assert result["status"] == "failed"
    assert "Connection refused" in result["error"]
