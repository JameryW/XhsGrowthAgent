"""Tests for RippleService."""

from unittest.mock import AsyncMock, MagicMock, call, patch

import httpx
import pytest

from backend.services.ripple_service import (
    RecoveryStatus,
    RippleHealthStatus,
    RippleService,
    RippleTimeoutError,
)


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

        with patch.object(
            service,
            "_get_config",
            return_value={
                "enabled": False,
                "base_url": "http://127.0.0.1:8081",
                "api_token": "",
                "timeout": 300,
            },
        ):
            status = await service.health_check()
            assert status.is_healthy is False
            assert "disabled" in status.error

    @pytest.mark.asyncio
    async def test_health_check_connect_error(self):
        """连接失败时健康检查"""
        service = RippleService()

        with (
            patch.object(
                service,
                "_get_config",
                return_value={
                    "enabled": True,
                    "base_url": "http://127.0.0.1:8081",
                    "api_token": "",
                    "timeout": 300,
                },
            ),
            patch.object(service, "_get_client") as mock_client,
        ):
            mock_client.return_value = MagicMock()
            mock_client.return_value.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )

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

        with patch.object(service, "_get_client") as mock_client:
            client = MagicMock()
            client.post = AsyncMock()
            # 第一次返回 500，第二次成功
            first_response = MagicMock(status_code=500)
            first_response.raise_for_status = MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "500",
                    request=MagicMock(),
                    response=MagicMock(status_code=500),
                )
            )
            client.post.side_effect = [first_response, mock_response]
            mock_client.return_value = client

            _result = await service._request_with_retry(
                "POST", "http://test/url", json_data={}, max_retries=3
            )
            assert client.post.call_count == 2


class TestRippleServicePredict:
    """测试传播预测"""

    @pytest.mark.asyncio
    async def test_predict_spread_with_fallback(self):
        """服务不可用时使用降级"""
        service = RippleService()
        service._health_status = RippleHealthStatus(is_healthy=False)

        with patch.object(service, "_get_config", return_value={"enabled": True}):
            result = await service.predict_spread("测试话题", use_fallback=True)
            assert result["ripple_fallback"] is True

    @pytest.mark.asyncio
    async def test_predict_spread_without_fallback(self):
        """服务不可用时返回错误"""
        service = RippleService()
        service._health_status = RippleHealthStatus(is_healthy=False)

        with patch.object(service, "_get_config", return_value={"enabled": True}):
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
            },
        }
        parsed = service._parse_spread_result(result)
        assert parsed["ripple_job_id"] == "test-job"
        assert parsed["ripple_prediction"]["estimated_reach"] == 5000

    def test_parse_spread_result_current_ripple_shape(self):
        """解析当前 Ripple output-json 结构"""
        service = RippleService()
        result = {
            "job_id": "current-job",
            "prediction": {
                "impact": "内容在母婴圈层中呈增长扩散，收藏和评论会高于基线。",
                "relative_estimate": {
                    "views_relative": "+15%~+30%",
                    "engagements_relative": "+25%~+45%",
                    "favorites_relative": "+20%~+35%",
                    "confidence": "medium",
                },
                "verdict": "growth",
            },
            "timeline": [{"wave": 1, "event": "种草用户开始讨论防晒成分"}],
            "observation": {
                "phase_vector": {
                    "heat": "growth",
                    "sentiment": "unified",
                    "coherence": "ordered",
                },
            },
            "agent_insights": {
                "stars": {"mama_kol": {"role": "parenting"}},
            },
            "total_waves": 4,
        }
        parsed = service._parse_spread_result(result)
        prediction = parsed["ripple_prediction"]

        assert parsed["ripple_job_id"] == "current-job"
        assert prediction["viral_probability"] == 0.55
        assert prediction["confidence"] == 0.6
        assert prediction["phase"] == "growth"
        assert prediction["views_relative"] == "+15%~+30%"
        assert prediction["spread_path"][0]["wave"] == 1
        assert prediction["key_influencers"][0]["name"] == "mama_kol"
        assert prediction["score_source"] == "derived_from_verdict"
        assert "estimated_reach" not in prediction

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
            },
        }
        parsed = service._parse_pmf_result(result)
        assert parsed["ripple_job_id"] == "pmf-job"
        assert parsed["ripple_pmf"]["pmf_score"] == 0.72

    def test_parse_pmf_result_current_ripple_shape(self):
        """解析当前 Ripple PMF output-json 结构"""
        service = RippleService()
        result = {
            "job_id": "pmf-current",
            "prediction": {
                "impact": "目标用户对夏季防晒需求明确，内容种草路径成立。",
                "relative_estimate": {
                    "views_relative": "+10%~+20%",
                    "engagements_relative": "+15%~+25%",
                    "confidence": "high",
                },
                "verdict": "growth",
            },
            "observation": {
                "phase_vector": {"heat": "growth"},
                "topology_recommendations": [
                    {"action": "突出儿童可用和补涂便利性"},
                ],
            },
            "bifurcation_points": [
                {"turning_point": "若成分解释不足，评论区会转向安全性质疑"},
            ],
            "agent_insights": {"seas": {"segment": "母婴防晒决策人群"}},
            "total_waves": 4,
        }
        parsed = service._parse_pmf_result(result)
        pmf = parsed["ripple_pmf"]

        assert parsed["ripple_job_id"] == "pmf-current"
        assert pmf["pmf_score"] == 0.68
        assert pmf["confidence"] == 0.8
        assert pmf["views_relative"] == "+10%~+20%"
        assert pmf["risk_factors"] == ["若成分解释不足，评论区会转向安全性质疑"]
        assert pmf["improvement_strategies"] == ["突出儿童可用和补涂便利性"]
        assert pmf["market_segment"]["segment"] == "母婴防晒决策人群"
        assert pmf["score_source"] == "derived_from_verdict"


