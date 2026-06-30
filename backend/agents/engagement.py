"""Engagement agent — manages comments, DMs, and fan interactions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.config.settings import Settings
from backend.state.schema import EngagementAction, WorkflowPhase, XHSGrowthState

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

        engagement_actions = []

        if not publish_result.get("post_id"):
            logger.info("无已发布帖子，跳过互动处理")
            mode = state.get("execution_mode", "single")
            return {
                "engagement_actions": engagement_actions,
                "phase": WorkflowPhase.COMPLETED if mode == "single" else WorkflowPhase.ENGAGING,
            }

        if not use_browser:
            logger.warning("use_browser=False，跳过真实互动")
            mode = state.get("execution_mode", "single")
            return {
                "engagement_actions": engagement_actions,
                "phase": WorkflowPhase.COMPLETED if mode == "single" else WorkflowPhase.ENGAGING,
            }

        # 调用真实互动服务
        from backend.services.xhs_client import XHSClient

        client = XHSClient(
            cookie=settings.platform.cookie,
            user_id=settings.platform.user_id,
            use_browser=True,
            headless=settings.platform.headless,
        )

        try:
            post_id = publish_result.get("post_id")

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
                    reply_content = response.content[:100]  # 限制回复长度

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
                reply_content = response.content[:200]

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

        finally:
            await client.close()

        # 沉淀受众偏好到长期记忆
        if store is not None and engagement_actions:
            try:
                from backend.memory.store import MemoryManager

                account_id = state.get("account_id", "default")
                mm = MemoryManager(account_id)
                reply_count = sum(1 for a in engagement_actions if a.action_type == "reply_comment")
                dm_count = sum(1 for a in engagement_actions if a.action_type == "reply_dm")
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
            }

        return {
            "engagement_actions": engagement_actions,
            "phase": WorkflowPhase.ENGAGING,
        }
