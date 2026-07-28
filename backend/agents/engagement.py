"""Engagement agent — manages comments, DMs, and fan interactions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast

from langchain_core.messages import HumanMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.config.settings import Settings
from backend.state.enums import WorkflowPhase
from backend.state.schema import XHSGrowthState
from backend.state.substates import EngagementAction

logger = logging.getLogger("xhs_growth.agents.engagement")


class EngagementAgent(BaseAgent):
    task_type = TaskType.ENGAGEMENT
    agent_name = "engagement"
    prompt_file = "engagement.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        publish_result = state.get("publish_result", {})

        # 获取配置
        settings = Settings()
        use_browser = settings.platform.use_browser

        engagement_actions: list[EngagementAction] = []
        engagement_error: str | None = None

        # dry_run guard — publisher returned a mock post_id ("mock_<session>").
        # Skip real XHS API calls so a manually-triggered engagement on a
        # dry_run thread doesn't leak real API calls against a fake post_id.
        # Normal flow never reaches here (dry_run publisher → END), but a
        # resume with phase=ANALYZING could route analyst → engagement.
        is_dry_run = bool(state.get("dry_run")) or (
            str(publish_result.get("post_id", "")).startswith("mock_")
        )
        if is_dry_run:
            logger.info("dry_run 或 mock post，跳过真实互动")
            mode = state.get("execution_mode", "single")
            return {
                "engagement_actions": engagement_actions,
                "phase": WorkflowPhase.COMPLETED if mode == "single" else WorkflowPhase.ENGAGING,
                "engagement_error": engagement_error,
            }

        if not publish_result.get("post_id"):
            logger.info("无已发布帖子，跳过互动处理")
            mode = state.get("execution_mode", "single")
            return {
                "engagement_actions": engagement_actions,
                "phase": WorkflowPhase.COMPLETED if mode == "single" else WorkflowPhase.ENGAGING,
                "engagement_error": engagement_error,
            }

        if not use_browser:
            logger.warning("use_browser=False，跳过真实互动")
            mode = state.get("execution_mode", "single")
            return {
                "engagement_actions": engagement_actions,
                "phase": WorkflowPhase.COMPLETED if mode == "single" else WorkflowPhase.ENGAGING,
                "engagement_error": engagement_error,
            }

        # 调用真实互动服务
        from backend.services.xhs_client import XHSClient

        account_id = str(state.get("account_id", "")).strip()
        cdp_endpoint = settings.platform.cdp_endpoint.strip()
        if account_id:
            try:
                from backend.db.accounts import get_account_cdp_endpoint

                account_cdp = (await get_account_cdp_endpoint(account_id)).strip()
                if account_cdp:
                    cdp_endpoint = account_cdp
            except Exception as exc:
                logger.warning("无法解析账号 %s 的互动 CDP endpoint: %s", account_id, exc)

        client = XHSClient(
            use_browser=True,
            headless=False,
            cdp_endpoint=cdp_endpoint,
            account_id=account_id,
        )

        try:
            post_id = publish_result.get("post_id")
            assert post_id is not None  # guarded by the early-return above

            # 1. 获取评论
            comments = await client.get_comments(post_id=post_id, limit=20)
            logger.info(f"获取 {len(comments)} 条评论")

            # 2. 获取私信
            dms = await client.get_direct_messages(limit=10)
            logger.info(f"获取 {len(dms)} 条私信")

            # 3. 自动回复评论 (使用 LLM 生成回复)
            for comment in comments:
                if comment.like_count > 10:  # 只回复热门评论
                    # 使用 LLM 生成回复
                    reply_prompt = f"请回复这条评论：{comment.content}"
                    response = await self.model.ainvoke([HumanMessage(content=reply_prompt)])
                    reply_content = cast(str, response.content)[:100]  # 限制回复长度

                    # 发送回复
                    success = await client.reply_to_comment(
                        comment_id=comment.comment_id,
                        post_id=post_id,
                        reply=reply_content,
                    )

                    if success:
                        engagement_actions.append(
                            EngagementAction(
                                action_type="reply_comment",
                                target_id=comment.comment_id,
                                content=reply_content,
                                timestamp=datetime.now(UTC).isoformat(),
                            )
                        )

            # 4. 处理私信
            for dm in dms[:5]:  # 只处理前5条
                # 使用 LLM 生成回复
                reply_prompt = f"请回复这条私信：{dm.content}"
                response = await self.model.ainvoke([HumanMessage(content=reply_prompt)])
                reply_content = cast(str, response.content)[:200]

                success = await client.send_dm(
                    user_id=dm.sender_id,
                    message=reply_content,
                )

                if success:
                    engagement_actions.append(
                        EngagementAction(
                            action_type="reply_dm",
                            target_id=dm.message_id,
                            content=reply_content,
                            timestamp=datetime.now(UTC).isoformat(),
                        )
                    )

            logger.info(f"完成 {len(engagement_actions)} 个互动操作")

        except Exception as e:
            logger.error(f"互动处理失败: {e}")
            # Record the failure for observability without failing the workflow —
            # the post was already published successfully. Mirrors the
            # optimization_error pattern: derive_status ignores engagement_error
            # so a completed workflow stays COMPLETED (setting the generic
            # ``error`` field would flip it to ERROR since engagement has no
            # next_nodes).
            engagement_error = str(e)

        finally:
            await client.close()

        # 沉淀受众偏好到长期记忆
        if store is not None and engagement_actions:
            try:
                from backend.memory.store import MemoryManager

                account_id = state.get("account_id", "default")
                mm = MemoryManager(account_id)
                reply_count = sum(
                    1 for a in engagement_actions if a["action_type"] == "reply_comment"
                )
                dm_count = sum(1 for a in engagement_actions if a["action_type"] == "reply_dm")
                await mm.store_audience_preference(
                    store,
                    f"互动偏好: {reply_count} 评论回复, {dm_count} 私信回复",
                    {"source": "engagement", "post_id": publish_result.get("post_id", "")},
                )
            except Exception as e:
                logger.warning(f"Failed to store audience preference: {e}")

        mode = state.get("execution_mode", "single")

        if mode == "single":
            return {
                "engagement_actions": engagement_actions,
                "phase": WorkflowPhase.COMPLETED,
                "engagement_error": engagement_error,
            }

        return {
            "engagement_actions": engagement_actions,
            "phase": WorkflowPhase.ENGAGING,
            "engagement_error": engagement_error,
        }
