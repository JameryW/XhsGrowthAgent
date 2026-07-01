"""Analyst agent — reads engagement data, generates insights, with Ripple report integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.services.ripple_service import RippleTimeoutError
from backend.state.schema import WorkflowPhase, XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.analyst")

# Ripple 报告获取超时（秒）— 报告生成是增值操作，不阻塞主流程
_RIPPLE_REPORT_TIMEOUT = 120


async def _safe_evolve(account_id: object) -> None:
    """Fire-and-forget wrapper: run maybe_evolve, swallow all errors.

    Scheduled via asyncio.create_task after backfill_engagement, so its
    exceptions would otherwise escape to the event loop. maybe_evolve is
    already non-blocking internally; this just guarantees no stray traceback.
    """
    try:
        from backend.db.evaluator_config import maybe_evolve

        await maybe_evolve(account_id if isinstance(account_id, str) else None)
    except Exception as e:
        logger.debug("evaluator auto-evolve failed (non-blocking): %s", e)


class AnalystAgent(BaseAgent):
    task_type = TaskType.ANALYSIS
    agent_name = "analyst"
    prompt_file = "analyst.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        account_id = state.get("account_id", "default")
        publish_result = state.get("publish_result", {})

        # 召回历史数据
        history = await self._recall_memory(
            store, account_id, query="content performance", namespace="content_history", limit=10
        )

        # 尝试获取 Ripple 预测报告（如果之前有模拟）
        ripple_report = await self._ripple_report(state)

        system_prompt = self._build_system_prompt(state)

        ripple_context = ""
        if ripple_report:
            ripple_context = f"\nRipple 传播预测报告：\n{ripple_report}\n"

        niche = state.get("niche", "母婴")
        user_msg = f"""帖子数据：{publish_result}
