"""Tests for RippleService."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from backend.services.ripple_service import RippleHealthStatus, RippleService


class TestRippleServiceSingleton:
    """测试单例模式"""

    def test_singleton_returns_same_instance(self):
        """单例返回相同实例"""
        service1 = RippleService.get_instance()
        service2 = RippleService.get_instance()
        assert service1 is service2

    def test_new_always_returns_same_instance(self):
        """__new__ 返回相同实例"""
        service1 = RippleService()
        service2 = RippleService()
        assert service1 is service2


class TestRippleHealthStatus:
    """测试健康状态"""

    def test_default_status(self):
        """默认状态为不健康"""
        status = RippleHealthStatus()
        assert status.is_healthy is False
        assert status.last_check == ""
        assert status.error == ""

    def test_healthy_status(self):
        """健康状态"""
        status = RippleHealthStatus(is_healthy=True, last_check="ok", latency_ms=50.0)
        assert status.is_healthy is True
        assert status.latency_ms == 50.0


class TestRippleServiceFallback:
    """测试降级策略"""

    def test_default_spread_prediction(self):
        """默认传播预测"""
        service = RippleService()
        result = service._default_spread_prediction()
        assert result["ripple_fallback"] is True
        assert result["ripple_prediction"]["estimated_reach"] == 0
        assert result["ripple_prediction"]["viral_probability"] == 0.0

    def test_default_pmf_result(self):
        """默认 PMF 结果"""
        service = RippleService()
        result = service._default_pmf_result()
        assert result["ripple_fallback"] is True
        assert result["ripple_pmf"]["pmf_score"] == 0.0
        assert "Ripple service unavailable" in result["ripple_pmf"]["risk_factors"]


class TestRippleServiceHealthCheck:
    """测试健康检查"""

    @pytest.mark.asyncio
    async def test_health_check_disabled(self):
        """Ripple 禁用时健康检查"""
        service = RippleService()

        with patch.object(service, '_get_config', return_value={
            "enabled": False,
            "base_url": "http://127.0.0.1:8081",
            "api_token": "",
            "timeout": 300,
        }):
            status = await service.health_check()
            assert status.is_healthy is False
            assert "disabled" in status.error

    @pytest.mark.asyncio
    async def test_health_check_connect_error(self):
        """连接失败时健康检查"""
        service = RippleService()

        with patch.object(service, '_get_config', return_value={
            "enabled": True,
            "base_url": "http://127.0.0.1:8081",
            "api_token": "",
            "timeout": 300,
        }):
            with patch.object(service, '_get_client') as mock_client:
                mock_client.return_value = MagicMock()
                mock_client.return_value.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))

                status = await service.health_check()
                assert status.is_healthy is False
                assert "Connection refused" in status.error


class TestRippleServiceRetry:
    """测试重试机制"""

    @pytest.mark.asyncio
    async def test_request_with_retry_success_on_second_attempt(self):
        """第二次尝试成功"""
        service = RippleService()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"job_id": "test-123"}

        with patch.object(service, '_get_client') as mock_client:
            client = MagicMock()
            client.post = AsyncMock()
            # 第一次返回 500，第二次成功
            client.post.side_effect = [
                MagicMock(status_code=500, raise_for_status=MagicMock(side_effect=httpx.HTTPStatusError("500", request=MagicMock(), response=MagicMock(status_code=500)))),
                mock_response
            ]
            mock_client.return_value = client

            _result = await service._request_with_retry("POST", "http://test/url", json_data={}, max_retries=3)
            assert client.post.call_count == 2


class TestRippleServicePredict:
    """测试传播预测"""

    @pytest.mark.asyncio
    async def test_predict_spread_with_fallback(self):
        """服务不可用时使用降级"""
        service = RippleService()
        service._health_status = RippleHealthStatus(is_healthy=False)

        with patch.object(service, '_get_config', return_value={"enabled": True}):
            result = await service.predict_spread("测试话题", use_fallback=True)
            assert result["ripple_fallback"] is True

    @pytest.mark.asyncio
    async def test_predict_spread_without_fallback(self):
        """服务不可用时返回错误"""
        service = RippleService()
        service._health_status = RippleHealthStatus(is_healthy=False)

        with patch.object(service, '_get_config', return_value={"enabled": True}):
            result = await service.predict_spread("测试话题", use_fallback=False)
            assert "error" in result
            assert "unavailable" in result["error"]


class TestRippleServiceParse:
    """测试结果解析"""

    def test_parse_spread_result_success(self):
        """解析传播结果"""
        service = RippleService()
        result = {
            "job_id": "test-job",
            "output": {
                "metrics": {
                    "estimated_reach": 5000,
                    "viral_probability": 0.35,
                },
                "phase_analysis": {"phase": "growth"},
            }
        }
        parsed = service._parse_spread_result(result)
        assert parsed["ripple_job_id"] == "test-job"
        assert parsed["ripple_prediction"]["estimated_reach"] == 5000

    def test_parse_spread_result_error(self):
        """解析错误结果"""
        service = RippleService()
        result = {"error": "Timeout"}
        parsed = service._parse_spread_result(result)
        assert parsed["ripple_prediction"] is None
        assert parsed["ripple_error"] == "Timeout"

    def test_parse_pmf_result_success(self):
        """解析 PMF 结果"""
        service = RippleService()
        result = {
            "job_id": "pmf-job",
            "output": {
                "pmf_score": 0.72,
                "risk_factors": ["竞争激烈"],
            }
        }
        parsed = service._parse_pmf_result(result)
        assert parsed["ripple_job_id"] == "pmf-job"
        assert parsed["ripple_pmf"]["pmf_score"] == 0.72


class TestRippleServiceConnectionPool:
    """测试连接池"""

    @pytest.mark.asyncio
    async def test_client_reuse(self):
        """复用 AsyncClient"""
        service = RippleService()

        with patch.object(service, '_get_config', return_value={
            "base_url": "http://test",
            "timeout": 30,
            "api_token": "",
        }):
            client1 = await service._get_client()
            client2 = await service._get_client()
            assert client1 is client2

    @pytest.mark.asyncio
    async def test_close_client(self):
        """关闭连接"""
        service = RippleService()

        with patch.object(service, '_get_config', return_value={
            "base_url": "http://test",
            "timeout": 30,
            "api_token": "",
        }):
            await service._get_client()
            await service.close()
            assert service._client is None