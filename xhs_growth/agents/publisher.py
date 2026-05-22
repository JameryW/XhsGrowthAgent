"""Publisher agent — handles posting workflow and A/B testing."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.store.base import BaseStore

from xhs_growth.agents.base import BaseAgent
from xhs_growth.config.models import TaskType
from xhs_growth.state.schema import XHSGrowthState, WorkflowPhase


class PublisherAgent(BaseAgent):
    task_type = TaskType.PUBLISHING
    agent_name = "publisher"
    prompt_file = "publisher.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        copy = state.get("copy_content", {})
        visual = state.get("visual_plan", {})
        plan = state.get("content_plan", {})

        # TODO: 调用真实发布 API
        # from xhs_growth.services.xhs_client import XHSClient, XHSPost
        # client = XHSClient(...)
        # post = XHSPost(title=copy.get("selected_title", ""), body=copy.get("body_text", ""), ...)
        # result = await client.publish_post(post)

        publish_result = {
            "post_id": f"mock_{state.get('session_id', '0')}",
            "post_url": "https://www.xiaohongshu.com/explore/mock",
            "published_at": __import__("datetime").datetime.now().isoformat(),
            "ab_variant": None,
            "status": "published",
        }

        # 记录到长期记忆
        account_id = state.get("account_id", "default")
        from xhs_growth.memory.content_history import ContentHistory

        history = ContentHistory(account_id)
        await history.record(
            store,
            post_id=publish_result["post_id"],
            data={
                "title": copy.get("selected_title", ""),
                "topic": plan.get("selected_topic", ""),
                "hashtags": copy.get("hashtags", []),
                "published_at": publish_result["published_at"],
            },
        )

        return {
            "publish_result": publish_result,
            "phase": WorkflowPhase.PUBLISHING,
        }