class TestRippleServiceConnectionPool:
    """测试连接池"""

    @pytest.mark.asyncio
    async def test_client_reuse(self):
        """复用 AsyncClient — mock httpx to avoid real connection."""
        service = RippleService()
        mock_client = MagicMock()

        with (
            patch.object(
                service,
                "_get_config",
                return_value={
                    "base_url": "http://test",
                    "timeout": 30,
                    "api_token": "",
                },
            ),
            patch("backend.services.ripple_service.httpx.AsyncClient", return_value=mock_client),
        ):
            client1 = await service._get_client()
            client2 = await service._get_client()
            assert client1 is client2

    @pytest.mark.asyncio
    async def test_close_client(self):
        """关闭连接 — mock httpx to avoid real connection."""
        service = RippleService()
        mock_client = MagicMock()
        mock_client.is_closed = False
        mock_client.aclose = AsyncMock()

        with (
            patch.object(
                service,
                "_get_config",
                return_value={
                    "base_url": "http://test",
                    "timeout": 30,
                    "api_token": "",
                },
            ),
            patch("backend.services.ripple_service.httpx.AsyncClient", return_value=mock_client),
        ):
            await service._get_client()
            await service.close()
            assert service._client is None


class TestRippleTimeoutError:
    """测试 RippleTimeoutError 异常"""

    def test_carries_job_id(self):
        """RippleTimeoutError 携带 job_id"""
        err = RippleTimeoutError("job-123", 900.0)
        assert err.job_id == "job-123"
        assert err.max_wait == 900.0
        assert "job-123" in str(err)
        assert "900" in str(err)

    def test_is_timeout_error_subclass(self):
        """RippleTimeoutError 是 TimeoutError 的子类"""
        err = RippleTimeoutError("job-456", 1800.0)
        assert isinstance(err, TimeoutError)


