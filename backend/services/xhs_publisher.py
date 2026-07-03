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
import re
import time
from typing import TYPE_CHECKING, Any

# ponytail: match XHS note IDs across the URL shapes the publish flow can land on
# — /note/{id}, /explore/{id}, /discovery/item/{id}. ID is typically 24-hex but
# may contain other word chars; capture the trailing path segment after a known prefix.
_NOTE_ID_RE = re.compile(r"/(?:note|explore|discovery/item)/(\w+)")
_PUBLISH_READY_SELECTORS = (
    ".publish-container",
    "input[type=file][accept*=image]",
    "input[type=file]",
    "input[placeholder*=标题]",
    "textarea[placeholder*=正文]",
    "text=发布笔记",
    "text=发布图文",
)
_PUBLISH_ALERT_KEYWORDS = (
    "未绑定",
    "绑定",
    "手机号",
    "实名",
    "验证码",
    "安全验证",
    "违规",
    "失败",
    "错误",
    "异常",
    "成功",
    "确认",
)
_PUBLISH_BLOCKING_ALERT_KEYWORDS = (
    "未绑定",
    "绑定手机号",
    "手机号",
    "实名",
    "验证码",
    "安全验证",
    "违规",
    "失败",
    "错误",
    "异常",
)

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
        cdp_endpoint: str = "",
    ):
        self.cookie = cookie
        self.headless = headless
        self.cookie_storage_path = cookie_storage_path or os.path.expanduser("~/.xhs_cookies.json")
        self.slow_mo = slow_mo
        # CDP 模式：连接常驻真实 Chrome（用户扫码登录的持久 profile），而非 launch
        # 新浏览器。真实 Chrome 无 playwright/stealth 自动化特征，XHS shield/sec
        # 不拦截——发布提交能正常触发 note/create。设了走 connect_over_cdp，空则
        # fallback 到 launch（被反爬拦截，仅作兼容/测试）。
        self.cdp_endpoint = cdp_endpoint
        self._browser: Browser | None = None
        self._page: Page | None = None

    async def _ensure_browser(self) -> Browser:
        """确保浏览器已启动/连接"""
        if self._browser is None:
            from playwright.async_api import async_playwright  # lazy: optional [browser] extra

            playwright = await async_playwright().start()
            if self.cdp_endpoint:
                # CDP 模式：连接常驻真实 Chrome（profile 自带登录态，不注 stealth/cookie）
                self._browser = await playwright.chromium.connect_over_cdp(self.cdp_endpoint)
                logger.info(f"已通过 CDP 连接真实 Chrome: {self.cdp_endpoint}")
            else:
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
            if self.cdp_endpoint:
                # CDP 模式：用真实 Chrome 已有的 context（profile 自带登录态），
                # 不 new_context / 不注 stealth / 不注 cookie——在已合法的浏览器里
                # 注入伪装脚本或裸 cookie 反而是自动化特征，会被 XHS shield 标红。
                contexts = browser.contexts
                context = contexts[0] if contexts else await browser.new_context()
                self._page = await context.new_page()
                return self._page
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="zh-CN",
            )
            # 反自动化检测：XHS 的 shield/sec 检测 webdriver/CDP/permissions 等指纹，
            # 仅隐藏 navigator.webdriver 不够。用 playwright-stealth 注入全套反检测
            # init script（plugins/webgl/vendor/permissions/ua 等）。可选依赖，未装则
            # fallback 到手动 webdriver 隐藏。
            try:
                from playwright_stealth import Stealth

                # 不覆盖 platform/languages（stealth 默认 Win32/en-US 与真实 Linux UA +
                # zh-CN locale 冲突，指纹不一致反而是自动化特征）。只启用检测隐藏类。
                await Stealth(
                    navigator_platform=False,
                    navigator_languages=False,
                    navigator_languages_override=("zh-CN", "zh"),
                ).apply_stealth_async(context)
                logger.info("playwright-stealth 已应用")
            except Exception as e:
                logger.warning(f"playwright-stealth 不可用，fallback 手动隐藏: {e}")
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => false });"
                )
            # 设置 Cookie
            if self.cookie:
                await self._set_cookies(context)
            self._page = await context.new_page()
        return self._page

    async def _set_cookies(self, context: Any) -> None:
        """设置登录 Cookie"""
        cookies = []
        for item in self.cookie.split(";"):
            item = item.strip()
            if "=" in item:
                name, value = item.split("=", 1)
                cookies.append(
                    {
                        "name": name.strip(),
                        "value": value.strip(),
                        "domain": ".xiaohongshu.com",
                        "path": "/",
                    }
                )
        await context.add_cookies(cookies)

    async def _goto_creator_page(self, page: Page) -> None:
        """Navigate to creator page without waiting for never-idle background traffic."""

        await page.goto(self.CREATOR_URL, wait_until="domcontentloaded", timeout=45000)

    async def _wait_for_publish_ready(self, page: Page, timeout: int = 10000) -> bool:
        """Wait until any known publish control is available."""

        async def _wait(selector: str) -> str:
            await page.wait_for_selector(selector, timeout=timeout)
            return selector

        pending = {asyncio.create_task(_wait(selector)) for selector in _PUBLISH_READY_SELECTORS}
        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    timeout=timeout / 1000,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    return False

                for task in done:
                    try:
                        selector = task.result()
                    except Exception as e:
                        logger.debug(f"发布页选择器未命中: {e}")
                        continue
                    logger.debug(f"发布页已就绪: {selector}")
                    return True
            return False
        finally:
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(Exception, asyncio.CancelledError):
                    await task

    async def _check_login(self) -> bool:
        """检查登录状态"""
        page = await self._ensure_page()
        await self._goto_creator_page(page)

        # 检查是否跳转到登录页
        current_url = page.url
        if "login" in current_url:
            logger.warning("Cookie 已失效，需要重新登录")
            return False

        return await self._wait_for_publish_ready(page, timeout=15000)

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

        # ponytail: 诊断——监听发布相关网络请求，_wait_for_success 失败时 dump，
        # 用于判断"点发布后 XHS 是否真调了发布 API"。发布成功排查依赖此。
        self._publish_requests: list[str] = []

        def _on_resp(resp: Any) -> None:
            try:
                url = resp.url
                # 排除静态资源，只抓动态 API（xhr/fetch）
                if any(
                    url.endswith(s)
                    for s in (".css", ".js", ".png", ".jpg", ".svg", ".woff", ".woff2")
                ):
                    return
                if "fe-static" in url or "xhscdn.com" in url:
                    return
                self._publish_requests.append(f"{resp.status} {resp.request.method} {url[:100]}")
            except Exception:
                pass

        page.on("response", _on_resp)

        try:
            # 1. 检查登录
            if not await self._check_login():
                return {"post_id": "", "status": "auth_failed", "error": "需要重新登录"}

            # 2. 确认发布页面可操作。_check_login 已导航到创作页，避免二次加载。
            if not await self._wait_for_publish_ready(page, timeout=10000):
                raise TimeoutError("发布页加载超时，未找到发布控件")
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

        # ponytail: 创作者发布页默认停在"上传视频"tab，其 file input 的
        # accept=".mp4,.mov,..." 不含 image，首选选择器必 miss。必须先切到
        # "上传图文"tab 才会出现图片 file input。页面上有多个同名隐藏 tab 副本，
        # Playwright 的 locator 会命中 outside-viewport 的隐藏副本而 click 超时，
        # 用 JS 选 offsetParent 非 null 的真实可见 tab 直接 dispatch click。
        # 已在图文 tab 时跳过（重复点会 toggle 回视频 tab）。
        already_img = await page.query_selector(
            "input.upload-input[type=file][accept*=jpg], input[type=file][accept*=png]"
        )
        if not already_img:
            # ponytail: creator-tab 是 SPA 异步渲染，_wait_for_publish_ready 命中
            # 视频 tab 的 file input 就返回了，但 div.creator-tab 此时可能还没
            # 渲染——不等的话下面切 tab 的 querySelectorAll 返回空，clicked=-1，
            # 走 else 备用分支最终超时。先等 tab 渲染出来再切。
            with contextlib.suppress(Exception):
                await page.wait_for_selector("div.creator-tab", state="attached", timeout=10000)
            await page.evaluate("""
                () => {
                    const tabs = [...document.querySelectorAll('div.creator-tab')];
                    const t = tabs.find(t => t.innerText.includes('上传图文')
                        && t.offsetParent !== null);
                    if (t) t.click();
                }
            """)
            # 等图片上传 input 出现。它是 hidden 元素（XHS 用隐藏 input + 可点容器），
            # wait_for_selector 默认等 visible 会超时，用 state="attached" 只等 DOM 挂载。
            try:
                await page.wait_for_selector(
                    "input[type=file][accept*=jpg], input[type=file][accept*=png]",
                    state="attached",
                    timeout=10000,
                )
            except Exception:
                await asyncio.sleep(1)

        # 找到上传 input。现网 class="upload-input"，accept=".jpg,.jpeg,.png,.webp"
        # （不含 "image" 字符串），故用 accept*=jpg / [multiple] 精确定位，避免裸
        # .upload-input 误命中视频 tab 的同名 input。
        upload_input = await page.query_selector(
            "input[type=file][accept*=jpg], input[type=file][accept*=png],"
            " input[type=file][multiple]"
        )
        if upload_input:
            await upload_input.set_input_files(valid_paths)
            # 等待上传完成。上传成功后页面进入编辑态，图片以 .item-picture
            # 容器呈现（.img-list 下），上传区容器随之消失。.image-item 是旧选择器，
            # 现网已不适用——保留兜底以防旧版页面回退。
            # ponytail: Playwright wait_for_function 把 `arg` 作为函数首个参数注入，
            # 不是 arguments 对象——箭头函数里 arguments 不绑定，旧代码 arguments[0]
            # 恒抛 ReferenceError 导致 wait 永不满足→60s 超时。必须声明形参接收。
            await page.wait_for_function(
                "(n) => document.querySelectorAll('.item-picture, .image-item').length >= n",
                arg=len(valid_paths),
                timeout=60000,  # 图片上传可能较慢
            )
        else:
            # 备用方案：点击上传区域触发 file picker（现网容器 .upload-c / .drag-over）
            await page.click(".upload-c, .drag-over, .upload-area, .image-upload-btn")
            await asyncio.sleep(1)
            file_input = await page.query_selector("input[type=file]")
            await file_input.set_input_files(valid_paths)
            await page.wait_for_selector(".item-picture, .image-item", timeout=60000)

    async def _fill_content(self, page: Page, title: str, body: str) -> None:
        """填写标题和正文"""
        # 标题输入框（现网 placeholder="填写标题会有更多赞哦"，class=d-text）
        title_input = await page.query_selector(
            "input[placeholder*=标题], .title-input, input.d-text[type=text]"
        )
        if title_input:
            await title_input.fill(title)
        else:
            # 备用方案
            await page.type("input", title, delay=50)

        await asyncio.sleep(0.5)

        # 正文：现网是 tiptap/ProseMirror 的 contenteditable div（非 textarea），
        # textarea[placeholder*=正文] 在新版页面不存在。fill() 只对 input/textarea
        # 生效，contenteditable 须 click 聚焦后 type。
        body_editor = await page.query_selector(
            ".tiptap.ProseMirror, [contenteditable=true],"
            " textarea[placeholder*=正文], .content-input"
        )
        if body_editor:
            tag = await body_editor.evaluate("el => el.tagName")
            if tag == "TEXTAREA":
                await body_editor.fill(body)
            else:
                # contenteditable: 聚焦后逐字 type（ProseMirror 监听键盘事件入 schema）
                await body_editor.click()
                await asyncio.sleep(0.2)
                await page.keyboard.type(body, delay=30)
        else:
            # 备用方案
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
        # 现网页面会渲染一个可直接点击的提交按钮。优先点这个真实 button；
        # 只有不存在时才回退到 xhs-publish-btn 坐标点击。
        for selector in (
            ".publish-page-publish-btn button.bg-red",
            ".publish-page-publish-btn button",
            "button.bg-red",
        ):
            direct_btn = page.locator(selector)
            if await direct_btn.count() > 0:
                try:
                    await direct_btn.first.click(timeout=15000)
                    logger.info(f"_click_publish: clicked direct submit button {selector}")
                    return
                except Exception as e:
                    logger.warning(f"_click_publish: direct submit click failed {selector}: {e}")

        # 现网发布提交按钮在 <xhs-publish-btn> 的 closed shadow DOM 内
        # （属性暴露：submit-text=发布, submit-disabled=false, save-text=暂存离开）。
        # 点外层标签只触发 tab 切换/展开，不触发内部 submit。现网 shadow 内两个
        # 按钮在底部居中：save 在左，submit 在右；submit 中心约在组件宽度 61%
        # 处。用渲染坐标命中 shadow 内 submit 按钮。
        btn = page.locator("xhs-publish-btn")
        if await btn.count() > 0:
            # 取实际 rect 算右侧坐标（submit 按钮区，约元素右 15%）
            box = await btn.bounding_box()
            if box:
                # 先试点 shadow 内 submit 按钮中心（约组件宽度 61% 处）
                await page.mouse.click(box["x"] + box["width"] * 0.61, box["y"] + box["height"] / 2)
                logger.info("_click_publish: clicked xhs-publish-btn submit region")
                return
            # rect 拿不到则 fallback 元素中心 click
            await btn.first.click()
            logger.info("_click_publish: clicked xhs-publish-btn center (fallback)")
            return

        # 备用：旧选择器
        for sel in (".publish-video", ".btn-wrapper", "button.publish-btn"):
            old = page.locator(sel)
            if await old.count() > 0:
                await old.first.click()
                logger.info(f"_click_publish: fallback clicked {sel}")
                return
        # 最后兜底
        await page.locator("text=发布笔记").first.click()

    async def _collect_visible_alerts(self, page: Page, limit: int = 10) -> list[str]:
        """Collect short visible platform toasts/validation messages."""

        try:
            alerts = await page.evaluate(
                """(arg)=>{
                    const keywords = arg.keywords || [];
                    const limit = arg.limit || 10;
                    const all=[...document.querySelectorAll('*')];
                    return all.filter(e=>e.offsetParent!==null && e.children.length===0)
                        .map(e=>(e.innerText||e.textContent||'').trim())
                        .filter(t=>t && t.length<80)
                        .filter(t=>keywords.some(k=>t.includes(k)))
                        .slice(0, limit);
                }""",
                {"keywords": list(_PUBLISH_ALERT_KEYWORDS), "limit": limit},
            )
        except Exception:
            return []

        return [str(alert) for alert in alerts if str(alert).strip()]

    async def _wait_for_success(self, page: Page) -> dict[str, Any]:
        """等待发布成功并获取结果。

        发布成功后页面通常跳转（离开 /publish/publish）或弹出"发布成功"提示——
        两者任一先到即视为成功，然后从落地页 URL 提取 post_id。
        """
        publish_url = "creator.xiaohongshu.com/publish/publish"
        deadline_left = 30.0
        try:
            latest_alerts: list[str] = []
            # 轮询：URL 离开发布页 或 出现"发布成功"文字，任一先到即成功
            while deadline_left > 0:
                url_now = page.url
                if publish_url not in url_now:
                    # 已跳转离开发布页 → 发布成功
                    break

                alerts = await self._collect_visible_alerts(page)
                if alerts:
                    latest_alerts = alerts
                    blocking_alert = next(
                        (
                            alert
                            for alert in alerts
                            if any(k in alert for k in _PUBLISH_BLOCKING_ALERT_KEYWORDS)
                        ),
                        "",
                    )
                    if blocking_alert:
                        logger.warning(f"发布被平台拦截，页面提示: {alerts}")
                        reqs = getattr(self, "_publish_requests", [])
                        logger.warning(f"发布相关网络请求 ({len(reqs)}): {reqs}")
                        return {
                            "post_id": "",
                            "post_url": "",
                            "status": "failed",
                            "error": blocking_alert,
                        }

                # 检查"发布成功"提示（短轮询，避免长阻塞错过 URL 跳转）
                try:
                    await page.wait_for_selector("text=发布成功", timeout=2000)
                    break
                except Exception:
                    deadline_left -= 2.0
                    continue

            await asyncio.sleep(2)  # 等跳转/渲染稳定

            current_url = page.url
            # 从 URL 提取笔记 ID — 覆盖 /note/, /explore/, /discovery/item/ 几种落地页
            match = _NOTE_ID_RE.search(current_url)
            post_id = match.group(1) if match else ""

            # 仍停在发布页 = 没跳转也没成功提示 → 发布可能未完成
            if publish_url in current_url and not post_id:
                # 诊断：dump 页面提示文字，便于排查"卡在哪"
                try:
                    alerts = await self._collect_visible_alerts(page, limit=5)
                    if not alerts:
                        alerts = latest_alerts
                    logger.warning(f"发布后仍停在发布页，页面提示: {alerts}")
                except Exception:
                    pass
                # 诊断：检测验证码/反爬拦截
                try:
                    captcha = await page.evaluate(
                        """()=>{
                        const html=document.documentElement.outerHTML;
                        const sel='[class*=captcha], [id*=captcha], iframe[src*=captcha]';
                        const hasCaptcha = !!document.querySelector(sel);
                        const keys=['验证','滑块','拼图','拖动','安全验证','人机'];
                        const hasVerify = keys.some(k=>html.includes(k));
                        return {hasCaptcha, hasVerify};
                    }"""
                    )
                    logger.warning(f"验证码检测: {captcha}")
                except Exception:
                    pass
                reqs = getattr(self, "_publish_requests", [])
                logger.warning(f"发布相关网络请求 ({len(reqs)}): {reqs}")
                return {
                    "post_id": "",
                    "status": "pending",
                    "error": "发布状态未知，请手动确认",
                }

            return {
                "post_id": post_id,
                "post_url": current_url,
                "status": "published",
                "published_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            }

        except Exception as e:
            logger.warning(f"等待发布成功异常: {e}")
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

    async def __aenter__(self) -> XHSPublisher:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()
