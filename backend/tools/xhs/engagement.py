"""小红书互动工具。

本模块仅提供人工审核后的单次、显式调用（manual-only）工具。调用前必须由
操作员确认目标账号、目标内容和待发送文本；这些工具不会被工作流 agent
调度、轮询或自动触发。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

if TYPE_CHECKING:
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


@tool
async def comment_replier(
    comment_id: str,
    post_id: str,
    reply_content: str,
    account_id: str = "",
) -> dict[str, Any]:
    """人工确认后回复一条小红书评论（manual-only）。

    仅允许操作员在核对目标和回复内容后显式调用；不会由工作流 agent 自动触发。

    Args:
        comment_id: 评论 ID
        post_id: 笔记 ID
        reply_content: 回复内容

    Returns:
        结果字典：``status``（sent/blocked/failed/unknown）、``success``、
        ``error_code``、``receipt_id``（仅平台回显，无则空）、``receipt_source``、
        ``verified``、``retryable``、``correlation_id``，以及本次请求的目标回显。

    Raises:
        Exception: 平台层抛出的异常**原样向上传**。这里不再把异常归一化成
            ``{"success": False}`` 字典 —— 那会让调用方看到"一次成功的调用"，
            从而分不清"没发出去"和"发了但答复丢了"。归一化只在 Tool Gateway
            一个归属地（见 ``backend/tools/xhs/publisher.py`` 的同一条规则）。
    """
    logger.info(f"Replying to comment: {comment_id}")

    engagement = _get_engagement(
        cdp_endpoint=await _resolve_engagement_cdp_endpoint(account_id),
        account_id=account_id,
    )
    try:
        verdict = await engagement.reply_to_comment(
            note_id=post_id,
            comment_id=comment_id,
            reply_content=reply_content,
        )
    finally:
        await engagement.close()

    return {
        "comment_id": comment_id,
        "post_id": post_id,
        "reply": reply_content,
        **verdict,
    }


@tool
async def dm_handler(
    message_id: str,
    sender_id: str,
    reply_content: str,
    account_id: str = "",
    human_confirmed: bool = False,
) -> dict[str, Any]:
    """人工确认后发送一条小红书私信（manual-only）。

    仅允许操作员在核对收件人和消息内容后显式调用；不会由工作流 agent 自动触发。
    默认仅可回复未读/入站白名单内的用户；冷启动新建私信需显式开关 + human_confirmed。

    Args:
        message_id: 入站消息 ID（原样回显，不是本次发送的回执）
        sender_id: 发送者用户 ID
        reply_content: 回复内容
        human_confirmed: 冷启动外发时的逐条人工确认

    Returns:
        结果字典：``status``（sent/blocked/failed/unknown）、``success``、
        ``error_code``、``receipt_id``（仅平台回显，无则空）、``receipt_source``、
        ``verified``（私信暂无读回，恒为 False）、``retryable``、
        ``correlation_id``，以及本次请求的目标回显。

    Raises:
        Exception: 平台层异常原样向上传，理由同 ``comment_replier``。

    注意 ``status == "sent"`` 的含义是"提交动作已发出且没有反证"，不是"平台已
    确认送达"；后者要等读回能力（见 docs/tool-gateway-engagement-migration.md §5.3）。
    """
    logger.info(f"Handling DM from: {sender_id}")

    engagement = _get_engagement(
        cdp_endpoint=await _resolve_engagement_cdp_endpoint(account_id),
        account_id=account_id,
    )
    try:
        verdict = await engagement.send_dm(
            target_user_id=sender_id,
            message=reply_content,
            human_confirmed=human_confirmed,
        )
    finally:
        await engagement.close()

    return {
        "message_id": message_id,
        "sender_id": sender_id,
        "reply": reply_content,
        **verdict,
    }


@tool
async def escalation_flagger(
    content: str,
    reason: str = "",
    severity: str = "medium",
) -> dict[str, Any]:
    """人工审核后标记需要处理的互动（manual-only）。

    仅允许操作员显式发起，供人工审核流程记录升级事项；不会由工作流 agent 自动触发。

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
async def fetch_pending_comments(
    post_id: str, limit: int = 20, account_id: str = ""
) -> list[dict[str, Any]]:
    """人工审核时获取待回复评论（manual-only）。

    必须由操作员明确发起，且结果只能用于人工审核；不会被工作流 agent 自动轮询或调度。

    **空列表只表示一件事：读到了，确实没有评论。** 读失败一律抛出。这条规则是
    后来补上的，它修的是一个比"异常信息不好看"严重得多的问题：以前这个工具用
    ``XHSClient()``（不带 cookie，``can_read`` 恒为 False）去读，``get_comments``
    在 ``_http is None`` 时**不抛异常、直接返回 ``[]``**，于是它**永远**返回空列表
    —— 一个审核队列的工具恒定回答"没有待办"，而真正的评论一条都没读过。

    Args:
        post_id: 笔记 ID
        limit: 获取数量
        account_id: 用哪个账号的身份读；空 = 部署级凭据（与 trending 侧同一口径）

    Returns:
        评论列表。

    Raises:
        XHSAuthError: 没有可用 cookie。空列表会把它说成"没有待办"，所以在这里停下。
        Exception: 平台层异常原样上抛（``comment_replier`` 同一条规则）。
    """
    from backend.services.xhs_client import client_for_account, require_readable

    logger.info(f"Fetching comments for post: {post_id}")

    client = await client_for_account(account_id)
    try:
        # Inside the ``try`` so the ``finally`` below still closes the client
        # when the guard refuses: the client was already built, and building it
        # may have opened a connection.
        require_readable(client, "fetch_pending_comments")
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

    finally:
        await client.close()