class TestRippleServiceCancelSimulation:
    """测试 cancel_simulation 方法"""

    @pytest.mark.asyncio
    async def test_cancel_simulation_success(self):
        """两步取消协议成功"""
        service = RippleService()

        request_response = MagicMock()
        request_response.status_code = 200
        request_response.json.return_value = {"cancel_token": "tok-123"}

        confirm_response = MagicMock()
        confirm_response.status_code = 202
        confirm_response.json.return_value = {"status": "cancelling"}

        with (
            patch.object(
                service,
                "_get_config",
                return_value={
                    "base_url": "http://ripple-test",
                    "api_token": "",
                    "timeout": 30,
                },
            ),
            patch.object(service, "_get_client") as mock_client,
        ):
            client = MagicMock()
            client.post = AsyncMock(side_effect=[request_response, confirm_response])
            client.delete = AsyncMock()
            mock_client.return_value = client

            result = await service.cancel_simulation("job-123")

        assert result["cancelled"] is True
        assert result["job_id"] == "job-123"
        assert result["status"] == "cancelling"
        assert client.post.await_args_list == [
            call("http://ripple-test/v1/simulations/job-123/cancel-request"),
            call(
                "http://ripple-test/v1/simulations/job-123/cancel-confirm",
                json={"cancel_token": "tok-123"},
            ),
        ]
        client.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_simulation_not_found(self):
        """cancel-request 返回 404 — 任务不存在"""
        service = RippleService()

        mock_response = MagicMock()
        mock_response.status_code = 404

        with (
            patch.object(
                service,
                "_get_config",
                return_value={
                    "base_url": "http://ripple-test",
                    "api_token": "",
                    "timeout": 30,
                },
            ),
            patch.object(service, "_get_client") as mock_client,
        ):
            client = MagicMock()
            client.post = AsyncMock(return_value=mock_response)
            client.delete = AsyncMock()
            mock_client.return_value = client

            result = await service.cancel_simulation("job-404")

        assert result["cancelled"] is False
        assert result["job_id"] == "job-404"
        assert result["status"] == "not_found"
        client.post.assert_awaited_once_with(
            "http://ripple-test/v1/simulations/job-404/cancel-request"
        )
        client.delete.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cancel_simulation_legacy_delete_success(self):
        """cancel-request 405 时回退到旧 DELETE 成功"""
        service = RippleService()

        request_response = MagicMock()
        request_response.status_code = 405

        delete_response = MagicMock()
        delete_response.status_code = 204

        with (
            patch.object(
                service,
                "_get_config",
                return_value={
                    "base_url": "http://ripple-test",
                    "api_token": "",
                    "timeout": 30,
                },
            ),
            patch.object(service, "_get_client") as mock_client,
        ):
            client = MagicMock()
            client.post = AsyncMock(return_value=request_response)
            client.delete = AsyncMock(return_value=delete_response)
            mock_client.return_value = client

            result = await service.cancel_simulation("job-legacy")

        assert result["cancelled"] is True
        assert result["job_id"] == "job-legacy"
        assert result["status"] == "cancelled"
        client.post.assert_awaited_once_with(
            "http://ripple-test/v1/simulations/job-legacy/cancel-request"
        )
        client.delete.assert_awaited_once_with("http://ripple-test/v1/simulations/job-legacy")

    @pytest.mark.asyncio
    async def test_cancel_simulation_not_supported(self):
        """新旧取消协议都不可用"""
        service = RippleService()

        request_response = MagicMock()
        request_response.status_code = 405

        delete_response = MagicMock()
        delete_response.status_code = 405

        with (
            patch.object(
                service,
                "_get_config",
                return_value={
                    "base_url": "http://ripple-test",
                    "api_token": "",
                    "timeout": 30,
                },
            ),
            patch.object(service, "_get_client") as mock_client,
        ):
            client = MagicMock()
            client.post = AsyncMock(return_value=request_response)
            client.delete = AsyncMock(return_value=delete_response)
            mock_client.return_value = client

            result = await service.cancel_simulation("job-405")

        assert result["cancelled"] is False
        assert result["job_id"] == "job-405"
        assert result["status"] == "not_supported"

    @pytest.mark.asyncio
    async def test_cancel_simulation_network_error(self):
        """cancel-request 网络错误 — 优雅降级"""
        service = RippleService()

        with (
            patch.object(
                service,
                "_get_config",
                return_value={
                    "base_url": "http://ripple-test",
                    "api_token": "",
                    "timeout": 30,
                },
            ),
            patch.object(service, "_get_client") as mock_client,
        ):
            client = MagicMock()
            client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client.return_value = client

            result = await service.cancel_simulation("job-net")

        assert result["cancelled"] is False
        assert result["job_id"] == "job-net"
        assert result["status"] == "error"
        assert "Connection refused" in result["error"]


