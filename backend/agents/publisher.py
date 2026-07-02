"""Publisher agent — handles posting workflow and A/B testing."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, cast

from langgraph.store.base import BaseStore

from backend.agents.base import BaseAgent
from backend.config.models import TaskType
from backend.config.settings import Settings
from backend.services.text_cover import generate_text_cover_image
from backend.state.schema import WorkflowPhase, XHSGrowthState

logger = logging.getLogger("xhs_growth.agents.publisher")


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


class PublisherAgent(BaseAgent):
    task_type = TaskType.PUBLISHING
    agent_name = "publisher"
    prompt_file = "publisher.yaml"

    async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]:
        # 获取配置
        settings = Settings()
        use_browser = settings.platform.use_browser

        # Read publish options from review decision (overrides defaults)
        publish_options = state.get("publish_options") or {}
        is_dry_run = publish_options.get("dry_run", False)

        if is_dry_run or not use_browser:
            if is_dry_run:
                logger.info("dry_run=True，执行试运行发布")
            else:
                logger.warning("use_browser=False，跳过真实发布")
            # 返回模拟结果
            import datetime

            publish_result = {
                "post_id": f"mock_{state.get('session_id', '0')}",
                "post_url": "https://www.xiaohongshu.com/explore/mock",
                "published_at": datetime.datetime.now().isoformat(),
                "ab_variant": None,
                "status": "mock_published",
                "account_id": publish_options.get("account_id") or state.get("account_id", ""),
            }
            return {
                "publish_result": publish_result,
                "phase": WorkflowPhase.PUBLISHING,
            }

        return await run_publish(state, store)


async def run_publish(state: XHSGrowthState | dict[str, Any], store: BaseStore) -> dict[str, Any]:
    """Execute the real (non-dry-run) publish against Xiaohongshu.

    Extracted from PublisherAgent.execute so failed-publish retries (the
    /api/workflow/publish-retry endpoint) can re-run just the publish step
    with the workflow's existing content, without re-running the creation
    chain or honoring dry_run. Returns the same shape as execute.
    """
    copy = state.get("copy_content", {})
    plan = state.get("content_plan", {})
    publish_options = state.get("publish_options") or {}
    publish_account_id = publish_options.get("account_id")
    settings = Settings()

    # 解析发布账号的 cookie: 选定 account_id 优先, 否则 fallback 全局活跃账号
    cookie = settings.platform.cookie
    user_id = settings.platform.user_id
    if publish_account_id:
        from backend.db.accounts import get_account_cookie

        cookie, user_id = await get_account_cookie(publish_account_id)
        if not cookie:
            logger.error(f"账号 {publish_account_id} 未配置 XHS_COOKIE，无法发布")
            publish_result = {
                "post_id": "",
                "post_url": "",
                "status": "failed",
                "error": f"账号 {publish_account_id} 未配置 cookie",
                "error_type": "no_cookie",
                # Structured recovery dict — same shape as
                # classify_publish_error() returns, so Dashboard.vue's
                # publishError.recovery.{hint,action,action_label} renders.
                "recovery": {
                    "message": "该账号未配置 XHS_COOKIE，无法发布",
                    "action": "reconfigure",
                    "action_label": "重新配置",
                    "hint": "请在设置页为该账号配置 XHS_COOKIE",
                },
            }
            return {
                "publish_result": publish_result,
                "phase": WorkflowPhase.PUBLISHING,
            }
        logger.info(f"按选中账号 {publish_account_id} 发布")

    # 调用真实发布服务
    from backend.services.xhs_client import XHSClient, XHSPost

    client = XHSClient(
        cookie=cookie,
        user_id=user_id,
        use_browser=True,
        headless=settings.platform.headless,
        cdp_endpoint=settings.platform.cdp_endpoint,
    )

    try:
        # 从 visual_plan 提取图片路径
        visual = state.get("visual_plan", {}) or {}
        image_paths = _as_str_list(visual.get("image_paths"))
        if not image_paths:
            # 尝试从 generated_images 提取
            image_paths = _as_str_list(visual.get("generated_images"))
        if not image_paths:
            title = copy.get("selected_title") or plan.get("selected_topic") or "小红书笔记"
            output_dir = Path("/tmp/xhs_generated_covers") / str(
                state.get("session_id") or "default"
            )
            cover_path = generate_text_cover_image(
                title=str(title),
                key_points=_as_str_list(plan.get("key_points")),
                color_palette=_as_str_list(visual.get("color_palette")),
                output_dir=output_dir,
            )
            image_paths = [cover_path]
            logger.info("无素材图，已生成文字封面: %s", cover_path)

        # 构造发布数据
        post = XHSPost(
            title=copy.get("selected_title", ""),
            body=copy.get("body_text", ""),
            hashtags=copy.get("hashtags", []),
            image_paths=image_paths,
            category=cast(str, plan.get("category", "")),
            location=cast(str, plan.get("location", "")),
            is_private=False,
            scheduled_time=plan.get("suggested_timing", ""),
        )

        # 执行发布
        result = await client.publish_post(post)

        publish_result = {
            "post_id": result.get("post_id", ""),
            "post_url": result.get("post_url", ""),
            "published_at": result.get("published_at", ""),
            "ab_variant": cast(Any, None),
            "status": result.get("status", "unknown"),
        }

        logger.info(f"发布完成: {publish_result['post_id']}")

    except Exception as e:
        logger.error(f"发布失败: {e}")
        from backend.api.errors import classify_publish_error

        error_type, recovery = classify_publish_error(str(e))
        publish_result = {
            "post_id": "",
            "post_url": "",
            "status": "failed",
            "error": str(e),
            "error_type": error_type.value,
            "recovery": recovery,
        }

    finally:
        await client.close()

    # 记录到长期记忆
    account_id = state.get("account_id", "default")
    if publish_result.get("post_id"):
        try:
            from backend.memory.content_history import ContentHistory

            history = ContentHistory(account_id)
            # Include IDs for calibration chain and content_type for recall filtering
            visual_plan = state.get("visual_plan", {})
            await history.record(
                store,
                post_id=cast(str, publish_result["post_id"]),
                data={
                    "title": copy.get("selected_title", ""),
                    "topic": plan.get("selected_topic", ""),
                    "hashtags": copy.get("hashtags", []),
                    "published_at": publish_result.get("published_at", ""),
                    "status": publish_result.get("status", ""),
                    "content_type": plan.get("content_type", ""),
                    "style_id": visual_plan.get("style_id", ""),
                    "play_id": plan.get("play_id", ""),
                },
            )
        except Exception as e:
            logger.warning(f"记录发布历史失败: {e}")

    return {
        "publish_result": publish_result,
        "phase": WorkflowPhase.PUBLISHING,
    }
