"""XHS 发布页 DOM 回归探针 — Playwright 验证上传页结构，不点发布.

XHS 发布页 DOM 会漂移，发布器选择器失效是 silent failure（要 wait_for_function
60s 超时才暴露）。本探针只验关键选择器存在，不上传/不填写/不点发布，作为
发布器（xhs_publisher.py）改动的必跑检查。

复用 XHSPublisher._ensure_browser/_ensure_page/_goto_creator_page 拿已登录 page，
避免重写 CDP/cookie/stealth 逻辑。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("xhs_growth.services.xhs_dom_probe")

# 关键选择器——发布链路依赖的 5 类结构。任一缺失说明 DOM 漂移，发布器需更新。
PROBE_SELECTORS: tuple[tuple[str, str], ...] = (
    (
        "image_upload_input",
        "input[type=file][accept*=jpg], input[type=file][accept*=png], input[type=file][multiple]",
    ),
    ("title_input", "input[placeholder*=标题], .title-input, input.d-text[type=text]"),
    (
        "body_editor",
        ".tiptap.ProseMirror, [contenteditable=true], textarea[placeholder*=正文], .content-input",
    ),
    ("publish_button", ".publish-page-publish-btn button, xhs-publish-btn, button.bg-red"),
    ("publish_container", ".publish-container, .publish-page-publish-btn"),
)


@dataclass
class ProbeFinding:
    """单个选择器探针结果。"""

    name: str
    selector: str
    passed: bool
    count: int = 0
    html_snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "selector": self.selector,
            "passed": self.passed,
            "count": self.count,
            "html_snippet": self.html_snippet,
        }


@dataclass
class ProbeReport:
    """整体探针报告。"""

    findings: list[ProbeFinding] = field(default_factory=list)
    url: str = ""
    error: str = ""
    # skipped=True = intentional no-op (no env configured), not a failure.
    # Distinguishes graceful skip from a probe exception (error set, findings
    # empty, skipped=False → real failure, exit 1).
    skipped: bool = False

    @property
    def all_passed(self) -> bool:
        # empty findings (e.g. graceful skip) is NOT all-pass — require at least
        # one finding and all of them passing.
        return bool(self.findings) and all(f.passed for f in self.findings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "all_passed": self.all_passed,
            "error": self.error,
            "skipped": self.skipped,
            "findings": [f.to_dict() for f in self.findings],
        }


async def probe_publish_page(page: Any) -> ProbeReport:
    """对已导航到发布页的 page 跑结构探针。

    不上传/不填写/不点发布——纯 query_selector/locator.count 验证。失败时抓
    页面 HTML 片段（前 500 字）辅助诊断漂移。
    """
    report = ProbeReport(url=getattr(page, "url", ""))
    # 切到"上传图文"tab——发布页默认停视频 tab，图片 input 不切 tab 不出现，
    # 会误报 image_upload_input 漂移。tab 切换是结构导航，非上传/填写/发布。
    await _switch_to_image_tab(page)
    for name, selector in PROBE_SELECTORS:
        finding = await _probe_one(page, name, selector)
        report.findings.append(finding)
        status = "PASS" if finding.passed else "FAIL"
        logger.info(f"probe {name}: {status} (count={finding.count}) selector={selector!r}")
    return report


async def _switch_to_image_tab(page: Any) -> None:
    """切换到"上传图文"tab（镜像 xhs_publisher._upload_images 的 tab 切换逻辑）。"""
    import contextlib

    try:
        # creator-tab SPA 异步渲染，先等它挂载
        with contextlib.suppress(Exception):
            await page.wait_for_selector("div.creator-tab", state="attached", timeout=10000)
        await page.evaluate(
            """
            () => {
                const tabs = [...document.querySelectorAll('div.creator-tab')];
                const t = tabs.find(t => t.innerText.includes('上传图文')
                    && t.offsetParent !== null);
                if (t) t.click();
            }
            """
        )
    except Exception as exc:
        # tab 切换失败不致命——image_upload_input 可能因此 fail，其余 selector 仍验
        logger.debug(f"tab switch skipped: {exc}")


async def _probe_one(page: Any, name: str, selector: str) -> ProbeFinding:
    try:
        locator = page.locator(selector)
        count = await locator.count()
        passed = count > 0
        snippet = ""
        if not passed:
            # 抓 HTML 片段辅助诊断漂移（只取 body 前 500 字，避免巨量日志）
            try:
                html = await page.content()
                snippet = html[:500]
            except Exception as exc:
                snippet = f"<content() failed: {exc}>"
        return ProbeFinding(
            name=name,
            selector=selector,
            passed=passed,
            count=count,
            html_snippet=snippet,
        )
    except Exception as exc:
        # 探针自身异常不算发布器 bug，但要暴露
        return ProbeFinding(
            name=name,
            selector=selector,
            passed=False,
            count=0,
            html_snippet=f"<probe error: {exc}>",
        )


async def run_probe(
    *,
    cookie: str = "",
    cdp_endpoint: str = "",
    headless: bool = True,
) -> ProbeReport:
    """端到端探针：起浏览器 → 导航发布页 → 跑结构断言 → 关浏览器。

    复用 XHSPublisher 拿已登录 page。无 cookie 且无 CDP → graceful skip
    （返回 error 报告，不抛）。
    """
    if not cookie and not cdp_endpoint:
        report = ProbeReport(
            error="no cookie and no cdp_endpoint — skip (set XHS_COOKIE or XHS_CDP_ENDPOINT)",
            skipped=True,
        )
        logger.warning(report.error)
        return report

    from backend.services.xhs_publisher import XHSPublisher

    publisher = XHSPublisher(
        cookie=cookie,
        headless=headless,
        cdp_endpoint=cdp_endpoint,
    )
    try:
        page = await publisher._ensure_page()
        await publisher._goto_creator_page(page)
        # 登录态校验——cookie 失效会 redirect 到 login 页，此时选择器全 fail
        # 会被误报为 DOM 漂移。先确认不在 login 页。
        if "login" in (page.url or ""):
            report = ProbeReport(url=page.url, error="cookie expired — redirected to login page")
            logger.warning(report.error)
            return report
        # 等发布页就绪（复用 publisher 的就绪探测，不重新发明）
        ready = await publisher._wait_for_publish_ready(page, timeout=15000)
        if not ready:
            report = ProbeReport(url=page.url, error="publish page not ready within 15s")
            logger.warning(report.error)
            return report
        return await probe_publish_page(page)
    except Exception as exc:
        logger.error(f"DOM probe failed: {exc}", exc_info=True)
        return ProbeReport(error=str(exc))
    finally:
        await publisher.close()
