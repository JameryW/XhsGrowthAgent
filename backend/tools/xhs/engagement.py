"""XHS engagement tools — 评论回复与私信处理."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

if TYPE_CHECKING:
    from backend.services.xhs_client import XHSClient
    from backend.services.xhs_engagement import XHSEngagement

logger = logging.getLogger("xhs_growth.tools.engagement")


def _get_engagement(cdp_endpoint: str = "", account_id: str = "") -> XHSEngagement:
    """获取 XHSEngagement 实例"""
    from backend.config.settings import Settings
    from backend.services.xhs_engagement import XHSEngagement

    settings = Settings()
    return XHSEngagement(
        cookie="",
        headless=False,
        cdp_endpoint=cdp_endpoint or settings.platform.cdp_endpoint,
        account_id=account_id,
    )


async def _resolve_engagement_cdp_endpoint(account_id: str) -> str:
    """Prefer the dedicated Chrome endpoint bound to the selected account."""
    from backend.config.settings import Settings

    settings = Settings()
    endpoint = settings.platform.cdp_endpoint.strip()
    account_id = account_id.strip()
    if account_id:
        try:
            from backend.db.accounts import get_account_cdp_endpoint

            account_endpoint = (await get_account_cdp_endpoint(account_id)).strip()
            if account_endpoint:
                endpoint = account_endpoint
        except Exception as exc:
            logger.warning("无法解析账号 %s 的互动 CDP endpoint: %s", account_id, exc)
    return endpoint


def _get_client() -> XHSClient:
    """获取 XHSClient 实例"""
    from backend.config.settings import Settings
    from backend.services.xhs_client import XHSClient

    settings = Settings()
    return XHSClient(
        use_browser=settings.platform.use_browser,
    )


@tool
async def comment_replier(
    comment_id: str,
    post_id: str,
    reply_content: str,
    account_id: str = "",
) -> dict[str, Any]:
    """回复小红书评论.

    Args:
        comment_id: 评论 ID
        post_id: 笔记 ID
        reply_content: 回复内容

    Returns:
        回复结果: success, reply_id
    """
    logger.info(f"Replying to comment: {comment_id}")

    engagement = _get_engagement(
        cdp_endpoint=await _resolve_engagement_cdp_endpoint(account_id),
        account_id=account_id,
    )
    try:
        result = await engagement.reply_to_comment(
            note_id=post_id,
            comment_id=comment_id,
            reply_content=reply_content,
        )

        return {
            "comment_id": comment_id,
            "post_id": post_id,
            "reply": reply_content,
            "success": result.get("success", False),
            "reply_id": result.get("reply_id", ""),
            "error": result.get("error", ""),
        }

    except Exception as e:
        logger.error(f"回复评论失败: {e}")
        return {
            "comment_id": comment_id,
            "success": False,
            "error": str(e),
        }

    finally:
        await engagement.close()


@tool
async def dm_handler(
    message_id: str,
    sender_id: str,
    reply_content: str,
    account_id: str = "",
) -> dict[str, Any]:
    """处理小红书私信.

    Args:
        message_id: 消息 ID
        sender_id: 发送者用户 ID
        reply_content: 回复内容

    Returns:
        回复结果: success, reply_id
    """
    logger.info(f"Handling DM from: {sender_id}")

    engagement = _get_engagement(
        cdp_endpoint=await _resolve_engagement_cdp_endpoint(account_id),
        account_id=account_id,
    )
    try:
        result = await engagement.send_dm(
            target_user_id=sender_id,
            message=reply_content,
        )

        return {
            "message_id": message_id,
            "sender_id": sender_id,
            "reply": reply_content,
            "success": result.get("success", False),
            "reply_id": result.get("message_id", ""),
            "error": result.get("error", ""),
        }

    except Exception as e:
        logger.error(f"回复私信失败: {e}")
        return {
            "message_id": message_id,
            "success": False,
            "error": str(e),
        }

    finally:
        await engagement.close()


@tool
async def escalation_flagger(
    content: str,
    reason: str = "",
    severity: str = "medium",
) -> dict[str, Any]:
    """标记需要人工处理的互动（负面评论、投诉等）.

    Args:
        content: 需要标记的内容
        reason: 标记原因
        severity: 严重程度 (low/medium/high)

    Returns:
        标记结果: escalated_id, notification_sent
    """
    logger.info(f"Escalating content: {reason}")

    import time

    escalated_id = f"esc_{int(time.time())}"

    result = {
        "escalated": True,
        "escalated_id": escalated_id,
        "content": content,
        "reason": reason,
        "severity": severity,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending_review",
    }

    from backend.config.settings import Settings

    settings = Settings()
    if settings.notification.webhook_url:
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                await client.post(
                    settings.notification.webhook_url,
                    json={
                        "type": "escalation",
                        "data": result,
                    },
                )
                result["notification_sent"] = True
        except Exception as e:
            logger.warning(f"发送通知失败: {e}")
            result["notification_sent"] = False
    else:
        result["notification_sent"] = False

    return result


@tool
async def fetch_pending_comments(post_id: str, limit: int = 20) -> list[dict[str, Any]]:
    """获取待回复的评论列表.

    Args:
        post_id: 笔记 ID
        limit: 获取数量

    Returns:
        评论列表
    """
    logger.info(f"Fetching comments for post: {post_id}")

    client = _get_client()
    try:
        comments = await client.get_comments(post_id=post_id, limit=limit)

        return [
            {
                "comment_id": c.comment_id,
                "post_id": c.post_id,
                "user_name": c.user_name,
                "user_id": c.user_id,
                "content": c.content,
                "like_count": c.like_count,
                "created_at": c.created_at,
            }
            for c in comments
        ]

    except Exception as e:
        logger.error(f"获取评论失败: {e}")
        return []

    finally:
        await client.close()
