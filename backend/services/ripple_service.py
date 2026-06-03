"""Ripple CAS service with connection pooling, retry, health check, and fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel

from backend.config.settings import Settings

logger = logging.getLogger("xhs_growth.services.ripple")


class RippleTimeoutError(TimeoutError):
    """Ripple 模拟超时 — 携带 job_id 以便后续取消或恢复"""

    def __init__(self, job_id: str, max_wait: float):
        self.job_id = job_id
        self.max_wait = max_wait
        super().__init__(f"Ripple simulation {job_id} did not complete within {max_wait}s")


class RecoveryStatus(BaseModel):
    """Ripple 模拟恢复状态 — 支持未来后台轮询扩展"""

    job_id: str
    status: str  # "completed", "running", "timed_out", "failed", "not_found"
    result: dict[str, Any] | None = None
    error: str = ""


class RippleHealthStatus(BaseModel):
    """Ripple 服务健康状态"""

    is_healthy: bool = False
    last_check: str = ""
    latency_ms: float = 0.0
    error: str = ""
    reason: str = ""  # "disabled", "unreachable", "error", ""


class RippleService:
    """Ripple CAS 服务封装

    特性：
    - 连接池：共享 AsyncClient 实例
    - 重试：失败自动重试 (max_retries=3)
    - 健康检查：启动时检测服务可用性
    - 降级策略：服务不可用时返回默认预测
    """

    _instance: RippleService | None = None
    _client: httpx.AsyncClient | None = None
    _health_status: RippleHealthStatus = RippleHealthStatus()

    def __new__(cls) -> RippleService:
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @classmethod
    def get_instance(cls) -> RippleService:
        """获取服务实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _get_config(self) -> dict[str, Any]:
        """读取配置"""
        s = Settings()
        return {
            "base_url": s.ripple.base_url,
            "api_token": s.ripple.api_token,
            "timeout": s.ripple.request_timeout,
            "enabled": s.ripple.enabled,
        }

    def _get_headers(self) -> dict[str, str]:
        """构建请求头"""
        config = self._get_config()
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if config["api_token"]:
            headers["Authorization"] = f"Bearer {config['api_token']}"
        return headers

    async def _get_client(self) -> httpx.AsyncClient:
        """获取共享 AsyncClient（连接池）"""
        if self._client is None or self._client.is_closed:
            config = self._get_config()
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(config["timeout"], connect=10.0),
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                headers=self._get_headers(),
            )
        return self._client

    async def close(self) -> None:
        """关闭连接"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    # ── 健康检查 ──

    async def health_check(self) -> RippleHealthStatus:
        """检测 Ripple 服务可用性"""
        config = self._get_config()

        if not config["enabled"]:
            self._health_status = RippleHealthStatus(
                is_healthy=False,
                last_check="disabled",
                error="Ripple is disabled in settings",
                reason="disabled",
            )
            return self._health_status

        try:
            client = await self._get_client()
            import time

            start = time.time()

            # 尝试访问健康端点或根路径
            resp = await client.get(f"{config['base_url']}/healthz", timeout=5.0)

            latency = (time.time() - start) * 1000

            if resp.status_code == 200:
                self._health_status = RippleHealthStatus(
                    is_healthy=True, last_check="ok", latency_ms=latency, reason=""
                )
                logger.info(f"Ripple health check passed: {latency:.0f}ms")
            else:
                self._health_status = RippleHealthStatus(
                    is_healthy=False,
                    last_check="error",
                    error=f"HTTP {resp.status_code}",
                    reason="unreachable",
                )
                logger.warning(f"Ripple health check failed: HTTP {resp.status_code}")

        except httpx.ConnectError as e:
            self._health_status = RippleHealthStatus(
                is_healthy=False, last_check="connect_error", error=str(e), reason="unreachable"
            )
            logger.warning(f"Ripple service not reachable: {e}")

        except Exception as e:
            self._health_status = RippleHealthStatus(
                is_healthy=False, last_check="error", error=str(e), reason="error"
            )
            logger.error(f"Ripple health check error: {e}")

        return self._health_status

    def is_healthy(self) -> bool:
        """检查服务是否健康"""
        return self._health_status.is_healthy

    # ── 重试机制 ──

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        json_data: dict | None = None,
        max_retries: int = 3,
        retry_delay: float = 1.0,
    ) -> dict[str, Any]:
        """带重试的请求"""
        client = await self._get_client()

        for attempt in range(max_retries):
            try:
                if method == "POST":
                    resp = await client.post(url, json=json_data)
                else:
                    resp = await client.get(url)

                if resp.status_code >= 500 and attempt < max_retries - 1:
                    # 服务器错误，重试
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue

                resp.raise_for_status()
                return resp.json()

            except httpx.HTTPStatusError as e:
                if e.response.status_code < 500:
                    # 客户端错误，不重试
                    raise
                if attempt < max_retries - 1:
                    logger.warning(f"Ripple request failed (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                raise

            except httpx.ConnectError as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Ripple connection failed (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(retry_delay * (attempt + 1))
                    continue
                raise

            except Exception as e:
                logger.error(f"Ripple request error: {e}")
                raise

        return {"error": "max_retries_exceeded"}

    # ── 降级策略 ──

    def _default_spread_prediction(self) -> dict[str, Any]:
        """默认传播预测（降级时使用）"""
        reason = self._health_status.reason or "unreachable"
        if reason == "disabled":
            message = "Ripple is disabled"
        else:
            message = "Service unavailable, using default prediction"
        return {
            "ripple_prediction": {
                "estimated_reach": 0,
                "estimated_engagement": 0,
                "viral_probability": 0.0,
                "phase": "unknown",
                "confidence": 0.0,
                "key_influencers": [],
                "spread_path": [],
            },
            "ripple_fallback": True,
            "ripple_reason": reason,
            "ripple_message": message,
        }

    def _default_pmf_result(self) -> dict[str, Any]:
        """默认 PMF 结果（降级时使用）"""
        reason = self._health_status.reason or "unreachable"
        if reason == "disabled":
            message = "Ripple is disabled"
        else:
            message = "Service unavailable, using default PMF"
        return {
            "ripple_pmf": {
                "pmf_score": 0.0,
                "risk_factors": ["Ripple service unavailable"],
                "improvement_strategies": [],
                "market_segment": {},
                "confidence": 0.0,
            },
            "ripple_fallback": True,
            "ripple_reason": reason,
            "ripple_message": message,
        }

    # ── 高级 API ──

    async def predict_spread(
        self,
        topic: str,
        content_type: str = "图文笔记",
        tags: list[str] | None = None,
        tone: str = "真诚种草",
        description: str = "",
        max_waves: int = 8,
        simulation_horizon: str = "48h",
        use_fallback: bool = True,
        max_wait: float = 1800.0,
    ) -> dict[str, Any]:
        """预测内容传播效果

        Args:
            use_fallback: 服务不可用时是否使用默认值
            max_wait: 最大等待时间（秒），传递给 submit_and_wait
        """
        if tags is None:
            tags = []
        config = self._get_config()

        if not config["enabled"] or not self.is_healthy():
            if use_fallback:
                reason = (
                    "disabled"
                    if not config["enabled"]
                    else self._health_status.reason or "unreachable"
                )
                logger.info(f"Ripple unavailable (reason={reason}), using fallback prediction")
                return self._default_spread_prediction()
            return {"error": "Ripple service unavailable"}

        try:
            event = {
                "topic": topic,
                "content_type": content_type,
                "tags": tags,
                "tone": tone,
                "description": description,
            }
            request_body = {
                "skill": "social-media",
                "platform": "xiaohongshu",
                "event": event,
                "max_waves": max_waves,
                "simulation_horizon": simulation_horizon,
            }

            result = await self.submit_and_wait(request_body, max_wait=max_wait)
            return self._parse_spread_result(result)

        except RippleTimeoutError:
            # 让 RippleTimeoutError 传播到调用方，以便保存 job_id 并尝试取消
            raise
        except Exception as e:
            logger.error(f"Ripple spread prediction failed: {e}")
            if use_fallback:
                return self._default_spread_prediction()
            return {"error": str(e)}

    async def validate_pmf(
        self,
        product_name: str,
        category: str,
        description: str,
        differentiators: list[str] | None = None,
        use_fallback: bool = True,
        max_wait: float = 1800.0,
    ) -> dict[str, Any]:
        """验证产品市场契合度

        Args:
            max_wait: 最大等待时间（秒），传递给 submit_and_wait
        """
        if differentiators is None:
            differentiators = []
        config = self._get_config()

        if not config["enabled"] or not self.is_healthy():
            if use_fallback:
                reason = (
                    "disabled"
                    if not config["enabled"]
                    else self._health_status.reason or "unreachable"
                )
                logger.info(f"Ripple unavailable (reason={reason}), using fallback PMF")
                return self._default_pmf_result()
            return {"error": "Ripple service unavailable"}

        try:
            event = {
                "name": product_name,
                "category": category,
                "description": description,
                "differentiators": differentiators,
            }
            request_body = {
                "skill": "pmf-validation",
                "channel": "content-seeding",
                "vertical": "fmcg",
                "platform": "xiaohongshu",
                "event": event,
            }

            result = await self.submit_and_wait(request_body, max_wait=max_wait)
            return self._parse_pmf_result(result)

        except RippleTimeoutError:
            # 让 RippleTimeoutError 传播到调用方，以便保存 job_id 并尝试取消
            raise
        except Exception as e:
            logger.error(f"Ripple PMF validation failed: {e}")
            if use_fallback:
                return self._default_pmf_result()
            return {"error": str(e)}

    async def submit_simulation(self, request_body: dict[str, Any]) -> dict[str, Any]:
        """提交模拟任务，返回含 job_id 的响应"""
        config = self._get_config()
        return await self._request_with_retry(
            "POST",
            f"{config['base_url']}/v1/simulations",
            json_data=request_body,
        )

    async def get_simulation_status(self, job_id: str) -> dict[str, Any]:
        """获取模拟任务状态"""
        config = self._get_config()
        return await self._request_with_retry(
            "GET",
            f"{config['base_url']}/v1/simulations/{job_id}",
        )

    async def wait_for_completion(
        self,
        job_id: str,
        poll_interval: float = 10.0,
        max_wait: float = 1800.0,
    ) -> dict[str, Any]:
        """轮询等待模拟完成

        Args:
            job_id: 模拟任务 ID
            poll_interval: 轮询间隔（秒）
            max_wait: 最大等待时间（秒）

        Returns:
            最终的模拟状态响应

        Raises:
            RippleTimeoutError: 超过最大等待时间（携带 job_id）
            RuntimeError: 模拟失败
        """
        elapsed = 0.0
        while elapsed < max_wait:
            status = await self.get_simulation_status(job_id)
            state = status.get("status", "").lower()

            if state in ("completed", "done", "finished"):
                logger.info(f"Ripple simulation {job_id} completed after {elapsed:.0f}s")
                return status
            if state in ("failed", "error"):
                error_msg = status.get("error", "Unknown simulation error")
                raise RuntimeError(f"Ripple simulation {job_id} failed: {error_msg}")

            logger.debug(f"Ripple simulation {job_id} status: {state}, waiting {poll_interval}s...")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        raise RippleTimeoutError(job_id, max_wait)

    async def submit_and_wait(
        self,
        request_body: dict[str, Any],
        poll_interval: float = 10.0,
        max_wait: float = 1800.0,
    ) -> dict[str, Any]:
        """提交模拟并等待完成，返回完整结果

        Returns:
            包含 job_id 和完整 output 的结果字典
        """
        submit_result = await self.submit_simulation(request_body)
        job_id = submit_result.get("job_id", submit_result.get("id", ""))

        if not job_id:
            # 同步完成（非异步模式）
            return submit_result

        await self.wait_for_completion(job_id, poll_interval, max_wait)
        result = await self.get_result(job_id)
        # 确保 job_id 在结果中
        result.setdefault("job_id", job_id)
        return result

    async def get_result(self, job_id: str) -> dict[str, Any]:
        """获取模拟结果"""
        config = self._get_config()

        try:
            return await self._request_with_retry(
                "GET",
                f"{config['base_url']}/v1/simulations/{job_id}/artifacts/output-json",
            )
        except Exception as e:
            return {"error": str(e)}

    async def get_report(self, job_id: str) -> dict[str, Any]:
        """生成模拟报告"""
        config = self._get_config()

        try:
            payload = {
                "rounds": [
                    {"label": "summary", "system_prompt": "", "extra_user_context": ""},
                    {"label": "diagnosis", "system_prompt": "", "extra_user_context": ""},
                ],
                "role": "omniscient",
            }
            return await self._request_with_retry(
                "POST",
                f"{config['base_url']}/v1/simulations/{job_id}/report",
                json_data=payload,
            )
        except Exception as e:
            return {"error": str(e)}

    # ── 取消与恢复 ──

    async def cancel_simulation(self, job_id: str) -> dict[str, Any]:
        """尝试取消 Ripple 模拟任务

        乐观尝试 DELETE /v1/simulations/{job_id}，对 404/405/网络错误做优雅降级。

        Returns:
            {"cancelled": bool, "job_id": str, "status": str, "error"?: str}
        """
        config = self._get_config()
        url = f"{config['base_url']}/v1/simulations/{job_id}"

        try:
            client = await self._get_client()
            resp = await client.delete(url)

            if resp.status_code in (200, 204):
                logger.info(f"Ripple simulation {job_id} cancelled successfully")
                return {"cancelled": True, "job_id": job_id, "status": "cancelled"}

            if resp.status_code == 404:
                logger.warning(f"Ripple simulation {job_id} not found on cancel")
                return {"cancelled": False, "job_id": job_id, "status": "not_found"}

            if resp.status_code == 405:
                logger.warning(f"Ripple server does not support cancel for {job_id}")
                return {"cancelled": False, "job_id": job_id, "status": "not_supported"}

            # 其他非成功状态码
            logger.warning(
                f"Ripple cancel returned unexpected status {resp.status_code} for {job_id}"
            )
            return {
                "cancelled": False,
                "job_id": job_id,
                "status": "error",
                "error": f"HTTP {resp.status_code}",
            }

        except httpx.ConnectError as e:
            logger.warning(f"Ripple cancel failed (connection error) for {job_id}: {e}")
            return {"cancelled": False, "job_id": job_id, "status": "error", "error": str(e)}

        except Exception as e:
            logger.warning(f"Ripple cancel failed for {job_id}: {e}")
            return {"cancelled": False, "job_id": job_id, "status": "error", "error": str(e)}

    async def recover_result(self, job_id: str) -> RecoveryStatus:
        """恢复超时模拟的结果 — 检查任务状态，若已完成则获取结果

        返回结构化的 RecoveryStatus，支持未来后台轮询扩展：
        - status="completed": result 字段包含完整数据
        - status="running": 任务仍在执行，可稍后重试
        - status="failed": 任务失败，error 字段包含原因
        - status="not_found": 任务不存在

        Args:
            job_id: 模拟任务 ID

        Returns:
            RecoveryStatus 结构化恢复状态
        """
        try:
            status_resp = await self.get_simulation_status(job_id)
            state = status_resp.get("status", "").lower()

            if state in ("completed", "done", "finished"):
                result = await self.get_result(job_id)
                return RecoveryStatus(
                    job_id=job_id,
                    status="completed",
                    result=result,
                )

            if state in ("failed", "error"):
                error_msg = status_resp.get("error", "Unknown simulation error")
                return RecoveryStatus(
                    job_id=job_id,
                    status="failed",
                    error=error_msg,
                )

            if state in ("running", "pending", "submitted", "in_progress"):
                return RecoveryStatus(
                    job_id=job_id,
                    status="running",
                )

            # 未知状态视为运行中
            logger.warning(f"Ripple simulation {job_id} has unknown status: {state}")
            return RecoveryStatus(
                job_id=job_id,
                status="running",
            )

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return RecoveryStatus(
                    job_id=job_id,
                    status="not_found",
                    error=f"Simulation {job_id} not found",
                )
            return RecoveryStatus(
                job_id=job_id,
                status="failed",
                error=str(e),
            )

        except Exception as e:
            return RecoveryStatus(
                job_id=job_id,
                status="failed",
                error=str(e),
            )

    # ── 结果解析 ──

    def _parse_spread_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """解析传播预测结果"""
        if "error" in result:
            return {"ripple_prediction": None, "ripple_error": result["error"]}

        output = result.get("output", result)
        job_id = result.get("job_id", result.get("id", ""))
        metrics = output.get("metrics", output.get("summary", {}))
        phase_analysis = output.get("phase_analysis", output.get("dynamics", {}))

        return {
            "ripple_job_id": job_id,
            "ripple_prediction": {
                "estimated_reach": metrics.get("estimated_reach", metrics.get("total_reach", 0)),
                "estimated_engagement": metrics.get(
                    "estimated_engagement", metrics.get("total_engagement", 0)
                ),
                "viral_probability": metrics.get(
                    "viral_probability",
                    metrics.get("outbreak_probability", 0.0),
                ),
                "phase": phase_analysis.get(
                    "phase", phase_analysis.get("dominant_phase", "unknown")
                ),
                "confidence": metrics.get("confidence", 0.0),
                "key_influencers": metrics.get("key_influencers", []),
                "spread_path": phase_analysis.get("spread_path", []),
            },
        }

    def _parse_pmf_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """解析 PMF 验证结果"""
        if "error" in result:
            return {"ripple_pmf": None, "ripple_error": result["error"]}

        output = result.get("output", result)
        job_id = result.get("job_id", result.get("id", ""))

        return {
            "ripple_job_id": job_id,
            "ripple_pmf": {
                "pmf_score": output.get("pmf_score", output.get("score", 0.0)),
                "risk_factors": output.get("risk_factors", []),
                "improvement_strategies": output.get("improvement_strategies", []),
                "market_segment": output.get("market_segment", {}),
                "confidence": output.get("confidence", 0.0),
            },
        }