历史数据：{history}
账号定位：{account_id}
垂类赛道：{niche}{ripple_context}"""

        response = await self.model.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_msg),
            ]
        )

        analytics = self._parse_json_response(cast(str, response.content))

        # 将 Ripple 预测与实际数据对比，写入 state
        result_updates: dict[str, Any] = {
            "analytics": analytics,
            "phase": WorkflowPhase.ANALYZING,
        }

        ripple_prediction = state.get("content_plan", {}).get("ripple_prediction")
        ripple_comparison: dict[str, Any] | None = None
        if ripple_prediction:
            ripple_comparison = self._compare_prediction_vs_actual(
                cast(dict[str, Any] | None, ripple_prediction),
                cast(dict[str, Any], publish_result),
            )
            if ripple_comparison:
                analytics["ripple_comparison"] = ripple_comparison
                result_updates["ripple_comparison"] = ripple_comparison

                # 将校准洞察存入原有记忆（保持兼容）
                calibration = ripple_comparison.get("calibration_insight", "")
                if calibration:
                    from backend.memory.store import MemoryManager

                    mm = MemoryManager(account_id)
                    await mm.store_insight(
                        store,
                        f"Ripple 校准: {calibration}",
                        {"source": "analyst", "type": "ripple_calibration"},
                    )

        # 将洞察存入原有记忆（保持兼容）
        from backend.memory.store import MemoryManager

        mm = MemoryManager(account_id)
        for insight in analytics.get("insights", []):
            post_id = publish_result.get("post_id", "")
            await mm.store_insight(store, insight, {"source": "analyst", "post_id": post_id})

        for rec in analytics.get("recommendations", []):
            await mm.store_strategy_note(store, rec, {"source": "analyst"})

        # ── Update content history with actual engagement metrics ──
        post_id = publish_result.get("post_id", "")
        if post_id:
            try:
                existing = await store.aget(mm.content_history_ns, key=post_id)
                if existing:
                    record = existing.value
                    record["views"] = publish_result.get(
                        "views", publish_result.get("impressions", 0)
                    )
                    record["likes"] = publish_result.get("likes", 0)
                    record["collects"] = publish_result.get(
                        "collects", publish_result.get("bookmarks", 0)
                    )
                    record["comments"] = publish_result.get("comments", 0)
                    record["shares"] = publish_result.get("shares", 0)
                    record_views = record["views"] or 0
                    if record_views > 0:
                        total_engagement = (
                            (record.get("likes", 0) or 0)
                            + (record.get("collects", 0) or 0)
                            + (record.get("comments", 0) or 0)
                            + (record.get("shares", 0) or 0)
                        )
                        record["engagement_rate"] = round(total_engagement / record_views, 4)
                    await store.aput(mm.content_history_ns, key=post_id, value=record)
            except Exception as e:
                logger.warning(f"更新内容历史互动数据失败: {e}")

        # ── Back-fill real engagement onto the evaluator's training sample ──
        # ponytail: weak label for grader finetuning — attaches publish_result
        # engagement to the evaluator judgment sample. Non-blocking.
        thread_id = state.get("session_id")
        if thread_id:
            try:
                from backend.db.evaluator_config import backfill_engagement
                from backend.db.pool import is_pool_ready

                if is_pool_ready():
                    engagement = {
                        k: publish_result.get(k, 0)
                        for k in ("views", "likes", "collects", "comments", "shares")
                        if k in publish_result
                    }
                    if engagement:
                        await backfill_engagement(thread_id, engagement)
                        # ── Online co-evolution (RQGM epoch boundary) ──
                        # New feedback arrived → fire-and-forget a check whether
                        # enough samples accrued to refit weights / advance the
                        # prompt epoch. Never blocks the publish path.
                        # ponytail: create_task; _safe_evolve swallows all errors
                        # and maybe_evolve is re-entry-guarded per account.
                        import asyncio

                        asyncio.create_task(_safe_evolve(state.get("account_id")))  # noqa: RUF006
            except Exception as e:
                logger.debug(f"样本 engagement 回灌失败 (non-blocking): {e}")

        # ── Creative Memory: 输出 calibration_payload（异步回写）──
        from backend.memory.calibrator import build_calibration_payload, schedule_calibration

        actual_engagement_rate = 0.0
        actual_save_rate = 0.0
        if ripple_comparison:
            actual_engagement_rate = ripple_comparison.get("actual_engagement_rate", 0.0)
        actual_collects: int = publish_result.get("collects", publish_result.get("bookmarks", 0))  # type: ignore[assignment]
        actual_views: int = publish_result.get("views", publish_result.get("impressions", 0))  # type: ignore[assignment]
        if actual_views > 0:
            actual_save_rate = actual_collects / actual_views

        calibration_payload = build_calibration_payload(
            state,  # type: ignore[arg-type]
            actual_engagement_rate,
            actual_save_rate,
        )
        result_updates["calibration_payload"] = calibration_payload

        # 异步回写（不阻塞主流程）
        if store is not None:
            await schedule_calibration(store, calibration_payload)

        return result_updates

    async def _ripple_report(self, state: XHSGrowthState) -> str | None:
        """尝试获取 Ripple 模拟报告（带超时保护）"""
        ripple_prediction = state.get("content_plan", {}).get("ripple_prediction", {})
        job_id = (
            ripple_prediction.get("ripple_job_id") if isinstance(ripple_prediction, dict) else None
        )

        if not job_id:
            return None

        try:
            from backend.tools.ripple.integration import get_report

            report = await asyncio.wait_for(
                get_report(job_id),
                timeout=_RIPPLE_REPORT_TIMEOUT,
            )
            if "error" not in report:
                # 提取报告文本
                rounds = report.get("rounds", [])
                texts = []
                for r in rounds:
                    texts.append(r.get("content", r.get("text", str(r))))
                return "\n".join(texts)

        except RippleTimeoutError as e:
            logger.warning(f"Ripple report timed out: job_id={e.job_id}")
            await self._ripple_cancel(e.job_id)

        except TimeoutError:
            logger.warning(
                f"Ripple report retrieval timed out after {_RIPPLE_REPORT_TIMEOUT}s for {job_id}"
            )
            # 尝试取消报告生成任务
            await self._ripple_cancel(job_id)

        except Exception as e:
            logger.warning(f"Ripple report retrieval skipped: {e}")

        return None

    async def _ripple_cancel(self, job_id: str) -> None:
        """尝试取消 Ripple 模拟任务（报告超时时调用）"""
        if not job_id:
            return

        try:
            from backend.services.ripple_service import RippleService

            service = RippleService.get_instance()
            result = await service.cancel_simulation(job_id)
            logger.info(f"Ripple cancel result for {job_id}: {result}")

        except Exception as e:
            logger.warning(f"Ripple cancel failed for {job_id}: {e}")

    def _compare_prediction_vs_actual(
        self, prediction: dict[str, Any] | None, actual: dict[str, Any]
    ) -> dict[str, Any]:
        """对比 Ripple 预测与实际表现，生成可行动的校准洞察"""
        if not prediction:
            return {}

        predicted_reach = prediction.get("estimated_reach", 0)
        predicted_engagement = prediction.get("estimated_engagement", 0)
        predicted_viral_prob = prediction.get("viral_probability", 0.0)

        # 从 publish_result 提取实际数据
        actual_views = actual.get("views", actual.get("impressions", 0))
        actual_likes = actual.get("likes", 0)
        actual_collects = actual.get("collects", actual.get("bookmarks", 0))
        actual_comments = actual.get("comments", 0)
        actual_shares = actual.get("shares", 0)
        actual_engagement_total = actual_likes + actual_collects + actual_comments + actual_shares
        actual_engagement_rate = actual.get(
            "engagement_rate",
            (actual_engagement_total / actual_views) if actual_views > 0 else 0.0,
        )

        # 计算偏差率
        reach_deviation = 0.0
        if predicted_reach > 0:
            reach_deviation = (actual_views - predicted_reach) / predicted_reach

        engagement_deviation = 0.0
        if predicted_engagement > 0:
            engagement_deviation = (
                actual_engagement_total - predicted_engagement
            ) / predicted_engagement

        # 评级
        if abs(reach_deviation) <= 0.3:
            accuracy_rating = "准确"
        elif reach_deviation > 0.3:
            accuracy_rating = "低估"
        else:
            accuracy_rating = "高估"

        # 生成校准洞察
        calibration_parts = []
        if accuracy_rating == "低估":
            calibration_parts.append(
                f"Ripple 低估了实际触达 {abs(reach_deviation):.0%}，"
                f"说明该内容类型/话题的传播力超出模型预期"
            )
        elif accuracy_rating == "高估":
            calibration_parts.append(
                f"Ripple 高估了实际触达 {abs(reach_deviation):.0%}，说明内容在分发/互动环节存在瓶颈"
            )
        else:
            calibration_parts.append("Ripple 预测与实际表现基本吻合")

        if predicted_viral_prob > 0.5 and actual_engagement_rate < 0.02:
            calibration_parts.append("高爆发概率但实际互动率偏低，可能标题党效应或受众不匹配")
        elif predicted_viral_prob < 0.3 and actual_engagement_rate > 0.05:
            calibration_parts.append("低爆发概率但实际互动率出色，该内容模式值得复用")

        return {
            "predicted_reach": predicted_reach,
            "predicted_engagement": predicted_engagement,
            "predicted_viral_prob": predicted_viral_prob,
            "actual_views": actual_views,
            "actual_engagement_total": actual_engagement_total,
            "actual_engagement_rate": actual_engagement_rate,
            "reach_deviation": round(reach_deviation, 3),
            "engagement_deviation": round(engagement_deviation, 3),
            "accuracy_rating": accuracy_rating,
            "calibration_insight": "；".join(calibration_parts),
        }
