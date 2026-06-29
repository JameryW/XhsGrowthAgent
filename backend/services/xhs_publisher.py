"""小红书 Playwright 发布器 — 浏览器自动化发布流程.

使用 Playwright 实现复杂的发布操作，包括:
- 图片上传
- 文案填写
- 标签选择
- 发布时间设置
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from typing import TYPE_CHECKING, Any

# ponytail: playwright is an optional [browser] extra. Import it lazily so the
# module is importable (and unit-testable with a mock Page) without it installed.
# `from __future__ import annotations` keeps the Browser/Page annotations as
# strings, so they never force a runtime import.
if TYPE_CHECKING:
    from playwright.async_api import Browser, Page

logger = logging.getLogger("xhs_growth.publisher")


class XHSPublisher:
    """Playwright-based 小红书发布器"""

    CREATOR_URL = "https://creator.xiaohongshu.com/publish/publish"
    LOGIN_URL = "https://creator.xiaohongshu.com/login"

    def __init__(
        self,
        cookie: str,
        headless: bool = True,
        cookie_storage_path: str = "",
        slow_mo: int = 100,  # 每步操作延迟 (ms)
    ):
        self.cookie = cookie
        self.headless = headless
        self.cookie_storage_path = cookie_storage_path or os.path.expanduser("~/.xhs_cookies.json")
        self.slow_mo = slow_mo
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def _ensure_browser(self) -> Browser:
        """确保浏览器已启动"""
        if self._browser is None:
            from playwright.async_api import async_playwright  # lazy: optional [browser] extra

            playwright = await async_playwright().start()
            self._browser = await playwright.chromium.launch(
                headless=self.headless,
                slow_mo=self.slow_mo,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
        return self._browser

    async def _ensure_page(self) -> Page:
        """确保页面已创建并登录"""
        browser = await self._ensure_browser()
        if self._page is None:
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
            # 设置 Cookie
            if self.cookie:
                await self._set_cookies(context)
            self._page = await context.new_page()
            # 首次访问设置 localStorage
            await self._page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
            """)
        return self._page

    async def _set_cookies(self, context) -> None:
        """设置登录 Cookie"""
        cookies = []
        for item in self.cookie.split(";"):
            item = item.strip()
            if "=" in item:
                name, value = item.split("=", 1)
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".xiaohongshu.com",
                    "path": "/",
                })
        await context.add_cookies(cookies)

    async def _check_login(self) -> bool:
        """检查登录状态"""
        page = await self._ensure_page()
        await page.goto(self.CREATOR_URL, wait_until="networkidle")

        # 检查是否跳转到登录页
        current_url = page.url
        if "login" in current_url:
            logger.warning("Cookie 已失效，需要重新登录")
            return False

        # 检查是否有发布按钮
        try:
            await page.wait_for_selector("text=发布笔记", timeout=5000)
            return True
        except Exception:
            return False

    async def publish_note(
        self,
        title: str,
        body: str,
        image_paths: list[str],
        hashtags: list[str] | None = None,
        category: str = "",
        location: str = "",
        scheduled_time: str = "",
        is_private: bool = False,
    ) -> dict[str, Any]:
        """发布小红书笔记

        Args:
            title: 笔记标题
            body: 正文内容
            image_paths: 图片路径列表
            hashtags: 标签列表
            category: 内容分类
            location: 发布地点
            scheduled_time: 定时发布时间 (如 "2024-03-15 18:00")
            is_private: 是否仅自己可见

        Returns:
            发布结果: {"post_id": str, "status": str, "url": str}
        """
        if hashtags is None:
            hashtags = []
        page = await self._ensure_page()

        try:
            # 1. 检查登录
            if not await self._check_login():
                return {"post_id": "", "status": "auth_failed", "error": "需要重新登录"}

            # 2. 进入发布页面
            await page.goto(self.CREATOR_URL, wait_until="networkidle")
            await page.wait_for_selector(".publish-container", timeout=10000)
            logger.info("进入发布页面")

            # 3. 上传图片
            await self._upload_images(page, image_paths)
            logger.info(f"上传 {len(image_paths)} 张图片")

            # 4. 填写标题和正文
            await self._fill_content(page, title, body)
            logger.info("填写标题和正文")

            # 5. 添加标签
            if hashtags:
                await self._add_hashtags(page, hashtags)
                logger.info(f"添加 {len(hashtags)} 个标签")

            # 6. 选择分类
            if category:
                await self._select_category(page, category)
                logger.info(f"选择分类: {category}")

            # 7. 设置发布时间
            if scheduled_time:
                await self._set_schedule(page, scheduled_time)
                logger.info(f"设置定时发布: {scheduled_time}")

            # 8. 设置隐私
            if is_private:
                await self._set_private(page)
                logger.info("设置为仅自己可见")

            # 9. 点击发布
            await self._click_publish(page)
            logger.info("点击发布按钮")

            # 10. 等待发布成功
            result = await self._wait_for_success(page)

            return result

        except Exception as e:
            logger.error(f"发布失败: {e}", exc_info=True)
            # ponytail: drop the dirty page (keep the browser) so a retry starts
            # from a clean page instead of a half-filled/erroring one. The
            # caller (XHSClient.publish_post) retries up to 3x; without this
            # reset, _ensure_page returns the same stuck page every attempt.
            if self._page is not None:
                with contextlib.suppress(Exception):
                    await self._page.close()
                self._page = None
            return {"post_id": "", "status": "error", "error": str(e)}

    async def _upload_images(self, page: Page, image_paths: list[str]) -> None:
        """上传图片"""
        # 确保图片文件存在
        valid_paths = []
        for path in image_paths:
            if os.path.exists(path):
                valid_paths.append(path)
            else:
                logger.warning(f"图片不存在: {path}")

        if not valid_paths:
            raise ValueError("没有有效的图片文件")

        # 找到上传按钮
        upload_input = await page.query_selector("input[type=file][accept*=image]")
        if upload_input:
            await upload_input.set_input_files(valid_paths)
            # 等待上传完成
            # ponytail: Playwright Python's wait_for_function takes `arg` (singular),
            # not `args` — `args=` was silently ignored, leaving arguments[0] undefined
            # so `.length >= undefined` was always false → 60s timeout on every publish.
            await page.wait_for_function(
                "document.querySelectorAll('.image-item').length >= arguments[0]",
                arg=len(valid_paths),
                timeout=60000,  # 图片上传可能较慢
            )
        else:
            # 备用方案：点击上传区域
            await page.click(".upload-area, .image-upload-btn")
            await asyncio.sleep(1)
            file_input = await page.query_selector("input[type=file]")
            await file_input.set_input_files(valid_paths)
            await page.wait_for_selector(".image-item", timeout=60000)

    async def _fill_content(self, page: Page, title: str, body: str) -> None:
        """填写标题和正文"""
        # 标题输入框
        title_input = await page.query_selector("input[placeholder*=标题], .title-input")
        if title_input:
            await title_input.fill(title)
        else:
            # 备用方案
            await page.type("input", title, delay=50)

        await asyncio.sleep(0.5)

        # 正文输入框
        body_input = await page.query_selector("textarea[placeholder*=正文], .content-input")
        if body_input:
            await body_input.fill(body)
        else:
            await page.type("textarea", body, delay=30)

    async def _add_hashtags(self, page: Page, hashtags: list[str]) -> None:
        """添加标签"""
        # 点击添加标签按钮
        tag_btn = await page.query_selector("text=添加标签, .tag-btn")
        if tag_btn:
            await tag_btn.click()
            await asyncio.sleep(0.5)

        for tag in hashtags[:5]:  # 小红书最多 5 个标签
            # 输入标签
            tag_input = await page.query_selector("input[placeholder*=输入标签], .tag-input")
            if tag_input:
                await tag_input.fill(tag)
                await asyncio.sleep(0.3)
                # 等待下拉选项出现，选择第一个
                try:
                    await page.click(".tag-option, .tag-dropdown-item", timeout=2000)
                except Exception:
                    # 直接回车
                    await tag_input.press("Enter")

            await asyncio.sleep(0.5)

    async def _select_category(self, page: Page, category: str) -> None:
        """选择内容分类"""
        category_btn = await page.query_selector("text=选择分类, .category-btn")
        if category_btn:
            await category_btn.click()
            await asyncio.sleep(0.5)
            # 点击分类选项
            await page.click(f"text={category}")
            await asyncio.sleep(0.3)

    async def _set_schedule(self, page: Page, scheduled_time: str) -> None:
        """设置定时发布"""
        schedule_btn = await page.query_selector("text=定时发布, .schedule-btn")
        if schedule_btn:
            await schedule_btn.click()
            await asyncio.sleep(0.5)
            # 选择时间
            # 需要根据具体 UI 调整
            await page.fill(".schedule-time-input", scheduled_time)
            await page.click("text=确定")

    async def _set_private(self, page: Page) -> None:
        """设置为仅自己可见"""
        private_btn = await page.query_selector("text=仅自己可见, .private-btn")
        if private_btn:
            await private_btn.click()

    async def _click_publish(self, page: Page) -> None:
        """点击发布按钮"""
        publish_btn = await page.query_selector("text=发布, button.publish-btn")
        if publish_btn:
            await publish_btn.click()
        else:
            # 备用方案
            await page.click("button >> text=发布")

    async def _wait_for_success(self, page: Page) -> dict[str, Any]:
        """等待发布成功并获取结果"""
        try:
            # 等待成功提示
            await page.wait_for_selector("text=发布成功", timeout=30000)

            # 尝试获取笔记 ID
            # 发布成功后通常会跳转到笔记详情页或显示笔记链接
            await asyncio.sleep(2)

            current_url = page.url
            # 从 URL 提取笔记 ID
            post_id = ""
            if "/note/" in current_url:
                import re
                match = re.search(r"/note/(\w+)", current_url)
                if match:
                    post_id = match.group(1)

            return {
                "post_id": post_id,
                "post_url": current_url,
                "status": "published",
                "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

        except Exception as e:
            logger.warning(f"等待发布成功超时: {e}")
            return {
                "post_id": "",
                "status": "pending",
                "error": "发布状态未知，请手动确认",
            }

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