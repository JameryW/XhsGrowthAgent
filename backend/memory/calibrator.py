"""Async creative memory calibration — writes back analyst results after workflow completes.

The analyst outputs a CalibrationPayload into state. This module provides
an async task that reads the payload and writes back to Style DNA,
Conversion Playbook, and Material Vault via CreativeMemory.calibrate().
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.store.base import BaseStore

from backend.memory.creative import CreativeMemory
from backend.memory.types import CalibrationPayload

logger = logging.getLogger("xhs_growth.memory.calibrator")

MAX_RETRIES = 3
RETRY_DELAY = 1.0  # seconds


async def calibrate_creative_memory(
    store: BaseStore,
    payload: CalibrationPayload,
    max_retries: int = MAX_RETRIES,
) -> bool:
    """异步校准创作记忆 — 带重试.

    Args:
        store: LangGraph BaseStore
        payload: analyst 输出的校准数据
        max_retries: 最大重试次数

    Returns:
        True if calibration succeeded, False otherwise
    """
    account_id = payload.get("account_id", "default")
    cm = CreativeMemory(account_id, store=store)

    for attempt in range(1, max_retries + 1):
        try:
            await cm.calibrate(payload)
            logger.info(
                f"Creative memory calibrated for account={account_id}, "
                f"post={payload.get('post_id', '')} (attempt {attempt})"
            )
            return True
        except Exception as e:
            logger.warning(f"Calibration attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                await asyncio.sleep(RETRY_DELAY * attempt)

    logger.error(f"Calibration failed after {max_retries} retries for account={account_id}")
    return False


async def schedule_calibration(
    store: BaseStore,
    payload: CalibrationPayload,
) -> asyncio.Task[bool]:
    """将校准任务提交为后台 asyncio.Task（不阻塞主流程）.

    Usage:
        task = await schedule_calibration(store, payload)
        # task runs in background; main flow continues
    """
    return asyncio.create_task(
        calibrate_creative_memory(store, payload),
        name=f"calibrate_{payload.get('account_id', 'default')}_{payload.get('post_id', '')}",
    )


def build_calibration_payload(
    state: dict[str, Any],
    actual_engagement_rate: float,
    actual_save_rate: float,
) -> CalibrationPayload:
    """从 workflow state 构建校准 payload.

    Called by analyst after computing actual metrics.
    """
    account_id = state.get("account_id", "default")
    niche = state.get("niche", "")

    # 从 content_plan 提取 style_id（如果有）
    content_plan = state.get("content_plan", {})
    style_id = content_plan.get("style_id", "")

    # 从 copy_content 提取 play_id（如果有）
    copy_content = state.get("copy_content", {})
    play_id = copy_content.get("play_id", "")

    # 从 publish_result 提取 post_id
    publish_result = state.get("publish_result", {})
    post_id = publish_result.get("post_id", "")

    # 判断 play 是否成功（互动率高于 0.03 视为成功）
    play_success = actual_engagement_rate >= 0.03

    # 素材 ID 和效果（从 copy_content 提取）
    material_ids = copy_content.get("used_material_ids", [])
    material_effectiveness = copy_content.get("material_effectiveness", {})

    return CalibrationPayload(
        account_id=account_id,
        niche=niche,
        style_id=style_id,
        actual_engagement_rate=actual_engagement_rate,
        actual_save_rate=actual_save_rate,
        play_id=play_id,
        play_success=play_success,
        material_ids=material_ids,
        material_effectiveness=material_effectiveness,
        post_id=post_id,
    )


__all__ = [
    "calibrate_creative_memory",
    "schedule_calibration",
    "build_calibration_payload",
]
