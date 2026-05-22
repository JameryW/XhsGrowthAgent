"""Ripple integration layer — connects Ripple CAS engine to XHS Growth Agent workflow.

Ripple provides:
- Content spread prediction (social-media skill)
- PMF validation (pmf-validation skill)
- Simulation reports with phase analysis

This module provides:
1. High-level async functions for agents to call
2. Result parsing and state mapping
3. Integration with the XHS Growth state schema
"""

from __future__ import annotations

import logging
from typing import Any

from xhs_growth.tools.ripple.client import (
    ripple_predict_content_spread,
    ripple_validate_pmf,
    ripple_get_simulation_status,
    ripple_get_simulation_result,
    ripple_get_simulation_log,
    ripple_generate_report,
)

logger = logging.getLogger("xhs_growth.tools.ripple")


async def predict_spread(
    topic: str,
    content_type: str = "图文笔记",
    tags: list[str] = [],
    tone: str = "真诚种草",
    description: str = "",
    max_waves: int = 8,
    simulation_horizon: str = "48h",
) -> dict[str, Any]:
    """预测内容传播效果 — 供 ContentStrategist 和 Copywriter 调用

    返回:
        - job_id: 模拟任务 ID
        - status: 任务状态
        - 预测数据（如果同步完成）
    """
    try:
        result = await ripple_predict_content_spread.ainvoke({
            "topic": topic,
            "content_type": content_type,
            "tags": tags,
            "tone": tone,
            "description": description,
            "max_waves": max_waves,
            "simulation_horizon": simulation_horizon,
        })
        return result
    except Exception as e:
        logger.error(f"Ripple spread prediction failed: {e}")
        return {"error": str(e), "job_id": None}


async def validate_pmf(
    product_name: str,
    category: str,
    description: str,
    differentiators: list[str] = [],
) -> dict[str, Any]:
    """验证产品市场契合度 — 供 ContentStrategist 调用

    返回:
        - job_id: 模拟任务 ID
        - pmf_score: PMF 评分
        - risk_factors: 风险因素
        - improvement_strategies: 改进策略
    """
    try:
        result = await ripple_validate_pmf.ainvoke({
            "product_name": product_name,
            "category": category,
            "description": description,
            "differentiators": differentiators,
        })
        return result
    except Exception as e:
        logger.error(f"Ripple PMF validation failed: {e}")
        return {"error": str(e), "job_id": None}


async def get_result(job_id: str) -> dict[str, Any]:
    """获取模拟结果"""
    try:
        return await ripple_get_simulation_result.ainvoke({"job_id": job_id})
    except Exception as e:
        logger.error(f"Ripple get result failed for {job_id}: {e}")
        return {"error": str(e)}


async def get_report(job_id: str) -> dict[str, Any]:
    """生成模拟报告"""
    try:
        return await ripple_generate_report.ainvoke({"job_id": job_id})
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
    if "error" in result:
        return {"ripple_prediction": None, "ripple_error": result["error"]}

    # Ripple 返回的 simulation 结果结构
    output = result.get("output", result)
    job_id = result.get("job_id", result.get("id", ""))

    # 尝试从 output-json 提取关键指标
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


def parse_pmf_result(result: dict[str, Any]) -> dict[str, Any]:
    """解析 Ripple PMF 验证结果"""
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
