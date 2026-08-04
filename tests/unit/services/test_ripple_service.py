"""Tests for RippleService."""

import asyncio
import contextlib
import time
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
                "POST", "http://test/url", json_data={}, max_retries=3, retry_delay=0
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


class TestAutoRecovery:
    """Tests for RippleService auto-recovery after container restart."""

    @pytest.fixture
    def service_unhealthy(self):
        """RippleService instance marked as unreachable."""
        svc = RippleService()
        svc._health_status = RippleHealthStatus(
            is_healthy=False,
            last_check="connect_error",
            error="Connection refused",
            reason="unreachable",
        )
        # ponytail: _probe_before_fallback short-circuits to False when
        # Settings.ripple.enabled is False (the default in a clean CI env).
        # Pin enabled=True so these recovery tests don't depend on RIPPLE_ENABLED.
        svc._get_config = lambda: {
            "base_url": "http://ripple-service:8080",
            "api_token": "t",
            "timeout": 5,
            "workflow_timeout": 60,
            "enabled": True,
        }
        return svc

    @pytest.mark.asyncio
    async def test_mark_healthy_recovers_status(self, service_unhealthy):
        """_mark_healthy should recover is_healthy to True."""
        svc = service_unhealthy
        assert not svc.is_healthy()
        svc._mark_healthy()
        assert svc.is_healthy()

    @pytest.mark.asyncio
    async def test_connect_error_exhausted_marks_unreachable(self):
        """ConnectError that exhausts all retries should mark service as unreachable."""
        svc = RippleService()
        svc._health_status = RippleHealthStatus(is_healthy=True, last_check="ok", reason="")

        with patch.object(svc, "_get_client") as mock_client:
            mock_http_client = AsyncMock()
            mock_http_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client.return_value = mock_http_client

            with pytest.raises(httpx.ConnectError):
                await svc._request_with_retry(
                    "POST", "http://ripple-service:8080/api/test", retry_delay=0
                )

        assert not svc.is_healthy()
        assert svc._health_status.reason == "unreachable"

    @pytest.mark.asyncio
    async def test_request_success_auto_marks_healthy(self):
        """A successful _request_with_retry call should mark service healthy."""
        svc = RippleService()
        svc._health_status = RippleHealthStatus(
            is_healthy=False,
            last_check="connect_error",
            error="Connection refused",
            reason="unreachable",
        )

        with patch.object(svc, "_get_client") as mock_client:
            mock_http_client = AsyncMock()
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"status": "ok"}
            mock_response.raise_for_status = MagicMock()
            mock_http_client.post = AsyncMock(return_value=mock_response)
            mock_client.return_value = mock_http_client

            with patch.object(svc, "_rebuild_client", new_callable=AsyncMock):
                result = await svc._request_with_retry(
                    "POST", "http://ripple-service:8080/api/test"
                )

        assert svc.is_healthy()
        assert result == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_probe_before_fallback_recovers(self, service_unhealthy):
        """_probe_before_fallback should return True when health_check recovers."""
        svc = service_unhealthy
        assert not svc.is_healthy()

        with patch.object(svc, "health_check", new_callable=AsyncMock) as mock_hc:

            async def make_healthy():
                svc._health_status = RippleHealthStatus(is_healthy=True, last_check="ok", reason="")

            mock_hc.side_effect = make_healthy

            with patch.object(svc, "_rebuild_client", new_callable=AsyncMock):
                result = await svc._probe_before_fallback()

        assert result is True
        assert svc.is_healthy()

    @pytest.mark.asyncio
    async def test_probe_before_fallback_still_unreachable(self, service_unhealthy):
        """_probe_before_fallback should return False when service stays unreachable."""
        svc = service_unhealthy

        with patch.object(svc, "health_check", new_callable=AsyncMock):
            result = await svc._probe_before_fallback()

        assert result is False
        assert not svc.is_healthy()

    @pytest.mark.asyncio
    async def test_rebuild_client_closes_old(self):
        """_rebuild_client should close the old client and set _client to None."""
        svc = RippleService()
        old_client = AsyncMock()
        old_client.is_closed = False
        svc._client = old_client

        await svc._rebuild_client()

        old_client.aclose.assert_awaited_once()
        assert svc._client is None

    @pytest.mark.asyncio
    async def test_rebuild_client_handles_already_closed(self):
        """_rebuild_client should handle already-closed client gracefully."""
        svc = RippleService()
        old_client = AsyncMock()
        old_client.is_closed = True
        svc._client = old_client

        await svc._rebuild_client()

        old_client.aclose.assert_not_awaited()
        assert svc._client is None

    @pytest.mark.asyncio
    async def test_background_health_check_loop(self):
        """Background loop should call health_check periodically and rebuild on recovery."""
        svc = RippleService()
        svc._health_status = RippleHealthStatus(
            is_healthy=False, last_check="connect_error", error="", reason="unreachable"
        )

        call_count = 0

        async def mock_health_check():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                svc._health_status = RippleHealthStatus(is_healthy=True, last_check="ok", reason="")

        with (
            patch.object(svc, "health_check", side_effect=mock_health_check),
            patch.object(svc, "_rebuild_client", new_callable=AsyncMock) as mock_rebuild,
        ):
            task = asyncio.create_task(svc._health_check_loop(interval_seconds=0.05))
            await asyncio.sleep(0.2)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert call_count >= 2
        mock_rebuild.assert_awaited()

    @pytest.mark.asyncio
    async def test_start_stop_background_health_check(self):
        """start/stop should create and cancel the background task."""
        svc = RippleService()

        with (
            patch.object(
                svc,
                "_get_config",
                return_value={
                    "enabled": True,
                    "base_url": "http://localhost:8081",
                    "api_token": "",
                    "timeout": 5,
                },
            ),
            patch.object(svc, "_health_check_loop", new_callable=AsyncMock),
        ):
            svc.start_background_health_check(interval_seconds=1.0)
            assert svc._bg_task is not None

            svc.stop_background_health_check()
            assert svc._bg_task is None

    @pytest.mark.asyncio
    async def test_start_background_skipped_when_disabled(self):
        """start_background_health_check should not start when Ripple is disabled."""
        svc = RippleService()

        with patch.object(
            svc,
            "_get_config",
            return_value={"enabled": False, "base_url": "", "api_token": "", "timeout": 5},
        ):
            svc.start_background_health_check()
            assert svc._bg_task is None


