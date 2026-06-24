"""Ripple CAS service with connection pooling, retry, health check, and fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel

from backend.config.settings import Settings

logger = logging.getLogger("xhs_growth.services.ripple")

SSE_STALE_THRESHOLD = 15.0  # Seconds before treating SSE progress as stale


class RippleTimeoutError(TimeoutError):
    """Ripple 模拟超时 — 携带 job_id 以便后续取消或恢复"""

    def __init__(self, job_id: str, max_wait: float):
        self.job_id = job_id
        self.max_wait = max_wait
        super().__init__(f"Ripple simulation {job_id} did not complete within {max_wait}s")


# ponytail: 残留进度过期阈值——max_wait(1800s) 的 94%。超过仍 running 视为
# 超时未收尾的历史残留，get_thread_progress 据此清理（兜底主修法之外的旧数据）
_STALE_PROGRESS_SECS = 1700.0


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
    prediction_quality: dict[str, Any] = {}  # /v1/health/prediction-quality checks


class RippleService:
    """Ripple CAS 服务封装

    特性：
    - 连接池：共享 AsyncClient 实例
    - 重试：失败自动重试 (max_retries=3)
    - 健康检查：启动时检测服务可用性
    - 降级策略：服务不可用时返回默认预测
    - 自动恢复：请求成功时恢复健康状态，后台定期探测
    - 连接池重建：服务恢复时关闭旧连接池，确保 DNS 重解析
    """

    _instance: RippleService | None = None
    _client: httpx.AsyncClient | None = None
    _health_status: RippleHealthStatus = RippleHealthStatus()
    _bg_task: asyncio.Task | None = None
    # Track active simulation progress per (thread_id, job_id)
    _progress_store: dict[str, dict[str, Any]] = {}

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

    def _build_llm_config(self) -> dict[str, Any] | None:
        """从 Settings 构建 Ripple LLM 配置（双保险：即使容器缺 llm_config.yaml 也能工作）"""
        s = Settings()
        if not (s.ripple.llm_model_platform and s.ripple.llm_model_name and s.ripple.llm_api_key):
            return None
        cfg: dict[str, Any] = {
            "model_platform": s.ripple.llm_model_platform,
            "model_name": s.ripple.llm_model_name,
            "api_key": s.ripple.llm_api_key,
        }
        if s.ripple.llm_url:
            cfg["url"] = s.ripple.llm_url
        return {"_default": cfg}

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
                # Also check prediction-quality subsystem (non-blocking)
                pq_checks: dict[str, Any] = {}
                try:
                    pq_resp = await client.get(
                        f"{config['base_url']}/v1/health/prediction-quality", timeout=3.0,
                    )
                    if pq_resp.status_code == 200:
                        pq_data = pq_resp.json()
                        pq_checks = pq_data.get("checks", {})
                except Exception:
                    pass  # Non-critical — older Ripple versions lack this endpoint

                self._health_status = RippleHealthStatus(
                    is_healthy=True, last_check="ok", latency_ms=latency, reason="",
                    prediction_quality=pq_checks,
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

    def _mark_healthy(self) -> None:
        """Mark service as healthy — called on successful request completion."""
        if not self._health_status.is_healthy:
            logger.info("Ripple service recovered — marking healthy and rebuilding connection pool")
            self._health_status = RippleHealthStatus(
                is_healthy=True, last_check="recovered", reason=""
            )
            # Rebuild client: old pool may have stale connections to dead container IP
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._rebuild_client())
            except RuntimeError:
                # No event loop — will rebuild on next _get_client() call
                self._client = None

    def _mark_unreachable(self, error: str = "") -> None:
        """Mark service as unreachable — called when ConnectError exhausts retries."""
        self._health_status = RippleHealthStatus(
            is_healthy=False,
            last_check="connect_error",
            error=error,
            reason="unreachable",
        )
        logger.warning(f"Ripple service marked unreachable: {error}")

    async def _rebuild_client(self) -> None:
        """Close old httpx client and rebuild — ensures fresh DNS + TCP connections."""
        if self._client and not self._client.is_closed:
            try:
                await self._client.aclose()
            except Exception as e:
                logger.debug(f"Error closing old Ripple client: {e}")
        self._client = None
        # Next _get_client() call will create a fresh client with new connections

    async def _probe_before_fallback(self) -> bool:
        """Quick health probe when is_healthy is False.

        Returns True if service recovered, False if still unreachable.
        On recovery, also rebuilds the connection pool.
        """
        if not self._get_config()["enabled"]:
            return False
        prev_healthy = self._health_status.is_healthy
        await self.health_check()
        if self._health_status.is_healthy and not prev_healthy:
            await self._rebuild_client()
        return self._health_status.is_healthy

    # ── Background health check ──

    def start_background_health_check(self, interval_seconds: float = 30.0) -> None:
        """Start a background task that periodically probes Ripple health.

        Safe to call multiple times — stops any previous task first.
        """
        self.stop_background_health_check()
        config = self._get_config()
        if not config["enabled"]:
            return
        self._bg_task = asyncio.create_task(self._health_check_loop(interval_seconds))
        logger.info(f"Ripple background health check started (interval={interval_seconds}s)")

    def stop_background_health_check(self) -> None:
        """Stop the background health check task."""
        if self._bg_task and not self._bg_task.done():
            self._bg_task.cancel()
            logger.info("Ripple background health check stopped")
        self._bg_task = None

    async def _health_check_loop(self, interval_seconds: float) -> None:
        """Periodically check Ripple health. Rebuilds client on recovery."""
        try:
            while True:
                await asyncio.sleep(interval_seconds)
                prev_healthy = self._health_status.is_healthy
                await self.health_check()
                if self._health_status.is_healthy and not prev_healthy:
                    logger.info("Ripple service recovered via background check — rebuilding client")
                    await self._rebuild_client()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Ripple background health check crashed: {e}")

    def _emit_progress(
        self,
        job_id: str,
        progress: float,
        current_wave: int,
        total_waves: int,
        elapsed_seconds: float,
        thread_id: str,
        status: str = "running",
        skill: str = "",
    ) -> None:
        """通过 EventBus 推送 Ripple 模拟进度事件"""
        from backend.realtime import EventBusService
        from backend.realtime.events import EventType

        payload = {
            "job_id": job_id,
            "current_wave": current_wave,
            "total_waves": total_waves,
            "progress": float(progress),
            "elapsed_seconds": round(elapsed_seconds, 1),
            "status": status,
            "skill": skill,
        }
        # Store progress for status API queries
        # ponytail: 终态一律清理 store——超时/失败不收尾会让前端永久卡在估算进度
        key = f"{thread_id}:{job_id}"
        terminal = ("completed", "done", "finished", "timed_out", "timeout", "failed", "error")
        if status in terminal:
            RippleService._progress_store.pop(key, None)
        else:
            RippleService._progress_store[key] = {**payload, "thread_id": thread_id}
        bus = EventBusService.get_instance()
        bus.emit(EventType.RIPPLE_PROGRESS, thread_id=thread_id, payload=payload)

    @classmethod
    def get_thread_progress(cls, thread_id: str) -> dict[str, Any]:
        """Get aggregated Ripple progress for a thread (for status API).

        Returns dict with 'jobs', 'overall_progress', 'active_jobs', 'total_jobs'.
        """
        jobs: dict[str, Any] = {}
        for key, data in list(cls._progress_store.items()):
            if data.get("thread_id") != thread_id:
                continue
            # ponytail: 防御性过期清理——逼近 max_wait 仍 "running" 的条目必然是
            # 超时未收尾的历史残留（实测残留值 ~1799.5s，略低于 max_wait 1800），
            # 剔除并 pop，避免永久卡前端进度条。阈值取 max_wait 的 94%，正常 job
            # 不会跑这么久还停在 running
            is_stale = (
                data.get("status") == "running"
                and float(data.get("elapsed_seconds", 0)) >= _STALE_PROGRESS_SECS
            )
            if is_stale:
                cls._progress_store.pop(key, None)
                continue
            job_id = data["job_id"]
            jobs[job_id] = {k: v for k, v in data.items() if k != "thread_id"}
        if not jobs:
            return {}
        entries = list(jobs.values())
        active = [j for j in entries if j.get("status") not in ("completed", "done", "finished")]
        avg = sum(j.get("progress", 0) for j in entries) / len(entries) if entries else 0
        return {
            "jobs": jobs,
            "overall_progress": avg,
            "active_jobs": len(active),
            "total_jobs": len(entries),
        }

    async def _stream_progress(
        self,
        job_id: str,
        thread_id: str,
        progress_state: dict[str, Any],
        done_event: asyncio.Event,
    ) -> None:
        """Consume Ripple SSE event stream and update progress_state.

        Reads from ``GET /v1/simulations/{job_id}/events`` — each event
        carries ``progress`` (0~1), ``wave``, ``total_waves`` etc.

        On any error (connection refused, timeout, parse failure) the method
        returns silently so that the caller can fall back to time-based
        estimation.
        """
        config = self._get_config()
        url = f"{config['base_url']}/v1/simulations/{job_id}/events"
        headers = self._get_headers()

        try:
            async with (
                httpx.AsyncClient(
                    timeout=httpx.Timeout(30.0, connect=10.0, read=60.0),
                    headers=headers,
                ) as client,
                client.stream("GET", url) as resp,
            ):
                    if resp.status_code != 200:
                        logger.warning(
                            f"Ripple SSE stream returned HTTP {resp.status_code}, falling back"
                        )
                        return

                    event_type = ""
                    async for line in resp.aiter_lines():
                        if done_event.is_set():
                            return

                        line = line.strip()
                        if line.startswith("event:"):
                            event_type = line[len("event:"):].strip()
                        elif line.startswith("data:"):
                            import json as _json

                            data_str = line[len("data:"):].strip()
                            try:
                                payload = _json.loads(data_str)
                            except _json.JSONDecodeError:
                                continue

                            # Lifecycle events signal completion
                            if event_type in (
                                "job.completed",
                                "job.failed",
                                "job.cancelled",
                                "job.timed_out",
                            ):
                                done_event.set()
                                return

                            # Progress events carry simulation progress
                            if event_type.startswith("progress."):
                                import time as _time

                                # Ripple event_bus wraps SimulationEvent fields in a
                                # "payload" sub-dict: {"type":"progress.wave_start",
                                # "payload":{"wave":3,"total_waves":8,...}}
                                inner = payload.get("payload", payload)

                                p = inner.get("progress")
                                if p is not None:
                                    progress_state["progress"] = float(p)
                                w = inner.get("wave")
                                if w is not None:
                                    progress_state["current_wave"] = int(w)
                                tw = inner.get("total_waves")
                                if tw is not None:
                                    progress_state["total_waves"] = int(tw)
                                progress_state["phase"] = inner.get("phase", "")
                                # R8: Quality fields in SSE events
                                detail = inner.get("detail") or {}
                                quality = detail.get("quality")
                                if isinstance(quality, dict):
                                    progress_state["quality"] = quality
                                cg = detail.get("confidence_gate_result")
                                if isinstance(cg, dict):
                                    progress_state["confidence_gate_result"] = cg
                                progress_state["last_update_at"] = _time.monotonic()

        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout) as exc:
            logger.warning(f"Ripple SSE stream error, falling back: {exc}")
        except Exception as exc:
            logger.warning(f"Ripple SSE stream unexpected error: {exc}")

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
                # Request succeeded — service is reachable
                self._mark_healthy()
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
                # All retries exhausted — service unreachable
                self._mark_unreachable(str(e))
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
        ensemble_runs: int = 3,
        use_fallback: bool = True,
        max_wait: float = 1800.0,
        thread_id: str | None = None,
        environment: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """预测内容传播效果

        Args:
            ensemble_runs: 并行模拟次数（≥3 改善 evidence_balance 和 ensemble_stability）
            use_fallback: 服务不可用时是否使用默认值
            max_wait: 最大等待时间（秒），传递给 submit_and_wait
            thread_id: 关联的工作流线程 ID，用于推送进度事件
            environment: 环境上下文（竞争格局、季节性、平台趋势），提高 input_completeness
        """
        if tags is None:
            tags = []
        config = self._get_config()

        if not config["enabled"] or not self.is_healthy():
            # Probe before falling back — service may have recovered since last check
            if not config["enabled"] or not await self._probe_before_fallback():
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
            if environment:
                event["environment"] = environment
            request_body = {
                "skill": "social-media",
                "platform": "xiaohongshu",
                "event": event,
                "max_waves": max_waves,
                "simulation_horizon": simulation_horizon,
                "ensemble_runs": ensemble_runs,
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
        ensemble_runs: int = 3,
        use_fallback: bool = True,
        max_wait: float = 1800.0,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """验证产品市场契合度

        Args:
            ensemble_runs: 并行模拟次数（≥3 改善 evidence_balance 和 ensemble_stability）
            max_wait: 最大等待时间（秒），传递给 submit_and_wait
            thread_id: 关联的工作流线程 ID，用于推送进度事件
        """
        if differentiators is None:
            differentiators = []
        config = self._get_config()

        if not config["enabled"] or not self.is_healthy():
            # Probe before falling back — service may have recovered since last check
            if not config["enabled"] or not await self._probe_before_fallback():
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
                "ensemble_runs": ensemble_runs,
            }

            result = await self.submit_and_wait(request_body, max_wait=max_wait, thread_id=thread_id)
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
        # Inject llm_config if not already provided by caller
        if "llm_config" not in request_body:
            llm_cfg = self._build_llm_config()
            if llm_cfg:
                request_body["llm_config"] = llm_cfg
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
        poll_interval: float = 3.0,
        max_wait: float = 1800.0,
        thread_id: str | None = None,
    ) -> dict[str, Any]:
        """Wait for simulation completion with SSE-driven progress.

        Uses two channels in parallel:
        - **SSE event stream** (``/v1/simulations/{job_id}/events``) for
          real-time progress updates (progress 0~1, wave, total_waves).
        - **Polling** (``/v1/simulations/{job_id}``) for terminal status
          detection (completed / failed / timed_out).

        If the SSE stream fails or is unavailable, falls back to a
        time-based progress estimate (``elapsed / max_wait``).

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

        # Shared state updated by SSE consumer
        progress_state: dict[str, Any] = {
            "progress": 0.0,
            "current_wave": 0,
            "total_waves": 0,
            "phase": "",
            "last_update_at": None,
        }
        done_event = asyncio.Event()

        # Start SSE consumer (fire-and-forget; errors handled internally)
        if thread_id:
            sse_task = asyncio.create_task(
                self._stream_progress(job_id, thread_id, progress_state, done_event)
            )
        else:
            sse_task = None

        try:
            start_time = _time.monotonic()
            elapsed = 0.0
            while elapsed < max_wait:
                # Check terminal state via polling
                status = await self.get_simulation_status(job_id)
                state = status.get("status", "").lower()

                if state in ("completed", "done", "finished"):
                    logger.info(f"Ripple simulation {job_id} completed after {elapsed:.0f}s")
                    # Emit 100% progress on completion
                    if thread_id:
                        self._emit_progress(
                            job_id,
                            progress=1.0,
                            current_wave=progress_state.get("total_waves", 0),
                            total_waves=progress_state.get("total_waves", 0),
                            elapsed_seconds=elapsed,
                            thread_id=thread_id,
                            status="completed",
                        )
                    return status
                if state in ("failed", "error", "timed_out", "timeout"):
                    error_msg = status.get("error", "Unknown simulation error")
                    raise RuntimeError(f"Ripple simulation {job_id} failed: {error_msg}")

                # Emit progress from SSE data (or time-based fallback)
                if thread_id:
                    sse_updated_at = progress_state.get("last_update_at")
                    sse_progress = progress_state.get("progress", 0.0)
                    use_sse = False
                    if sse_updated_at is not None:
                        sse_age = _time.monotonic() - sse_updated_at
                        # Use SSE data if fresh AND meaningful (progress > 0)
                        if sse_age < SSE_STALE_THRESHOLD and sse_progress > 0:
                            use_sse = True
                    if use_sse:
                        self._emit_progress(
                            job_id,
                            progress=sse_progress,
                            current_wave=progress_state["current_wave"],
                            total_waves=progress_state["total_waves"],
                            elapsed_seconds=elapsed,
                            thread_id=thread_id,
                            status=state,
                            skill=progress_state.get("phase", ""),
                        )
                    else:
                        # Fallback: estimate progress from elapsed time
                        est = min(0.95, elapsed / max_wait)
                        self._emit_progress(
                            job_id,
                            progress=est,
                            current_wave=0,
                            total_waves=0,
                            elapsed_seconds=elapsed,
                            thread_id=thread_id,
                            status=state,
                        )

                if done_event.is_set():
                    # SSE reported completion — do one final poll to get result
                    status = await self.get_simulation_status(job_id)
                    state = status.get("status", "").lower()
                    if state in ("completed", "done", "finished"):
                        if thread_id:
                            self._emit_progress(
                                job_id,
                                progress=1.0,
                                current_wave=progress_state.get("total_waves", 0),
                                total_waves=progress_state.get("total_waves", 0),
                                elapsed_seconds=elapsed,
                                thread_id=thread_id,
                                status="completed",
                            )
                        return status
                    if state in ("failed", "error", "timed_out", "timeout"):
                        error_msg = status.get("error", "Unknown simulation error")
                        raise RuntimeError(f"Ripple simulation {job_id} failed: {error_msg}")

                logger.debug(f"Ripple simulation {job_id} status: {state}, waiting {poll_interval}s...")
                await asyncio.sleep(poll_interval)
                elapsed = _time.monotonic() - start_time

            # ponytail: 超时也必须收尾进度条——否则 _progress_store 残留
            # 0.95/"running" 永久卡死前端（max_wait 跑满但无终态事件 pop）
            if thread_id:
                self._emit_progress(
                    job_id,
                    progress=1.0,
                    current_wave=progress_state.get("total_waves", 0),
                    total_waves=progress_state.get("total_waves", 0),
                    elapsed_seconds=elapsed,
                    thread_id=thread_id,
                    status="timed_out",
                )
            raise RippleTimeoutError(job_id, max_wait)
        finally:
            if sse_task and not sse_task.done():
                sse_task.cancel()
                try:
                    await sse_task
                except asyncio.CancelledError:
                    pass

    async def submit_and_wait(
        self,
        request_body: dict[str, Any],
        poll_interval: float = 3.0,
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

        # Quality subsystem: confidence_gate + quality report
        confidence_gate = output.get("confidence_gate")
        if isinstance(confidence_gate, dict):
            parsed_prediction["confidence_gate"] = confidence_gate
        quality = output.get("quality")
        if isinstance(quality, dict):
            parsed_prediction["quality"] = quality

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

        # Quality subsystem: confidence_gate + quality report
        confidence_gate = output.get("confidence_gate")
        if isinstance(confidence_gate, dict):
            parsed_pmf["confidence_gate"] = confidence_gate
        quality = output.get("quality")
        if isinstance(quality, dict):
            parsed_pmf["quality"] = quality

        return {
            "ripple_job_id": job_id,
            "ripple_pmf": parsed_pmf,
        }
