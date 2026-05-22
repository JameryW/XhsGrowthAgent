"""XHS engagement tools."""

from langchain_core.tools import tool


@tool
async def comment_replier(comment_id: str, reply_content: str) -> dict:
    """回复小红书评论"""
    return {"comment_id": comment_id, "reply": reply_content, "status": "sent"}


@tool
async def dm_handler(message_id: str, reply_content: str) -> dict:
    """处理小红书私信"""
    return {"message_id": message_id, "reply": reply_content, "status": "sent"}


@tool
async def escalation_flagger(content: str, reason: str = "") -> dict:
    """标记需要人工处理的互动（负面评论、投诉等）"""
    return {"escalated": True, "content": content, "reason": reason}