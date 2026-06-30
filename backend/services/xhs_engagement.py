"""小红书 Playwright 互动器 — 评论回复与私信处理.

使用 Playwright 实现复杂的互动操作:
- 评论回复
- 私信发送
- 关注用户
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from playwright.async_api import Browser, Page, async_playwright

logger = logging.getLogger("xhs_growth.engagement")


class XHSEngagement:
    """Playwright-based 小红书互动器"""

    NOTE_URL_TEMPLATE = "https://www.xiaohongshu.com/explore/{note_id}"
    DM_URL = "https://www.xiaohongshu.com/message"

    def __init__(
        self,
        cookie: str,
        headless: bool = True,
        slow_mo: int = 100,
    ):
        self.cookie = cookie
        self.headless = headless
        self.slow_mo = slow_mo
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def _ensure_browser(self) -> Browser:
        """确保浏览器已启动"""
        if self._browser is None:
            playwright = await async_playwright().start()
            self._browser = await playwright.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
        return self._browser

    async def _ensure_page(self) -> Page:
        """确保页面已创建"""
        browser = await self._ensure_browser()
        if self._page is None:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
            if self.cookie:
                await self._set_cookies(context)
            self._page = await context.new_page()
        return self._page

    async def _set_cookies(self, context) -> None:
        """设置 Cookie"""
        cookies = []
        for item in self.cookie.split(";"):
            if "=" in item.strip():
                name, value = item.strip().split("=", 1)
                cookies.append(
                    {
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".xiaohongshu.com",
                        "path": "/",
                    }
                )
        await context.add_cookies(cookies)

    async def reply_to_comment(
        self,
        note_id: str,
        comment_id: str,
        reply_content: str,
    ) -> dict[str, Any]:
        """回复评论

        Args:
            note_id: 笔记 ID
            comment_id: 评论 ID
            reply_content: 回复内容

        Returns:
            {"success": bool, "reply_id": str}
        """
        page = await self._ensure_page()

        try:
            # 1. 打开笔记页面
            note_url = self.NOTE_URL_TEMPLATE.format(note_id=note_id)
            await page.goto(note_url, wait_until="networkidle")
            await asyncio.sleep(1)

            # 2. 找到目标评论
            # 小红书评论结构: .comment-item[data-id=comment_id]
            comment_selector = f".comment-item[data-id='{comment_id}'], .comment-wrapper"
            await page.wait_for_selector(comment_selector, timeout=10000)

            # 3. 点击评论下的回复按钮
            comment_element = await page.query_selector(comment_selector)
            reply_btn = await comment_element.query_selector("text=回复, .reply-btn")
            if reply_btn:
                await reply_btn.click()
                await asyncio.sleep(0.5)

            # 4. 输入回复内容
            reply_input = await page.query_selector(
                "textarea[placeholder*=回复], .reply-input, input.reply-input"
            )
            if reply_input:
                await reply_input.fill(reply_content)
                await asyncio.sleep(0.3)

                # 5. 点击发送
                send_btn = await page.query_selector("text=发送, button.send-btn")
                if send_btn:
                    await send_btn.click()
                    await asyncio.sleep(1)

                # 6. 等待发送成功
                # 检查回复是否出现在评论列表中
                await page.wait_for_function(
                    """
                    const replies = document.querySelectorAll('.reply-item');
                    return replies.length > 0;
                    """,
                    timeout=5000,
                )

                return {"success": True, "reply_id": f"reply_{int(time.time())}"}

            return {"success": False, "error": "无法找到回复输入框"}

        except Exception as e:
            logger.error(f"回复评论失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def send_dm(
        self,
        target_user_id: str,
        message: str,
    ) -> dict[str, Any]:
        """发送私信

        Args:
            target_user_id: 目标用户 ID
            message: 私信内容

        Returns:
            {"success": bool, "message_id": str}
        """
        page = await self._ensure_page()

        try:
            # 1. 打开私信页面
            await page.goto(self.DM_URL, wait_until="networkidle")
            await asyncio.sleep(2)

            # 2. 搜索目标用户
            # 点击新建私信或搜索
            new_dm_btn = await page.query_selector("text=新建私信, .new-dm-btn")
            if new_dm_btn:
                await new_dm_btn.click()
                await asyncio.sleep(0.5)

            # 3. 输入用户 ID 搜索
            search_input = await page.query_selector("input[placeholder*=搜索], .dm-search-input")
            if search_input:
                await search_input.fill(target_user_id)
                await asyncio.sleep(1)

                # 4. 选择搜索结果
                user_result = await page.query_selector(
                    f".user-item[data-id='{target_user_id}'], .search-result-item"
                )
                if user_result:
                    await user_result.click()
                    await asyncio.sleep(1)

            # 5. 输入私信内容
            dm_input = await page.query_selector("textarea[placeholder*=输入], .dm-input")
            if dm_input:
                await dm_input.fill(message)
                await asyncio.sleep(0.3)

                # 6. 点击发送
                send_btn = await page.query_selector("text=发送, button.send-btn")
                if send_btn:
                    await send_btn.click()
                    await asyncio.sleep(1)

                return {"success": True, "message_id": f"dm_{int(time.time())}"}

            return {"success": False, "error": "无法找到私信输入框"}

        except Exception as e:
            logger.error(f"发送私信失败: {e}", exc_info=True)
            return {"success": False, "error": str(e)}

    async def get_unread_messages(self) -> list[dict[str, Any]]:
        """获取未读私信列表"""
        page = await self._ensure_page()

        try:
            await page.goto(self.DM_URL, wait_until="networkidle")
            await asyncio.sleep(2)

            # 获取未读消息
            unread_items = await page.query_selector_all(".message-item.unread, .unread-badge")
            messages = []

            for item in unread_items:
                sender = await item.query_selector(".sender-name")
                content = await item.query_selector(".message-preview")
                if sender and content:
                    messages.append(
                        {
                            "sender_name": await sender.inner_text(),
                            "preview": await content.inner_text(),
                            "is_unread": True,
                        }
                    )

            return messages

        except Exception as e:
            logger.error(f"获取未读消息失败: {e}")
            return []

    async def close(self) -> None:
        """关闭浏览器"""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