class TestRippleServiceRecoverResult:
    """测试 recover_result 方法"""

    @pytest.mark.asyncio
    async def test_recover_result_completed(self):
        """任务已完成 — 返回结果"""
        service = RippleService()

        with (
            patch.object(service, "get_simulation_status", new_callable=AsyncMock) as mock_status,
            patch.object(service, "get_result", new_callable=AsyncMock) as mock_result,
        ):
            mock_status.return_value = {"status": "completed"}
            mock_result.return_value = {"output": {"metrics": {"estimated_reach": 5000}}}

            recovery = await service.recover_result("job-done")

        assert isinstance(recovery, RecoveryStatus)
        assert recovery.job_id == "job-done"
        assert recovery.status == "completed"
        assert recovery.result is not None
        assert recovery.result["output"]["metrics"]["estimated_reach"] == 5000

    @pytest.mark.asyncio
    async def test_recover_result_running(self):
        """任务仍在运行 — 返回 running 状态"""
        service = RippleService()

        with patch.object(service, "get_simulation_status", new_callable=AsyncMock) as mock_status:
            mock_status.return_value = {"status": "running"}

            recovery = await service.recover_result("job-running")

        assert isinstance(recovery, RecoveryStatus)
        assert recovery.job_id == "job-running"
        assert recovery.status == "running"
        assert recovery.result is None

    @pytest.mark.asyncio
    async def test_recover_result_failed(self):
        """任务失败 — 返回 failed 状态"""
        service = RippleService()

        with patch.object(service, "get_simulation_status", new_callable=AsyncMock) as mock_status:
            mock_status.return_value = {"status": "failed", "error": "OOM"}

            recovery = await service.recover_result("job-failed")

        assert isinstance(recovery, RecoveryStatus)
        assert recovery.job_id == "job-failed"
        assert recovery.status == "failed"
        assert "OOM" in recovery.error

    @pytest.mark.asyncio
    async def test_recover_result_timed_out(self):
        """任务服务端超时 — 返回 timed_out 状态"""
        service = RippleService()

        with patch.object(service, "get_simulation_status", new_callable=AsyncMock) as mock_status:
            mock_status.return_value = {"status": "timed_out", "error": "phase timeout"}

            recovery = await service.recover_result("job-timeout")

        assert isinstance(recovery, RecoveryStatus)
        assert recovery.job_id == "job-timeout"
        assert recovery.status == "timed_out"
        assert "phase timeout" in recovery.error

    @pytest.mark.asyncio
    async def test_recover_result_not_found(self):
        """任务 404 — 返回 not_found 状态"""
        service = RippleService()

        with patch.object(service, "get_simulation_status", new_callable=AsyncMock) as mock_status:
            mock_status.side_effect = httpx.HTTPStatusError(
                "404",
                request=MagicMock(),
                response=MagicMock(status_code=404),
            )

            recovery = await service.recover_result("job-404")

        assert isinstance(recovery, RecoveryStatus)
        assert recovery.job_id == "job-404"
        assert recovery.status == "not_found"

    @pytest.mark.asyncio
    async def test_recover_result_network_error(self):
        """网络错误 — 返回 failed 状态"""
        service = RippleService()

        with patch.object(service, "get_simulation_status", new_callable=AsyncMock) as mock_status:
            mock_status.side_effect = httpx.ConnectError("Connection refused")

            recovery = await service.recover_result("job-net")

        assert isinstance(recovery, RecoveryStatus)
        assert recovery.job_id == "job-net"
        assert recovery.status == "failed"
        assert "Connection refused" in recovery.error
