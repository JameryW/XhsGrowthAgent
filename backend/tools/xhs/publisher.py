"""XHS publisher tool — 发布小红书笔记."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.tools import tool

from backend.tools.runtime.models import DomainOutcome

if TYPE_CHECKING:
    from backend.services.xhs_publisher import XHSPublisher

logger = logging.getLogger("xhs_growth.tools.publisher")


def _get_publisher(cdp_endpoint: str = "") -> XHSPublisher:
    """获取 XHSPublisher 实例.

    ``cdp_endpoint`` 为空时回落到全局配置 —— 这就是控制面路径（P2a-S3 的
    Action Executor）今天的做法，不要动它。主链会**按账号**解析出 endpoint
    （``get_account_cdp_endpoint``）并显式传入：多账号发布靠这个参数区分浏览器
    profile，把全局值写死在这里会让多账号发布静默回到第一个账号的登录态。
    """
    from backend.config.settings import Settings
    from backend.services.xhs_publisher import XHSPublisher

    settings = Settings()
    return XHSPublisher(
        cookie="",
        headless=False,
        cdp_endpoint=(cdp_endpoint or "").strip() or settings.platform.cdp_endpoint,
    )


@tool
async def xhs_publisher(
    title: str,
    body: str,
    hashtags: list[str] | None = None,
    image_paths: list[str] | None = None,
    category: str = "",
    location: str = "",
    scheduled_time: str = "",
    is_private: bool = False,
    account_id: str = "",
    idempotency_key: str = "",
    cdp_endpoint: str = "",
) -> dict[str, Any]:
    """发布小红书笔记.

    Args:
        title: 笔记标题
        body: 正文内容
        hashtags: 标签列表 (最多5个)
        image_paths: 图片路径列表
        category: 内容分类
        location: 发布地点
        scheduled_time: 定时发布时间
        is_private: 是否仅自己可见
        account_id: 发布所属账号（用于按账号记账的发布冷却）
        cdp_endpoint: 目标浏览器 profile 的 CDP 地址。留空 = 用全局配置；
            主链按账号解析后显式传入（多账号发布靠它）
        idempotency_key: 请求级幂等键。**本工具不用它去重**——它是运行时
            重试护栏的输入（见 ``RetryPolicy.requires_idempotency_key``），
            以及运营排查用的关联 id；内容级去重由发布主链的
            ``compute_publish_id`` 负责。

    Returns:
        发布结果: post_id, status, post_url

    Raises:
        DomainOutcome: 平台层给出了结论（拒发、冷却中、CDP 忙、或"提交了但
            结果不明"）。结论不是抖动，所以它作为**答案**上报，而不是作为
            运行时失败——否则一次超时/结论都会被当成"可以重试"。
        Exception: 平台调用本身抛错（网络、浏览器、取消）。这类失败没有结论，
            按运行时失败上报。

    这个工具以前把异常吞成一个 ``{"status": "error"}`` 字典，于是 Gateway 只能
    看到"成功的一次调用"。去除那层归一化是 P1c 迁移清单的第一条：**归一化只在
    Gateway 一个归属地**，工具层第二个安静的归一化器正是两边开始不一致的原因。
    """
    if hashtags is None:
        hashtags = []
    if image_paths is None:
        image_paths = []
    logger.info(f"Publishing note: {title}")

    publisher = _get_publisher(cdp_endpoint)
    try:
        result = await publisher.publish_note(
            title=title,
            body=body,
            image_paths=image_paths,
            hashtags=hashtags[:5],
            category=category,
            location=location,
            scheduled_time=scheduled_time,
            is_private=is_private,
            account_id=account_id,
        )
    finally:
        await publisher.close()

    status = str(result.get("status") or "")
    if status == "published":
        return {
            "post_id": str(result.get("post_id") or ""),
            # The service answers with ``url`` on the success path and
            # ``post_url`` on its blocked paths; normalising to one name here
            # keeps that split from reaching the receipt.
            "post_url": str(result.get("post_url") or result.get("url") or ""),
            "status": status,
            "published_at": str(result.get("published_at") or ""),
        }

    # Every other status is the platform layer's own verdict -- including
    # ``unknown``/``pending`` ("a submit went out and the answer was lost"),
    # which must never arrive as retryable.  One payload, one reader:
    # ``creator_agent.execution.interpret_publish_result``.
    #
    # ``DomainOutcome`` takes the verdict positionally and everything else as
    # keyword payload -- passing ``payload=dict(result)`` would bury the whole
    # dict one level down, where the reader's ``status`` lookup would miss it
    # and every verdict would arrive as an unexplained failure.
    verdict = {str(key): value for key, value in result.items() if str(key).isidentifier()}
    verdict.pop("reason", None)  # the positional argument owns that name
    raise DomainOutcome(
        str(result.get("error") or status or "publish rejected"),
        **verdict,
    )


@tool
async def ab_test_manager(
    base_post_id: str,
    variant_titles: list[str],
    duration_hours: int = 4,
) -> dict[str, Any]:
    """管理 A/B 测试 — 对比不同标题/封面的表现.

    Args:
        base_post_id: 基础帖子 ID
        variant_titles: 变体标题列表 (最多3个)
        duration_hours: 测试持续时间

    Returns:
        A/B 测试配置结果
    """
    logger.info(f"Setting up A/B test for post: {base_post_id}")

    import time

    test_id = f"ab_{int(time.time())}"

    return {
        "test_id": test_id,
        "base_post_id": base_post_id,
        "variants": [
            {"variant_id": f"v{i}", "title": title} for i, title in enumerate(variant_titles[:3])
        ],
        "duration_hours": duration_hours,
        "start_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "configured",
        "note": "需要数据库支持存储测试数据",
    }


@tool
async def post_scheduler(
    post_id: str,
    publish_time: str,
) -> dict[str, Any]:
    """调度帖子在最佳时间发布.

    Args:
        post_id: 帖子 ID
        publish_time: 发布时间 (格式: "2024-03-15 18:00")

    Returns:
        调度结果
    """
    logger.info(f"Scheduling post {post_id} for {publish_time}")

    return {
        "scheduled": True,
        "post_id": post_id,
        "publish_time": publish_time,
        "scheduler_note": "需要集成 APScheduler 实现真实调度",
        "status": "configured",
    }
