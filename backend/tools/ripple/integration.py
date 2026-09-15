"""Ripple integration layer — connects Ripple CAS engine to XHS Growth Agent workflow.

Ripple provides:
- Content spread prediction (social-media skill)
- PMF validation (pmf-validation skill)
- Simulation reports with phase analysis

This module provides:
1. High-level async functions for agents to call
2. Result parsing and state mapping
3. Integration with the XHS Growth state schema

All calls go through RippleService for connection pooling, retry, and fallback.

Ripple answers in a vocabulary of its own, and that answer is *data* rather
than an exception: "the simulation has not finished, here is the job id to
cancel or resume" is not a failure of the call. Those answers are raised as
``DomainOutcome`` — the runtime's channel for them — so they reach the caller
intact. Raising them rather than returning them is what stops the Gateway from
filing the call as a success: a returned ``{"error": ...}`` dict used to be
recorded as ``ok=True``, and a ``RippleTimeoutError`` (a ``TimeoutError``
subclass) used to arrive as a plain gateway timeout with the ``job_id`` — the
only field that makes recovery possible — stripped off.

Ordinary exceptions are *not* caught here. Normalising failures is the
Gateway's job and it has exactly one home (``backend/tools/runtime/gateway.py``);
a second, quieter normaliser in this file is how the two came to disagree.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.services.ripple_service import RippleService, RippleTimeoutError
from backend.tools.runtime.models import DomainOutcome

logger = logging.getLogger("xhs_growth.tools.ripple")


async def _get_service() -> RippleService:
    """获取 RippleService 实例并确保健康检查已执行"""
    service = RippleService.get_instance()
    if not service.is_healthy():
        await service.health_check()
    return service


def _reject_degraded(result: dict[str, Any], *, body_key: str) -> dict[str, Any]:
    """Turn the service's designed degraded answer into a domain outcome.

    ``RippleService`` reports "service unavailable" by *succeeding*: it returns
    a fallback body full of zeros next to ``ripple_fallback: True``. Passed
    through as a value, that is indistinguishable from a real prediction —
    ``predict_spread`` handed the caller a zeroed ``ripple_prediction`` and the
    agent read those zeros as a genuine forecast. Saying so as a domain outcome
    makes the degradation a fact the caller branches on, and gives the trace an
    honest ``error_kind`` instead of ``ok=True``.

    The zeroed body is deliberately *not* carried in the payload: callers build
    their own fallback, and copying the same zeros into every payload would be
    noise. The reason and the message — which explain *why* — are.
    """
    if not result.get("ripple_fallback"):
        return result
    logger.warning("Ripple degraded answer (%s): %s", body_key, result.get("ripple_reason", ""))
    raise DomainOutcome(
        "unavailable",
        ripple_reason=str(result.get("ripple_reason", "")),
        ripple_message=str(result.get("ripple_message", "")),
    )


async def predict_spread(
    topic: str,
    content_type: str = "图文笔记",
    tags: list[str] | None = None,
    tone: str = "真诚种草",
    description: str = "",
    max_waves: int = 3,
    simulation_horizon: str = "12h",
    ensemble_runs: int = 1,
    max_wait: float = 1800.0,
    thread_id: str | None = None,
    environment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """预测内容传播效果 — 供 ContentStrategist 和 Copywriter 调用

    Args:
        ensemble_runs: 并行模拟次数（≥3 改善 evidence_balance 和 ensemble_stability）
        max_wait: 最大等待时间（秒），传递给 RippleService.submit_and_wait
        thread_id: 关联的工作流线程 ID，用于推送进度事件
        environment: 环境上下文（竞争格局、季节性、平台趋势），提高 input_completeness

    Returns:
        - ripple_job_id: 模拟任务 ID
        - ripple_prediction: 预测数据

    Raises:
        DomainOutcome: ``timeout``（携带 ripple_job_id / max_wait）或
            ``unavailable``（服务降级）
    """
    if tags is None:
        tags = []
    service = await _get_service()
    try:
        result = await service.predict_spread(
            topic=topic,
            content_type=content_type,
            tags=tags,
            tone=tone,
            description=description,
            max_waves=max_waves,
            simulation_horizon=simulation_horizon,
            ensemble_runs=ensemble_runs,
            max_wait=max_wait,
            thread_id=thread_id,
            environment=environment,
        )
    except RippleTimeoutError as exc:
        # The simulation is still running server-side. Carry its id: cancel and
        # resume both start from it, and it is the reason this is a domain
        # outcome rather than a plain timeout.
        raise DomainOutcome("timeout", ripple_job_id=exc.job_id, max_wait=exc.max_wait) from exc
    return _reject_degraded(result, body_key="ripple_prediction")


async def validate_pmf(
    product_name: str,
    category: str,
    description: str,
    differentiators: list[str] | None = None,
    max_waves: int = 3,
    simulation_horizon: str = "12h",
    ensemble_runs: int = 1,
    max_wait: float = 1800.0,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """验证产品市场契合度 — 供 ContentStrategist 调用

    Args:
        max_wait: 最大等待时间（秒），传递给 RippleService.submit_and_wait
        thread_id: 关联的工作流线程 ID，用于推送进度事件

    Returns:
        - ripple_job_id: 模拟任务 ID
        - ripple_pmf: PMF 验证结果（pmf_score, risk_factors 等）

    Raises:
        DomainOutcome: ``timeout``（携带 ripple_job_id / max_wait）或
            ``unavailable``（服务降级）
    """
    if differentiators is None:
        differentiators = []
    service = await _get_service()
    try:
        result = await service.validate_pmf(
            product_name=product_name,
            category=category,
            description=description,
            differentiators=differentiators,
            max_waves=max_waves,
            simulation_horizon=simulation_horizon,
            ensemble_runs=ensemble_runs,
            max_wait=max_wait,
            thread_id=thread_id,
        )
    except RippleTimeoutError as exc:
        raise DomainOutcome("timeout", ripple_job_id=exc.job_id, max_wait=exc.max_wait) from exc
    return _reject_degraded(result, body_key="ripple_pmf")


async def get_report(job_id: str) -> dict[str, Any]:
    """生成模拟报告"""
    try:
        service = await _get_service()
        return await service.get_report(job_id)
    except Exception as e:
        logger.error(f"Ripple report generation failed for {job_id}: {e}")
        return {"error": str(e)}
