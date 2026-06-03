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
"""

from __future__ import annotations

import logging
from typing import Any

from backend.services.ripple_service import RippleService, RippleTimeoutError

logger = logging.getLogger("xhs_growth.tools.ripple")


def _parser_service() -> RippleService:
    """Create a stateless parser instance without touching RippleService's singleton."""
    return object.__new__(RippleService)


async def _get_service() -> RippleService:
    """获取 RippleService 实例并确保健康检查已执行"""
    service = RippleService.get_instance()
    if not service.is_healthy():
        await service.health_check()
    return service


async def predict_spread(
    topic: str,
    content_type: str = "图文笔记",
    tags: list[str] | None = None,
    tone: str = "真诚种草",
    description: str = "",
    max_waves: int = 8,
    simulation_horizon: str = "48h",
    max_wait: float = 1800.0,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """预测内容传播效果 — 供 ContentStrategist 和 Copywriter 调用

    Args:
        max_wait: 最大等待时间（秒），传递给 RippleService.submit_and_wait
        thread_id: 关联的工作流线程 ID，用于推送进度事件

    Returns:
        - ripple_job_id: 模拟任务 ID
        - ripple_prediction: 预测数据
        - ripple_fallback: True if service was unavailable
    """
    if tags is None:
        tags = []
    try:
        service = await _get_service()
        result = await service.predict_spread(
            topic=topic,
            content_type=content_type,
            tags=tags,
            tone=tone,
            description=description,
            max_waves=max_waves,
            simulation_horizon=simulation_horizon,
            max_wait=max_wait,
            thread_id=thread_id,
        )
        return result
    except RippleTimeoutError:
        # 让 RippleTimeoutError 传播到调用方，以便保存 job_id 并尝试取消
        raise
    except Exception as e:
        logger.error(f"Ripple spread prediction failed: {e}")
        return {"error": str(e), "ripple_prediction": None}


async def validate_pmf(
    product_name: str,
    category: str,
    description: str,
    differentiators: list[str] | None = None,
    max_wait: float = 1800.0,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """验证产品市场契合度 — 供 ContentStrategist 调用

    Args:
        max_wait: 最大等待时间（秒），传递给 RippleService.submit_and_wait
        thread_id: 关联的工作流线程 ID，用于推送进度事件

    通过 RippleService 提交模拟并等待完成，返回解析后的结果。

    Args:
        max_wait: 最大等待时间（秒），传递给 RippleService.submit_and_wait

    Returns:
        - ripple_job_id: 模拟任务 ID
        - ripple_pmf: PMF 验证结果（pmf_score, risk_factors 等）
        - ripple_fallback: True if service was unavailable (降级)
    """
    if differentiators is None:
        differentiators = []
    try:
        service = await _get_service()
        result = await service.validate_pmf(
            product_name=product_name,
            category=category,
            description=description,
            differentiators=differentiators,
            max_wait=max_wait,
            thread_id=thread_id,
        )
        return result
    except RippleTimeoutError:
        # 让 RippleTimeoutError 传播到调用方，以便保存 job_id 并尝试取消
        raise
    except Exception as e:
        logger.error(f"Ripple PMF validation failed: {e}")
        return {"error": str(e), "ripple_pmf": None}


async def get_result(job_id: str) -> dict[str, Any]:
    """获取模拟结果"""
    try:
        service = await _get_service()
        return await service.get_result(job_id)
    except Exception as e:
        logger.error(f"Ripple get result failed for {job_id}: {e}")
        return {"error": str(e)}


async def get_report(job_id: str) -> dict[str, Any]:
    """生成模拟报告"""
    try:
        service = await _get_service()
        return await service.get_report(job_id)
    except Exception as e:
        logger.error(f"Ripple report generation failed for {job_id}: {e}")
        return {"error": str(e)}


async def cancel_simulation(job_id: str) -> dict[str, Any]:
    """尝试取消 Ripple 模拟任务

    使用 Ripple 两步取消协议，对旧服务回退 DELETE，并对 404/405/网络错误做优雅降级。

    Args:
        job_id: 模拟任务 ID

    Returns:
        {"cancelled": bool, "job_id": str, "status": str, "error"?: str}
    """
    try:
        service = await _get_service()
        return await service.cancel_simulation(job_id)
    except Exception as e:
        logger.error(f"Ripple cancel failed for {job_id}: {e}")
        return {"cancelled": False, "job_id": job_id, "status": "error", "error": str(e)}


async def recover_result(job_id: str) -> dict[str, Any]:
    """恢复超时模拟的结果 — 检查任务状态，若已完成则获取结果

    返回结构化状态，支持未来后台轮询扩展。

    Args:
        job_id: 模拟任务 ID

    Returns:
        RecoveryStatus 的 dict 形式: {"job_id", "status", "result"?, "error"?}
    """
    try:
        service = await _get_service()
        recovery = await service.recover_result(job_id)
        return recovery.model_dump()
    except Exception as e:
        logger.error(f"Ripple recover failed for {job_id}: {e}")
        return {"job_id": job_id, "status": "failed", "error": str(e)}


def parse_spread_prediction(result: dict[str, Any]) -> dict[str, Any]:
    """解析 Ripple 传播预测结果，映射到 XHS Growth 状态字段

    从 Ripple 输出中提取:
    - 预计互动量级
    - 爆发概率
    - 传播路径特征
    - 关键影响节点
    """
    return _parser_service()._parse_spread_result(result)


def parse_pmf_result(result: dict[str, Any]) -> dict[str, Any]:
    """解析 Ripple PMF 验证结果"""
    return _parser_service()._parse_pmf_result(result)
