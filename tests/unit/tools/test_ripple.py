"""Ripple integration tests."""

from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from backend.tools.ripple.client import (
    ripple_predict_content_spread,
    ripple_validate_pmf,
    ripple_get_simulation_status,
    ripple_get_simulation_result,
    ripple_generate_report,
)
from backend.tools.ripple.integration import (
    predict_spread,
    validate_pmf,
    parse_spread_prediction,
    parse_pmf_result,
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


def test_parse_pmf_result_error():
    """解析 PMF 验证错误"""
    result = {"error": "Timeout"}
    parsed = parse_pmf_result(result)
    assert parsed["ripple_pmf"] is None
    assert parsed["ripple_error"] == "Timeout"


@pytest.mark.asyncio
async def test_predict_spread_handles_failure():
    """传播预测失败时返回错误"""
    with patch("backend.tools.ripple.integration.ripple_predict_content_spread") as mock_tool:
        mock_tool.ainvoke = AsyncMock(side_effect=Exception("Connection refused"))
        result = await predict_spread(topic="测试话题")
        assert "error" in result
        assert result["job_id"] is None


def test_ripple_settings_default():
    """Ripple 配置默认值"""
    from backend.config.settings import RippleSettings

    s = RippleSettings()
    assert s.base_url == "http://127.0.0.1:8081"
    assert s.enabled is True
    assert s.default_max_waves == 8
    assert s.request_timeout == 300


def test_tool_registry_has_ripple():
    """工具注册表包含 Ripple 工具"""
    from backend.tools.registry import ToolRegistry

    ToolRegistry.register_ripple_tools()
    names = ToolRegistry.available_tool_names()
    assert "ripple_predict_content_spread" in names
    assert "ripple_validate_pmf" in names
    assert "ripple_get_simulation_result" in names
    assert "ripple_generate_report" in names


def test_content_strategist_has_ripple_tools():
    """ContentStrategist agent 分配有 Ripple 工具"""
    from backend.tools.registry import ToolRegistry

    ToolRegistry.register_ripple_tools()
    tools = ToolRegistry.get_tools_for_agent("content_strategist")
    tool_names = [t.name for t in tools]
    assert "ripple_predict_content_spread" in tool_names
    assert "ripple_validate_pmf" in tool_names


def test_analyst_has_ripple_tools():
    """Analyst agent 分配有 Ripple 工具"""
    from backend.tools.registry import ToolRegistry

    ToolRegistry.register_ripple_tools()
    tools = ToolRegistry.get_tools_for_agent("analyst")
    tool_names = [t.name for t in tools]
    assert "ripple_get_simulation_result" in tool_names
    assert "ripple_generate_report" in tool_names
