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

from backend.services.ripple_service import RippleService

logger = logging.getLogger("xhs_growth.tools.ripple")


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
) -> dict[str, Any]:
    """预测内容传播效果 — 供 ContentStrategist 和 Copywriter 调用

    通过 RippleService 提交模拟并等待完成，返回解析后的结果。

    Args:
        max_wait: 最大等待时间（秒），传递给 RippleService.submit_and_wait

    Returns:
        - ripple_job_id: 模拟任务 ID
        - ripple_prediction: 预测数据（estimated_reach, viral_probability 等）
        - ripple_fallback: True if service was unavailable (降级)
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
        )
        return result
    except Exception as e:
        logger.error(f"Ripple spread prediction failed: {e}")
        return {"error": str(e), "ripple_prediction": None}


async def validate_pmf(
    product_name: str,
    category: str,
    description: str,
    differentiators: list[str] | None = None,
    max_wait: float = 1800.0,
) -> dict[str, Any]:
    """验证产品市场契合度 — 供 ContentStrategist 调用

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
        )
        return result
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


def parse_spread_prediction(result: dict[str, Any]) -> dict[str, Any]:
    """解析 Ripple 传播预测结果，映射到 XHS Growth 状态字段

    从 Ripple 输出中提取:
    - 预计互动量级
    - 爆发概率
    - 传播路径特征
    - 关键影响节点
    """
    # 降级或错误直接透传
    if result.get("ripple_fallback"):
        return result
    if "error" in result and "ripple_prediction" not in result:
        return {"ripple_prediction": None, "ripple_error": result["error"]}

    # RippleService 已解析过的结果
    if (
        "ripple_prediction" in result
        and isinstance(result["ripple_prediction"], dict)
        and result["ripple_prediction"].get("viral_probability") is not None
    ):
            return {
                "ripple_job_id": result.get("ripple_job_id", ""),
                "ripple_prediction": result["ripple_prediction"],
            }

    # 原始 API 响应（未解析）
    output = result.get("output", result)
    job_id = result.get("job_id", result.get("id", result.get("ripple_job_id", "")))

    metrics = output.get("metrics", output.get("summary", {}))
    phase_analysis = output.get("phase_analysis", output.get("dynamics", {}))

    if not metrics and not phase_analysis:
        logger.warning(f"Ripple result has no metrics or phase_analysis: {list(result.keys())}")
        return {
            "ripple_job_id": job_id,
            "ripple_prediction": None,
            "ripple_error": "No prediction data in response",
        }

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
            "phase": phase_analysis.get("phase", phase_analysis.get("dominant_phase", "unknown")),
            "confidence": metrics.get("confidence", 0.0),
            "key_influencers": metrics.get("key_influencers", []),
            "spread_path": phase_analysis.get("spread_path", []),
        },
    }


def parse_pmf_result(result: dict[str, Any]) -> dict[str, Any]:
    """解析 Ripple PMF 验证结果"""
    # 降级或错误直接透传
    if result.get("ripple_fallback"):
        return result
    if "error" in result and "ripple_pmf" not in result:
        return {"ripple_pmf": None, "ripple_error": result["error"]}

    # RippleService 已解析过的结果
    if (
        "ripple_pmf" in result
        and isinstance(result["ripple_pmf"], dict)
        and result["ripple_pmf"].get("pmf_score") is not None
    ):
            return {
                "ripple_job_id": result.get("ripple_job_id", ""),
                "ripple_pmf": result["ripple_pmf"],
            }

    # 原始 API 响应（未解析）
    output = result.get("output", result)
    job_id = result.get("job_id", result.get("id", result.get("ripple_job_id", "")))

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
