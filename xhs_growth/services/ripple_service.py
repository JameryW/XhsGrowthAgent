"""Ripple CAS service with connection pooling, retry, health check, and fallback."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel

from xhs_growth.config.settings import Settings

logger = logging.getLogger("xhs_growth.services.ripple")


class RippleHealthStatus(BaseModel):
    """Ripple 服务健康状态"""
    is_healthy: bool = False
    last_check: str = ""
    latency_ms: float = 0.0
    error: str = ""


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
                error="Ripple is disabled in settings"
            )
            return self._health_status

        try:
            client = await self._get_client()
            import time
            start = time.time()

            # 尝试访问健康端点或根路径
            resp = await client.get(f"{config['base_url']}/health", timeout=5.0)

            latency = (time.time() - start) * 1000

            if resp.status_code in (200, 404):  # 404 表示服务运行但没有 /health
                self._health_status = RippleHealthStatus(
                    is_healthy=True,
                    last_check="ok",
                    latency_ms=latency,
                )
                logger.info(f"Ripple health check passed: {latency:.0f}ms")
            else:
                self._health_status = RippleHealthStatus(
                    is_healthy=False,
                    last_check="error",
                    error=f"HTTP {resp.status_code}"
                )
                logger.warning(f"Ripple health check failed: HTTP {resp.status_code}")

        except httpx.ConnectError as e:
            self._health_status = RippleHealthStatus(
                is_healthy=False,
                last_check="connect_error",
                error=str(e)
            )
            logger.warning(f"Ripple service not reachable: {e}")

        except Exception as e:
            self._health_status = RippleHealthStatus(
                is_healthy=False,
                last_check="error",
                error=str(e)
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

                if resp.status_code >= 500:
                    # 服务器错误，重试
                    if attempt < max_retries - 1:
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
            "ripple_message": "Service unavailable, using default prediction"
        }

    def _default_pmf_result(self) -> dict[str, Any]:
        """默认 PMF 结果（降级时使用）"""
        return {
            "ripple_pmf": {
                "pmf_score": 0.0,
                "risk_factors": ["Ripple service unavailable"],
                "improvement_strategies": [],
                "market_segment": {},
                "confidence": 0.0,
            },
            "ripple_fallback": True,
            "ripple_message": "Service unavailable, using default PMF"
        }

    # ── 高级 API ──

    async def predict_spread(
        self,
        topic: str,
        content_type: str = "图文笔记",
        tags: list[str] = [],
        tone: str = "真诚种草",
        description: str = "",
        max_waves: int = 8,
        simulation_horizon: str = "48h",
        use_fallback: bool = True,
    ) -> dict[str, Any]:
        """预测内容传播效果

        Args:
            use_fallback: 服务不可用时是否使用默认值
        """
        config = self._get_config()

        if not config["enabled"] or not self.is_healthy():
            if use_fallback:
                logger.info("Ripple unavailable, using fallback prediction")
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

            result = await self._request_with_retry(
                "POST",
                f"{config['base_url']}/v1/simulations",
                json_data=request_body,
            )

            return self._parse_spread_result(result)

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
        differentiators: list[str] = [],
        use_fallback: bool = True,
    ) -> dict[str, Any]:
        """验证产品市场契合度"""
        config = self._get_config()

        if not config["enabled"] or not self.is_healthy():
            if use_fallback:
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

            result = await self._request_with_retry(
                "POST",
                f"{config['base_url']}/v1/simulations",
                json_data=request_body,
            )

            return self._parse_pmf_result(result)

        except Exception as e:
            logger.error(f"Ripple PMF validation failed: {e}")
            if use_fallback:
                return self._default_pmf_result()
            return {"error": str(e)}

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
                "estimated_engagement": metrics.get("estimated_engagement", metrics.get("total_engagement", 0)),
                "viral_probability": metrics.get("viral_probability", metrics.get("outbreak_probability", 0.0)),
                "phase": phase_analysis.get("phase", phase_analysis.get("dominant_phase", "unknown")),
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