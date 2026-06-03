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
            "workflow_timeout": s.ripple.workflow_timeout,
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

    def _emit_progress(
        self,
        job_id: str,
        status: dict[str, Any],
        elapsed_seconds: float,
        thread_id: str,
    ) -> None:
        """通过 EventBus 推送 Ripple 模拟进度事件"""
        from backend.realtime import EventBusService
        from backend.realtime.events import EventType

        bus = EventBusService.get_instance()
        payload = {
            "job_id": job_id,
            "current_wave": status.get("current_wave", 0),
            "total_waves": status.get("total_waves", status.get("max_waves", 0)),
            "progress": float(status.get("progress", 0)),
            "elapsed_seconds": round(elapsed_seconds, 1),
            "status": status.get("status", "unknown"),
        }
        bus.emit(EventType.RIPPLE_PROGRESS, thread_id=thread_id, payload=payload)

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
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """预测内容传播效果

        Args:
            use_fallback: 服务不可用时是否使用默认值
            max_wait: 最大等待时间（秒），传递给 submit_and_wait
            thread_id: 关联的工作流线程 ID，用于推送进度事件
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

            result = await self.submit_and_wait(
                request_body, max_wait=max_wait, thread_id=thread_id,
            )
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
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """验证产品市场契合度

        Args:
            max_wait: 最大等待时间（秒），传递给 submit_and_wait
            thread_id: 关联的工作流线程 ID，用于推送进度事件
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
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """轮询等待模拟完成

        Args:
            job_id: 模拟任务 ID
            poll_interval: 轮询间隔（秒）
            max_wait: 最大等待时间（秒）
            thread_id: 关联的工作流线程 ID，用于推送进度事件

        Returns:
            最终的模拟状态响应

        Raises:
            RippleTimeoutError: 超过最大等待时间（携带 job_id）
            RuntimeError: 模拟失败
        """
        import time as _time

        start_time = _time.monotonic()
        elapsed = 0.0
        while elapsed < max_wait:
            status = await self.get_simulation_status(job_id)
            state = status.get("status", "").lower()

            # Push progress event via EventBus
            if thread_id:
                self._emit_progress(job_id, status, elapsed, thread_id)

            if state in ("completed", "done", "finished"):
                logger.info(f"Ripple simulation {job_id} completed after {elapsed:.0f}s")
                return status
            if state in ("failed", "error", "timed_out", "timeout"):
                error_msg = status.get("error", "Unknown simulation error")
                raise RuntimeError(f"Ripple simulation {job_id} failed: {error_msg}")

            logger.debug(f"Ripple simulation {job_id} status: {state}, waiting {poll_interval}s...")
            await asyncio.sleep(poll_interval)
            elapsed = _time.monotonic() - start_time

        raise RippleTimeoutError(job_id, max_wait)

    async def submit_and_wait(
        self,
        request_body: dict[str, Any],
        poll_interval: float = 10.0,
        max_wait: float = 1800.0,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """提交模拟并等待完成，返回完整结果

        Args:
            thread_id: 关联的工作流线程 ID，用于推送进度事件

        Returns:
            包含 job_id 和完整 output 的结果字典
        """
        submit_result = await self.submit_simulation(request_body)
        job_id = submit_result.get("job_id", submit_result.get("id", ""))

        if not job_id:
            return submit_result

        await self.wait_for_completion(job_id, poll_interval, max_wait, thread_id=thread_id)
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

        优先使用 Ripple 当前的两步取消协议，旧服务不支持时回退到 DELETE。

        Returns:
            {"cancelled": bool, "job_id": str, "status": str, "error"?: str}
        """
        config = self._get_config()
        url = f"{config['base_url']}/v1/simulations/{job_id}"

        async def _legacy_delete_cancel(client: httpx.AsyncClient) -> dict[str, Any]:
            resp = await client.delete(url)

            if resp.status_code in (200, 204):
                logger.info(f"Ripple simulation {job_id} cancelled successfully")
                return {"cancelled": True, "job_id": job_id, "status": "cancelled"}

            if resp.status_code == 404:
                logger.warning(f"Ripple simulation {job_id} not found on cancel")
                return {"cancelled": False, "job_id": job_id, "status": "not_found"}

            if resp.status_code == 405:
                logger.warning(f"Ripple server does not support legacy cancel for {job_id}")
                return {"cancelled": False, "job_id": job_id, "status": "not_supported"}

            logger.warning(
                f"Ripple cancel returned unexpected status {resp.status_code} for {job_id}"
            )
            return {
                "cancelled": False,
                "job_id": job_id,
                "status": "error",
                "error": f"HTTP {resp.status_code}",
            }

        try:
            client = await self._get_client()
            request_resp = await client.post(f"{url}/cancel-request")

            if request_resp.status_code in (200, 201, 202):
                payload = request_resp.json()
                token = payload.get("cancel_token")
                if not token:
                    return {
                        "cancelled": False,
                        "job_id": job_id,
                        "status": "error",
                        "error": "cancel token missing",
                    }

                confirm_resp = await client.post(
                    f"{url}/cancel-confirm",
                    json={"cancel_token": token},
                )
                if confirm_resp.status_code in (200, 201, 202, 204):
                    confirm_payload = {}
                    if confirm_resp.status_code != 204:
                        try:
                            confirm_payload = confirm_resp.json()
                        except ValueError:
                            confirm_payload = {}
                    status = str(confirm_payload.get("status") or "cancelling")
                    logger.info(f"Ripple simulation {job_id} cancel accepted: {status}")
                    return {
                        "cancelled": True,
                        "job_id": job_id,
                        "status": status,
                    }

                return {
                    "cancelled": False,
                    "job_id": job_id,
                    "status": "error",
                    "error": f"cancel confirm HTTP {confirm_resp.status_code}",
                }

            if request_resp.status_code == 404:
                logger.warning(f"Ripple simulation {job_id} not found on cancel")
                return {"cancelled": False, "job_id": job_id, "status": "not_found"}

            if request_resp.status_code == 405:
                return await _legacy_delete_cancel(client)

            if request_resp.status_code == 409:
                return {
                    "cancelled": False,
                    "job_id": job_id,
                    "status": "not_cancellable",
                    "error": request_resp.text,
                }

            return {
                "cancelled": False,
                "job_id": job_id,
                "status": "error",
                "error": f"cancel request HTTP {request_resp.status_code}",
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

            if state in ("timed_out", "timeout"):
                error_msg = status_resp.get("error", "Ripple simulation timed out")
                return RecoveryStatus(
                    job_id=job_id,
                    status="timed_out",
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

    @staticmethod
    def _unwrap_result_output(result: dict[str, Any]) -> dict[str, Any]:
        """Return the actual Ripple artifact payload from known response envelopes."""
        output = result.get("output", result)
        if isinstance(output, dict) and isinstance(output.get("result"), dict):
            output = output["result"]
        return output if isinstance(output, dict) else {}

    @staticmethod
    def _result_job_id(result: dict[str, Any], output: dict[str, Any]) -> str:
        return str(
            result.get("job_id")
            or result.get("id")
            or result.get("ripple_job_id")
            or output.get("job_id")
            or output.get("id")
            or ""
        )

    @staticmethod
    def _clamp_score(value: float) -> float:
        return max(0.0, min(1.0, value))

    @classmethod
    def _numeric_score(cls, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int | float):
            score = float(value)
            if score > 1.0 and score <= 100.0:
                score /= 100.0
            return cls._clamp_score(score)
        if isinstance(value, str):
            raw = value.strip().lower()
            if not raw:
                return None
            try:
                score = float(raw.rstrip("%"))
                if raw.endswith("%") or score > 1.0:
                    score /= 100.0
                return cls._clamp_score(score)
            except ValueError:
                return None
        return None

    @classmethod
    def _confidence_to_float(cls, value: Any) -> float:
        numeric = cls._numeric_score(value)
        if numeric is not None:
            return numeric

        text = str(value or "").strip().lower()
        mapping = {
            "very high": 0.9,
            "high": 0.8,
            "strong": 0.8,
            "medium": 0.6,
            "moderate": 0.6,
            "mid": 0.6,
            "low": 0.35,
            "very low": 0.2,
            "weak": 0.25,
            "高": 0.8,
            "中": 0.6,
            "低": 0.35,
        }
        return mapping.get(text, 0.0)

    @staticmethod
    def _phase_text(*values: Any) -> str:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def _probability_from_phase(cls, *values: Any) -> float:
        text = " ".join(str(value).lower() for value in values if value)
        if not text:
            return 0.0
        if any(token in text for token in ("explosion", "viral", "outbreak", "burst", "爆发")):
            return 0.75
        if any(token in text for token in ("growth", "growing", "rising", "expansion", "增长", "上升")):
            return 0.55
        if any(token in text for token in ("stable", "plateau", "ordered", "稳定", "平台")):
            return 0.42
        if any(token in text for token in ("seed", "seeding", "nascent", "萌芽", "种子")):
            return 0.28
        if any(token in text for token in ("decline", "cooling", "drop", "衰退", "下降")):
            return 0.18
        return 0.0

    @classmethod
    def _pmf_score_from_phase(cls, *values: Any) -> float:
        text = " ".join(str(value).lower() for value in values if value)
        if not text:
            return 0.0
        if any(token in text for token in ("explosion", "viral", "outbreak", "burst", "爆发")):
            return 0.78
        if any(token in text for token in ("growth", "growing", "rising", "expansion", "增长", "上升")):
            return 0.68
        if any(token in text for token in ("stable", "plateau", "ordered", "稳定", "平台")):
            return 0.6
        if any(token in text for token in ("seed", "seeding", "nascent", "萌芽", "种子")):
            return 0.48
        if any(token in text for token in ("decline", "cooling", "drop", "衰退", "下降")):
            return 0.3
        return 0.0

    @staticmethod
    def _text_from_mapping(item: dict[str, Any]) -> str:
        for key in (
            "message",
            "recommendation",
            "strategy",
            "action",
            "risk",
            "reason",
            "description",
            "turning_point",
            "event",
            "label",
            "phase",
            "name",
        ):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    @classmethod
    def _text_items(cls, value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value] if value.strip() else []
        if isinstance(value, dict):
            if isinstance(value.get("items"), list):
                return cls._text_items(value["items"])
            text = cls._text_from_mapping(value)
            return [text] if text else []
        if isinstance(value, list):
            items: list[str] = []
            for item in value:
                if isinstance(item, str) and item.strip():
                    items.append(item.strip())
                elif isinstance(item, dict):
                    text = cls._text_from_mapping(item)
                    if text:
                        items.append(text)
            return items
        return []

    @staticmethod
    def _key_influencers(agent_insights: Any, metrics: dict[str, Any]) -> list[Any]:
        existing = metrics.get("key_influencers")
        if isinstance(existing, list):
            return existing

        if not isinstance(agent_insights, dict):
            return []
        stars = agent_insights.get("stars")
        if isinstance(stars, list):
            return stars
        if isinstance(stars, dict):
            influencers: list[dict[str, Any]] = []
            for name, payload in stars.items():
                item: dict[str, Any] = {"name": name}
                if isinstance(payload, dict):
                    item.update(payload)
                elif payload is not None:
                    item["value"] = payload
                influencers.append(item)
            return influencers
        return []

    @staticmethod
    def _add_relative_fields(target: dict[str, Any], relative: Any) -> None:
        if not isinstance(relative, dict) or not relative:
            return
        target["relative_estimate"] = relative
        for key, value in relative.items():
            if key.endswith("_relative") and value not in (None, ""):
                target[key] = value

    def _parse_spread_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """解析传播预测结果"""
        if result.get("ripple_fallback"):
            return result
        if "error" in result and "ripple_prediction" not in result:
            return {"ripple_prediction": None, "ripple_error": result["error"]}
        if isinstance(result.get("ripple_prediction"), dict):
            output = self._unwrap_result_output(result)
            return {
                "ripple_job_id": self._result_job_id(result, output),
                "ripple_prediction": result["ripple_prediction"],
            }

        output = self._unwrap_result_output(result)
        job_id = self._result_job_id(result, output)
        metrics = output.get("metrics", output.get("summary", {}))
        if not isinstance(metrics, dict):
            metrics = {}
        phase_analysis = output.get("phase_analysis", output.get("dynamics", {}))
        if not isinstance(phase_analysis, dict):
            phase_analysis = {}
        prediction = output.get("prediction", {})
        if not isinstance(prediction, dict):
            prediction = {}
        relative = prediction.get("relative_estimate", {})
        observation = output.get("observation", {})
        if not isinstance(observation, dict):
            observation = {}
        phase_vector = observation.get("phase_vector", {})
        if not isinstance(phase_vector, dict):
            phase_vector = {}

        if not any((metrics, phase_analysis, prediction, relative, phase_vector)):
            logger.warning(f"Ripple spread result has no prediction data: {list(result.keys())}")
            return {
                "ripple_job_id": job_id,
                "ripple_prediction": None,
                "ripple_error": "No prediction data in response",
            }

        viral_probability = self._numeric_score(
            metrics.get("viral_probability", metrics.get("outbreak_probability"))
        )
        score_source = "metrics"
        if viral_probability is None:
            score_phase = (
                prediction.get("verdict")
                or phase_vector.get("heat")
                or phase_analysis.get("phase")
                or phase_analysis.get("dominant_phase")
            )
            viral_probability = self._probability_from_phase(score_phase)
            score_source = "derived_from_verdict"

        phase = self._phase_text(
            phase_analysis.get("phase"),
            phase_analysis.get("dominant_phase"),
            phase_vector.get("heat"),
            prediction.get("verdict"),
            "unknown",
        )
        confidence = self._confidence_to_float(
            metrics.get("confidence", relative.get("confidence") if isinstance(relative, dict) else None)
        )

        parsed_prediction: dict[str, Any] = {
            "viral_probability": viral_probability,
            "phase": phase,
            "confidence": confidence,
            "key_influencers": self._key_influencers(output.get("agent_insights"), metrics),
            "spread_path": phase_analysis.get("spread_path", output.get("timeline", [])),
        }

        estimated_reach = metrics.get("estimated_reach", metrics.get("total_reach"))
        if estimated_reach is not None:
            parsed_prediction["estimated_reach"] = estimated_reach
        estimated_engagement = metrics.get("estimated_engagement", metrics.get("total_engagement"))
        if estimated_engagement is not None:
            parsed_prediction["estimated_engagement"] = estimated_engagement

        self._add_relative_fields(parsed_prediction, relative)
        if prediction.get("impact"):
            parsed_prediction["prediction_summary"] = prediction["impact"]
        if prediction.get("verdict"):
            parsed_prediction["verdict"] = prediction["verdict"]
        if phase_vector:
            parsed_prediction["phase_vector"] = phase_vector
        if output.get("total_waves") is not None:
            parsed_prediction["total_waves"] = output["total_waves"]
        if score_source != "metrics":
            parsed_prediction["score_source"] = score_source

        return {
            "ripple_job_id": job_id,
            "ripple_prediction": parsed_prediction,
        }

    def _parse_pmf_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """解析 PMF 验证结果"""
        if result.get("ripple_fallback"):
            return result
        if "error" in result and "ripple_pmf" not in result:
            return {"ripple_pmf": None, "ripple_error": result["error"]}
        if isinstance(result.get("ripple_pmf"), dict):
            output = self._unwrap_result_output(result)
            return {
                "ripple_job_id": self._result_job_id(result, output),
                "ripple_pmf": result["ripple_pmf"],
            }

        output = self._unwrap_result_output(result)
        job_id = self._result_job_id(result, output)
        prediction = output.get("prediction", {})
        if not isinstance(prediction, dict):
            prediction = {}
        relative = prediction.get("relative_estimate", {})
        observation = output.get("observation", {})
        if not isinstance(observation, dict):
            observation = {}
        phase_vector = observation.get("phase_vector", {})
        if not isinstance(phase_vector, dict):
            phase_vector = {}

        score = self._numeric_score(output.get("pmf_score", output.get("score")))
        score_source = "metrics"
        if score is None:
            score_phase = prediction.get("verdict") or phase_vector.get("heat")
            score = self._pmf_score_from_phase(score_phase)
            score_source = "derived_from_verdict"

        risk_factors = self._text_items(output.get("risk_factors"))
        if not risk_factors:
            risk_factors = self._text_items(output.get("bifurcation_points"))

        improvement_strategies = self._text_items(output.get("improvement_strategies"))
        if not improvement_strategies:
            improvement_strategies = self._text_items(
                observation.get("topology_recommendations")
            )

        confidence = self._confidence_to_float(
            output.get("confidence", relative.get("confidence") if isinstance(relative, dict) else None)
        )
        market_segment = output.get("market_segment", {})
        agent_insights = output.get("agent_insights")
        if not market_segment and isinstance(agent_insights, dict):
            market_segment = agent_insights.get("seas", {})

        parsed_pmf: dict[str, Any] = {
            "pmf_score": score,
            "risk_factors": risk_factors,
            "improvement_strategies": improvement_strategies,
            "market_segment": market_segment if isinstance(market_segment, dict) else {},
            "confidence": confidence,
        }
        self._add_relative_fields(parsed_pmf, relative)
        if prediction.get("impact"):
            parsed_pmf["prediction_summary"] = prediction["impact"]
        if prediction.get("verdict"):
            parsed_pmf["verdict"] = prediction["verdict"]
        phase = self._phase_text(phase_vector.get("heat"), prediction.get("verdict"))
        if phase:
            parsed_pmf["phase"] = phase
        if phase_vector:
            parsed_pmf["phase_vector"] = phase_vector
        if output.get("total_waves") is not None:
            parsed_pmf["total_waves"] = output["total_waves"]
        if score_source != "metrics":
            parsed_pmf["score_source"] = score_source

        return {
            "ripple_job_id": job_id,
            "ripple_pmf": parsed_pmf,
        }