class TestStreamProgress:
    """Test _stream_progress SSE consumer."""

    @pytest.mark.asyncio
    async def test_stream_progress_updates_state_from_sse(self):
        """SSE events update progress_state with progress/wave/total_waves."""
        svc = RippleService()
        progress_state: dict = {
            "progress": 0.0,
            "current_wave": 0,
            "total_waves": 0,
            "phase": "",
            "last_update_at": None,
        }
        done_event = asyncio.Event()

        sse_lines = [
            "event: progress.wave_start",
            'data: {"phase":"RIPPLE","wave":2,"progress":0.25,"total_waves":8}',
            "",
            "event: progress.wave_end",
            'data: {"phase":"RIPPLE","wave":3,"progress":0.45,"total_waves":8}',
            "",
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=AsyncIterator(sse_lines))

        with (
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
            patch.object(svc, "_get_headers", return_value={}),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = MagicMock(return_value=AsyncContextManagerMock(mock_resp))
            mock_client_cls.return_value = mock_client

            await svc._stream_progress("job_123", "thread_abc", progress_state, done_event)

        assert progress_state["progress"] == 0.45
        assert progress_state["current_wave"] == 3
        assert progress_state["total_waves"] == 8
        assert progress_state["last_update_at"] is not None

    @pytest.mark.asyncio
    async def test_stream_progress_nested_payload_format(self):
        """Ripple event_bus wraps fields in a 'payload' sub-dict — ensure we unwrap correctly."""
        svc = RippleService()
        progress_state: dict = {
            "progress": 0.0,
            "current_wave": 0,
            "total_waves": 0,
            "phase": "",
            "last_update_at": None,
        }
        done_event = asyncio.Event()

        # Real Ripple SSE format: outer envelope has job_id, seq, type, ts, payload
        sse_lines = [
            "event: progress.wave_start",
            'data: {"job_id":"job_abc","seq":3,"type":"progress.wave_start","ts":"2026-06-15T04:00:00Z","payload":{"phase":"RIPPLE","wave":4,"progress":0.55,"total_waves":8,"detail":{}}}',  # noqa: E501
            "",
            "event: progress.wave_end",
            'data: {"job_id":"job_abc","seq":4,"type":"progress.wave_end","ts":"2026-06-15T04:00:05Z","payload":{"phase":"RIPPLE","wave":5,"progress":0.7,"total_waves":8,"detail":{"quality":{"input_completeness":0.8}}}}',  # noqa: E501
            "",
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=AsyncIterator(sse_lines))

        with (
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
            patch.object(svc, "_get_headers", return_value={}),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = MagicMock(return_value=AsyncContextManagerMock(mock_resp))
            mock_client_cls.return_value = mock_client

            await svc._stream_progress("job_abc", "thread_xyz", progress_state, done_event)

        assert progress_state["progress"] == 0.7
        assert progress_state["current_wave"] == 5
        assert progress_state["total_waves"] == 8
        assert progress_state["phase"] == "RIPPLE"
        assert progress_state["quality"]["input_completeness"] == 0.8

    @pytest.mark.asyncio
    async def test_stream_progress_sets_done_on_job_completed(self):
        """SSE job.completed event sets done_event."""
        svc = RippleService()
        progress_state: dict = {
            "progress": 0.8,
            "current_wave": 6,
            "total_waves": 8,
            "phase": "",
            "last_update_at": 100.0,
        }
        done_event = asyncio.Event()

        sse_lines = [
            "event: job.completed",
            'data: {"result":"ok"}',
            "",
        ]

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        mock_resp.aiter_lines = MagicMock(return_value=AsyncIterator(sse_lines))

        with (
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
            patch.object(svc, "_get_headers", return_value={}),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = MagicMock(return_value=AsyncContextManagerMock(mock_resp))
            mock_client_cls.return_value = mock_client

            await svc._stream_progress("job_123", "thread_abc", progress_state, done_event)

        assert done_event.is_set()

    @pytest.mark.asyncio
    async def test_stream_progress_fallback_on_connection_error(self):
        """SSE connection error returns silently (caller falls back to time estimate)."""
        svc = RippleService()
        progress_state: dict = {
            "progress": 0.0,
            "current_wave": 0,
            "total_waves": 0,
            "phase": "",
            "last_update_at": None,
        }
        done_event = asyncio.Event()

        with (
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
            patch.object(svc, "_get_headers", return_value={}),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            # Should not raise
            await svc._stream_progress("job_123", "thread_abc", progress_state, done_event)

        # State should remain unchanged
        assert progress_state["progress"] == 0.0
        assert progress_state["last_update_at"] is None

    @pytest.mark.asyncio
    async def test_stream_progress_stops_on_done_event(self):
        """SSE consumer stops reading when done_event is set externally."""
        svc = RippleService()
        progress_state: dict = {
            "progress": 0.0,
            "current_wave": 0,
            "total_waves": 0,
            "phase": "",
            "last_update_at": None,
        }
        done_event = asyncio.Event()

        # Set done_event before stream starts — consumer should exit immediately
        done_event.set()

        mock_resp = AsyncMock()
        mock_resp.status_code = 200
        lines = [
            "event: progress.wave_start",
            'data: {"phase":"RIPPLE","wave":1,"progress":0.1,"total_waves":8}',
            "",
        ]
        mock_resp.aiter_lines = MagicMock(return_value=AsyncIterator(lines))

        with (
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
            patch.object(svc, "_get_headers", return_value={}),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client.stream = MagicMock(return_value=AsyncContextManagerMock(mock_resp))
            mock_client_cls.return_value = mock_client

            await svc._stream_progress("job_123", "thread_abc", progress_state, done_event)

        # Should not have processed any events
        assert progress_state["progress"] == 0.0


class TestWaitForCompletionWithSSE:
    """Test wait_for_completion SSE + polling dual-channel."""

    @pytest.mark.asyncio
    async def test_emit_progress_with_sse_data(self):
        """Progress events use SSE data when available."""
        svc = RippleService()
        emitted: list[dict] = []

        def mock_emit(
            job_id,
            progress,
            current_wave,
            total_waves,
            elapsed_seconds,
            thread_id,
            status="running",
            skill="",
        ):
            emitted.append(
                {"progress": progress, "current_wave": current_wave, "total_waves": total_waves}
            )

        with (
            patch.object(svc, "get_simulation_status", new_callable=AsyncMock) as mock_status,
            patch.object(svc, "_stream_progress", new_callable=AsyncMock) as mock_sse,
            patch.object(svc, "_emit_progress", side_effect=mock_emit),
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
        ):
            # Simulate: 1st poll running, 2nd running (SSE data now available), 3rd completed
            mock_status.side_effect = [
                {"status": "running"},
                {"status": "running"},
                {"status": "completed"},
            ]

            # Simulate SSE updating progress_state immediately
            async def sse_update(job_id, thread_id, progress_state, done_event):
                progress_state["progress"] = 0.5
                progress_state["current_wave"] = 4
                progress_state["total_waves"] = 8
                progress_state["last_update_at"] = time.monotonic()

            mock_sse.side_effect = sse_update

            result = await svc.wait_for_completion(
                "job_123", thread_id="thread_abc", poll_interval=0.01
            )

        assert result["status"] == "completed"
        # At least one emit should use SSE data (progress=0.5, wave=4/8)
        sse_emits = [e for e in emitted if e["progress"] == 0.5 and e["current_wave"] == 4]
        assert len(sse_emits) >= 1

    @pytest.mark.asyncio
    async def test_emit_progress_time_fallback_when_no_sse(self):
        """Falls back to time-based estimate when SSE provides no data."""
        svc = RippleService()
        emitted: list[dict] = []

        def mock_emit(
            job_id,
            progress,
            current_wave,
            total_waves,
            elapsed_seconds,
            thread_id,
            status="running",
            skill="",
        ):
            emitted.append({"progress": progress})

        with (
            patch.object(svc, "get_simulation_status", new_callable=AsyncMock) as mock_status,
            patch.object(svc, "_stream_progress", new_callable=AsyncMock) as mock_sse,
            patch.object(svc, "_emit_progress", side_effect=mock_emit),
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
        ):
            # More polls so elapsed time grows
            mock_status.side_effect = [
                {"status": "running"},
                {"status": "running"},
                {"status": "running"},
                {"status": "completed"},
            ]

            # SSE does nothing (simulating connection failure)
            async def sse_noop(job_id, thread_id, progress_state, done_event):
                pass

            mock_sse.side_effect = sse_noop

            result = await svc.wait_for_completion(
                "job_123", thread_id="thread_abc", poll_interval=0.05
            )

        assert result["status"] == "completed"
        # The last emit should be 1.0 (completion)
        assert emitted[-1]["progress"] == 1.0
        # Non-final emits should use time-based estimate (progress >= 0)
        non_final = [e for e in emitted if e["progress"] < 1.0]
        assert all(0 <= e["progress"] <= 0.95 for e in non_final)

    @pytest.mark.asyncio
    async def test_sse_task_cancelled_on_completion(self):
        """SSE task is cancelled when wait_for_completion finishes."""
        svc = RippleService()

        with (
            patch.object(svc, "get_simulation_status", new_callable=AsyncMock) as mock_status,
            patch.object(svc, "_stream_progress", new_callable=AsyncMock) as mock_sse,
            patch.object(svc, "_emit_progress"),
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
        ):
            mock_status.return_value = {"status": "completed"}

            # SSE task that would run forever
            async def sse_hang(job_id, thread_id, progress_state, done_event):
                await asyncio.sleep(100)

            mock_sse.side_effect = sse_hang

            result = await svc.wait_for_completion(
                "job_123", thread_id="thread_abc", poll_interval=0.01
            )

        assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_stale_sse_zero_progress_falls_back_to_time_estimate(self):
        """When SSE sends progress=0 and goes stale, falls back to time-based estimate."""
        from backend.services.ripple_service import SSE_STALE_THRESHOLD

        svc = RippleService()
        emitted: list[dict] = []

        def mock_emit(
            job_id,
            progress,
            current_wave,
            total_waves,
            elapsed_seconds,
            thread_id,
            status="running",
            skill="",
        ):
            emitted.append(
                {"progress": progress, "current_wave": current_wave, "elapsed": elapsed_seconds}
            )

        with (
            patch.object(svc, "get_simulation_status", new_callable=AsyncMock) as mock_status,
            patch.object(svc, "_stream_progress", new_callable=AsyncMock) as mock_sse,
            patch.object(svc, "_emit_progress", side_effect=mock_emit),
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
        ):
            mock_status.side_effect = [
                {"status": "running"},
                {"status": "running"},
                {"status": "running"},
                {"status": "completed"},
            ]

            # SSE sends progress=0 once (long ago), then goes stale
            async def sse_stale_zero(job_id, thread_id, progress_state, done_event):
                progress_state["progress"] = 0.0
                progress_state["current_wave"] = 0
                progress_state["total_waves"] = 0
                # Set last_update_at far in the past → stale
                progress_state["last_update_at"] = time.monotonic() - SSE_STALE_THRESHOLD - 10

            mock_sse.side_effect = sse_stale_zero

            # Use a small max_wait so time-based estimate is visible
            result = await svc.wait_for_completion(
                "job_123", thread_id="thread_abc", poll_interval=0.05, max_wait=1.0
            )

        assert result["status"] == "completed"
        # Non-final emits should use time-based estimate (progress based on elapsed/max_wait)
        non_final = [e for e in emitted if e["progress"] < 1.0]
        assert len(non_final) > 0
        # With max_wait=1.0 and poll_interval=0.05, at least the 2nd/3rd poll
        # should have elapsed > 0.05s, so progress > 0.05
        assert any(e["progress"] >= 0.03 for e in non_final), (
            f"Time-based fallback not working: {non_final}"
        )

    @pytest.mark.asyncio
    async def test_fresh_sse_nonzero_progress_used_directly(self):
        """When SSE sends progress > 0 and is fresh, the SSE value is used directly."""
        svc = RippleService()
        emitted: list[dict] = []

        def mock_emit(
            job_id,
            progress,
            current_wave,
            total_waves,
            elapsed_seconds,
            thread_id,
            status="running",
            skill="",
        ):
            emitted.append({"progress": progress, "current_wave": current_wave})

        with (
            patch.object(svc, "get_simulation_status", new_callable=AsyncMock) as mock_status,
            patch.object(svc, "_stream_progress", new_callable=AsyncMock) as mock_sse,
            patch.object(svc, "_emit_progress", side_effect=mock_emit),
            patch.object(svc, "_get_config", return_value={"base_url": "http://localhost:8080"}),
        ):
            mock_status.side_effect = [
                {"status": "running"},
                {"status": "running"},
                {"status": "completed"},
            ]

            # SSE sends meaningful progress (fresh)
            async def sse_fresh(job_id, thread_id, progress_state, done_event):
                progress_state["progress"] = 0.6
                progress_state["current_wave"] = 5
                progress_state["total_waves"] = 8
                progress_state["last_update_at"] = time.monotonic()

            mock_sse.side_effect = sse_fresh

            result = await svc.wait_for_completion(
                "job_123", thread_id="thread_abc", poll_interval=0.01
            )

        assert result["status"] == "completed"
        # At least one emit should use SSE data (progress=0.6, wave=5)
        sse_emits = [e for e in emitted if e["progress"] == 0.6 and e["current_wave"] == 5]
        assert len(sse_emits) >= 1


class AsyncIterator:
    """Helper to make an async iterator from a list for mocking aiter_lines."""

    def __init__(self, items):
        self._items = list(items)
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


class AsyncContextManagerMock:
    """Helper to mock async context managers (e.g., httpx client.stream)."""

    def __init__(self, return_value):
        self._return_value = return_value

    async def __aenter__(self):
        return self._return_value

    async def __aexit__(self, *args):
        return False


class TestRippleProgressStoreCleanup:
    """Ripple 仿真进度收尾——防止前端永久卡 95%。"""

    def setup_method(self):
        RippleService._progress_store.clear()

    def teardown_method(self):
        RippleService._progress_store.clear()

    def test_terminal_status_pops_store(self):
        """终态（含 timed_out/failed）必须从 _progress_store 移除。"""
        svc = RippleService()
        # 先写入一条 running 条目
        svc._emit_progress("job-1", 0.95, 0, 0, 100.0, "thread-A", status="running")
        assert "thread-A:job-1" in RippleService._progress_store
        # timed_out 收尾应 pop
        svc._emit_progress("job-1", 1.0, 0, 0, 1800.0, "thread-A", status="timed_out")
        assert "thread-A:job-1" not in RippleService._progress_store

    def test_get_thread_progress_filters_stale_running(self):
        """status=running 且 elapsed≥1800 的残留条目应被剔除并 pop。"""
        RippleService._progress_store["thread-B:job-2"] = {
            "job_id": "job-2",
            "progress": 0.95,
            "status": "running",
            "elapsed_seconds": 1799.5,
            "thread_id": "thread-B",
            "current_wave": 0,
            "total_waves": 0,
            "skill": "",
        }
        result = RippleService.get_thread_progress("thread-B")
        # 超时残留被过滤——不再返回，前端不会被钉在 95%
        assert result == {}
        assert "thread-B:job-2" not in RippleService._progress_store
