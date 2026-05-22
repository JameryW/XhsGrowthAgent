"""Publisher agent — handles posting workflow and A/B testing."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.config.settings import Settings
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase

logger = logging.getLogger("xhs_growth.agents.publisher")


class PublisherAgent(BaseAgent):
    task_type = TaskType.PUBLISHING
    agent_name = "publisher"
    prompt_file = "publisher.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        copy = state.get("copy_content", {})
        visual = state.get("visual_plan", {})
        plan = state.get("content_plan", {})

        # 获取配置
        settings = Settings()
        use_browser = settings.platform.use_browser

        if not use_browser:
            logger.warning("use_browser=False，跳过真实发布")
            # 返回模拟结果
            import datetime
            publish_result = {
                "post_id": f"mock_{state.get('session_id', '0')}",
                "post_url": "https://www.xiaohongshu.com/explore/mock",
                "published_at": datetime.datetime.now().isoformat(),
                "ab_variant": None,
                "status": "mock_published",
            }
        else:
            # 调用真实发布服务
            from xhs_growth.services.xhs_client import XHSClient, XHSPost

            client = XHSClient(
                cookie=settings.platform.cookie,
                user_id=settings.platform.user_id,
                use_browser=True,
                headless=settings.platform.headless,
            )

            try:
                # 构造发布数据
                post = XHSPost(
                    title=copy.get("selected_title", ""),
                    body=copy.get("body_text", ""),
                    hashtags=copy.get("hashtags", []),
                    image_paths=[],  # 图片路径需要从 visual_plan 获取
                    category=plan.get("category", ""),
                    location=plan.get("location", ""),
                    is_private=False,
                    scheduled_time=plan.get("suggested_timing", ""),
                )

                # 执行发布
                result = await client.publish_post(post)

                publish_result = {
                    "post_id": result.get("post_id", ""),
                    "post_url": result.get("post_url", ""),
                    "published_at": result.get("published_at", ""),
                    "ab_variant": None,
                    "status": result.get("status", "unknown"),
                }

                logger.info(f"发布完成: {publish_result['post_id']}")

            except Exception as e:
                logger.error(f"发布失败: {e}")
                publish_result = {
                    "post_id": "",
                    "post_url": "",
                    "status": "failed",
                    "error": str(e),
                }

            finally:
                await client.close()

        # 记录到长期记忆
        account_id = state.get("account_id", "default")
        if publish_result.get("post_id"):
            from xhs_growth.memory.content_history import ContentHistory

            history = ContentHistory(account_id)
            await history.record(
                store,
                post_id=publish_result["post_id"],
                data={
                    "title": copy.get("selected_title", ""),
                    "topic": plan.get("selected_topic", ""),
                    "hashtags": copy.get("hashtags", []),
                    "published_at": publish_result.get("published_at", ""),
                    "status": publish_result.get("status", ""),
                },
            )

        return {
            "publish_result": publish_result,
            "phase": WorkflowPhase.PUBLISHING,
        }