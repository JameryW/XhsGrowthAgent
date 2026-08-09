#!/usr/bin/env python3
"""Acceptance audit for the public Showcase and workflow replay pages.

The live pass verifies that the deployed public surface is private-by-default.
Deployments with intentionally approved public cases can opt into the matrix
with ``--allow-existing-public``; the report keeps that live empty-state check
distinguishable from the synthetic fixture pass.
The matrix pass uses a deliberately synthetic, non-sensitive case fixture so the
visual, keyboard and accessibility gates can run before a real case is approved
for publication.

Examples:
    python scripts/acceptance/public_ux_audit.py
    python scripts/acceptance/public_ux_audit.py --base-url https://staging.example
    python scripts/acceptance/public_ux_audit.py --screenshot-dir /tmp/public-ux
    python scripts/acceptance/public_ux_audit.py --network-profile slow-4g \
        --save-data --max-combinations 4
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import statistics
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, Route, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = os.getenv("PUBLIC_UX_BASE_URL", "http://127.0.0.1:8889").rstrip("/")
AXE_SCRIPT = REPO_ROOT / "frontend" / "node_modules" / "axe-core" / "axe.min.js"
VIEWPORTS = (320, 390, 768, 1024, 1280, 1440)
LOCALES = ("zh-CN", "en")
THEMES = ("light", "dark")
MOTIONS = ("normal", "reduced")
CASE_ID = "case-demo"
NAVIGATION_TIMEOUT_MS = 20_000
AXE_TIMEOUT_MS = 30_000
WARM_NAVIGATION_BUDGET_MS = 500
CACHED_SELECT_BUDGET_MS = 100
PERFORMANCE_SAMPLE_COUNT = 3
PAGE_READY_ATTEMPTS = 2
NETWORK_PROFILES: dict[str, dict[str, int | str]] = {
    "online": {},
    "slow-4g": {
        "latency": 150,
        "downloadThroughput": 1_600_000,
        "uploadThroughput": 750_000,
        "connectionType": "cellular4g",
    },
}

PERFORMANCE_INIT_SCRIPT = """(() => {
  const state = { lcp_ms: null, cls: 0 };
  window.__publicUxVitals = state;
  window.__publicUxNavigationStartedAt = performance.now();
  try {
    new PerformanceObserver((list) => {
      const entries = list.getEntries();
      if (entries.length) state.lcp_ms = entries[entries.length - 1].startTime;
    }).observe({ type: 'largest-contentful-paint', buffered: true });
  } catch {}
  try {
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) state.cls += entry.value;
      }
    }).observe({ type: 'layout-shift', buffered: true });
  } catch {}
})();"""

SAVE_DATA_INIT_SCRIPT = """(() => {
  const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
  if (!connection) return;
  try {
    Object.defineProperty(connection, 'saveData', { configurable: true, get: () => true });
  } catch {}
})();"""

CASE: dict[str, Any] = {
    "public_id": CASE_ID,
    "title": "春日通勤的轻量仪式感",
    "summary": "从洞察到发布的完整创作过程。",
    "status": "completed",
    "phase": "completed",
    "workflow_mode": "trend",
    "created_at": "2026-07-16T10:00:00Z",
    "updated_at": "2026-07-16T10:00:00Z",
    "featured": True,
    "replay_available": True,
    "result_preview": {"title": "春日通勤的轻量仪式感", "topic": "春日通勤"},
}
STEPS: list[dict[str, Any]] = [
    {
        "public_id": "step-scout",
        "step": 1,
        "phase": "scouting",
        "title": "趋势洞察",
        "summary": "找到内容方向",
        "created_at": None,
        "has_result": True,
        "result_kind": "scouting",
        "result": {"topic": "春日通勤"},
    },
    {
        "public_id": "step-create",
        "step": 2,
        "phase": "creating",
        "title": "内容产出",
        "summary": "完成标题和正文",
        "created_at": None,
        "has_result": True,
        "result_kind": "creating",
        "result": {"title": "春日通勤的轻量仪式感", "summary": "正文产出"},
    },
    {
        "public_id": "step-publish",
        "step": 3,
        "phase": "publishing",
        "title": "发布决策",
        "summary": "准备发布",
        "created_at": None,
        "has_result": True,
        "result_kind": "publishing",
        "result": {"publish": {"status": "published"}},
    },
]


def json_response(route: Route, body: object, status: int = 200) -> None:
    route.fulfill(
        status=status,
        content_type="application/json",
        body=json.dumps({"success": True, "data": body, "error": None}),
    )


def install_mock_api(page: Page) -> None:
    """Install only public API fixtures; all non-public requests stay real."""

    def handle(route: Route) -> None:
        url = route.request.url
        if "/api/public/telemetry" in url:
            route.fulfill(status=204, body="")
        elif "/api/public/showcase/cases/" in url:
            json_response(route, {**CASE, "result": CASE["result_preview"]})
        elif "/api/public/showcase/cases" in url:
            json_response(
                route,
                {
                    "cases": [CASE],
                    "total": 1,
                    "limit": 100,
                    "offset": 0,
                    "featured_public_id": CASE_ID,
                },
            )
        elif f"/api/public/replays/{CASE_ID}/manifest" in url:
            json_response(
                route,
                {
                    "public_id": CASE_ID,
                    "view": "key",
                    "steps": STEPS,
                    "offset": 0,
                    "limit": 20,
                    "total_steps": len(STEPS),
                    "key_step_count": len(STEPS),
                    "technical_step_count": len(STEPS),
                    "has_more": False,
                    "technical_steps_available": False,
                    "workflow": CASE,
                },
            )
        elif f"/api/public/replays/{CASE_ID}/final-summary" in url:
            json_response(
                route,
                {
                    "public_id": CASE_ID,
                    "status": "completed",
                    "result": CASE["result_preview"],
                    "stable": True,
                },
            )
        elif f"/api/public/replays/{CASE_ID}/checkpoints/" in url:
            step_id = url.rsplit("/", 1)[-1].split("?", 1)[0]
            step = next(item for item in STEPS if item["public_id"] == step_id)
            json_response(route, step)
        else:
            route.continue_()

    page.route("**/api/public/**", handle)


def assert_no_horizontal_overflow(page: Page) -> dict[str, int]:
    metrics = page.evaluate(
        """({
          innerWidth: window.innerWidth,
          docWidth: document.documentElement.scrollWidth,
          bodyWidth: document.body.scrollWidth
        })"""
    )
    if metrics["docWidth"] > metrics["innerWidth"] or metrics["bodyWidth"] > metrics["innerWidth"]:
        raise AssertionError(f"horizontal overflow: {metrics}")
    return metrics


def collect_web_vitals(page: Page) -> dict[str, float | None]:
    return page.evaluate(
        """() => {
          const navigation = performance.getEntriesByType('navigation')[0];
          const lcpEntries = performance.getEntriesByType('largest-contentful-paint');
          const layoutShifts = performance.getEntriesByType('layout-shift');
          const cls = layoutShifts
            .filter(entry => !entry.hadRecentInput)
            .reduce((sum, entry) => sum + entry.value, 0);
          return {
            response_end_ms: navigation ? navigation.responseEnd : null,
            dom_content_loaded_ms: navigation ? navigation.domContentLoadedEventEnd : null,
            load_event_ms: navigation ? navigation.loadEventEnd : null,
            lcp_ms: window.__publicUxVitals?.lcp_ms
              ?? (lcpEntries.length ? lcpEntries[lcpEntries.length - 1].startTime : null),
            cls: window.__publicUxVitals?.cls ?? cls,
          };
        }"""
    )


def scan_axe(page: Page) -> list[dict[str, Any]]:
    result = page.evaluate(
        f"""async () => {{
          if (!window.axe) return {{error: 'axe global was not installed'}};
          const audit = await Promise.race([
            window.axe.run(document, {{
              runOnly: {{
                type: 'tag',
                values: ['wcag2a', 'wcag2aa', 'best-practice'],
              }},
            }}),
            new Promise((_, reject) => setTimeout(
              () => reject(new Error('axe scan timed out after {AXE_TIMEOUT_MS}ms')),
              {AXE_TIMEOUT_MS},
            )),
          ]);
          return {{
            violations: audit.violations
              .filter(item => item.impact === 'serious' || item.impact === 'critical')
              .map(item => ({{
                id: item.id,
                impact: item.impact,
                help: item.help,
                helpUrl: item.helpUrl,
                nodes: item.nodes.map(node => ({{
                  target: node.target,
                  failureSummary: node.failureSummary,
                }})),
              }})),
          }};
        }}"""
    )
    if result.get("error"):
        raise AssertionError(result["error"])
    return result["violations"]


def wait_for_page(page: Page, selector: str, *, settle_ms: int = 80) -> None:
    page.wait_for_selector(selector, state="visible")
    # The selector is the user-visible readiness signal. Waiting for networkidle
    # would make the audit depend on telemetry/auth requests that intentionally
    # remain background work on public pages.
    if settle_ms:
        page.wait_for_timeout(settle_ms)


def wait_for_heading(page: Page, text: str) -> None:
    page.evaluate(
        """expected => new Promise((resolve, reject) => {
          const matches = () => [...document.querySelectorAll('#step-detail-heading')].some(
            element => {
              const style = window.getComputedStyle(element);
              return style.display !== 'none'
                && style.visibility !== 'hidden'
                && element.getClientRects().length > 0
                && element.textContent?.includes(expected);
            },
          );
          if (matches()) {
            resolve(true);
            return;
          }
          const observer = new MutationObserver(() => {
            if (!matches()) return;
            observer.disconnect();
            resolve(true);
          });
          observer.observe(document.body, { childList: true, characterData: true, subtree: true });
          window.setTimeout(() => {
            observer.disconnect();
            reject(new Error(`heading did not become visible: ${expected}`));
          }, 8_000);
        })""",
        text,
    )


def wait_for_motion_settle(page: Page) -> None:
    """Wait for finite presentation animations before visual/accessibility scans."""

    # Give IntersectionObserver and the first Vue paint one frame to enqueue
    # reveal transitions before checking the Web Animations timeline.
    page.wait_for_timeout(50)
    page.wait_for_function(
        """() => document.getAnimations().every(animation => {
          const timing = animation.effect?.getComputedTiming?.();
          return animation.playState === 'finished'
            || animation.playState === 'idle'
            || timing?.iterations === Infinity;
        })""",
        timeout=3_000,
    )


def ensure_step_list_visible(page: Page) -> None:
    """Keep mobile's collapsible step list open across route-query updates."""

    content = page.locator("#replay-steps-content:visible").first
    if content.count() > 0:
        return
    page.locator('button[aria-controls="replay-steps-content"]:visible').first.click()
    page.locator("#replay-steps-content:visible").first.wait_for(state="visible")
    wait_for_motion_settle(page)


def click_visible_step(page: Page, step_id: str) -> None:
    """Click the current visible step even while Vue replaces route-keyed DOM."""

    page.evaluate(
        """stepId => new Promise((resolve, reject) => {
          const findTarget = () => [...document.querySelectorAll('[data-step-id]')].find(
            element => {
              const style = window.getComputedStyle(element);
              return element.getAttribute('data-step-id') === stepId
                && style.display !== 'none'
                && style.visibility !== 'hidden'
                && element.getClientRects().length > 0;
            },
          );
          const observer = new MutationObserver(() => {
            const target = findTarget();
            if (!target) return;
            observer.disconnect();
            window.clearTimeout(timeoutId);
            target.click();
            resolve(true);
          });
          const timeoutId = window.setTimeout(() => {
            observer.disconnect();
            reject(new Error(`missing visible step: ${stepId}`));
          }, 8_000);
          const target = findTarget();
          if (target) {
            observer.disconnect();
            window.clearTimeout(timeoutId);
            target.click();
            resolve(true);
            return;
          }
          observer.observe(document.body, { childList: true, subtree: true });
        })""",
        step_id,
    )


def measure_cached_select_to_render(
    page: Page,
) -> tuple[float, float, float, list[float], list[float], list[float]]:
    """Warm the step cache, then take repeated samples returning to the first result."""

    total_samples: list[float] = []
    dispatch_samples: list[float] = []
    ready_wait_samples: list[float] = []
    for _ in range(PERFORMANCE_SAMPLE_COUNT):
        ensure_step_list_visible(page)
        click_visible_step(page, "step-create")
        wait_for_heading(page, "内容产出")
        wait_for_motion_settle(page)
        ensure_step_list_visible(page)
        measurement = page.evaluate(
            """({ stepId, expectedHeading }) => new Promise((resolve, reject) => {
              const findTarget = () => [...document.querySelectorAll('[data-step-id]')].find(
                element => {
                  const style = window.getComputedStyle(element);
                  return element.getAttribute('data-step-id') === stepId
                    && style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && element.getClientRects().length > 0;
                },
              );
              const headingMatches = () => [
                ...document.querySelectorAll('#step-detail-heading'),
              ].some(
                element => {
                  const style = window.getComputedStyle(element);
                  return style.display !== 'none'
                    && style.visibility !== 'hidden'
                    && element.getClientRects().length > 0
                    && element.textContent?.includes(expectedHeading);
                },
              );
              const targetObserver = new MutationObserver(() => startMeasurement());
              const timeoutId = window.setTimeout(() => {
                targetObserver.disconnect();
                reject(new Error(`missing visible step: ${stepId}`));
              }, 8_000);
              const startMeasurement = () => {
                const target = findTarget();
                if (!target) return;
                targetObserver.disconnect();
                window.clearTimeout(timeoutId);
                const startedAt = performance.now();
                let dispatchMs = 0;
                const observer = new MutationObserver(() => {
                  if (!headingMatches()) return;
                  observer.disconnect();
                  resolve({
                    totalMs: performance.now() - startedAt,
                    dispatchMs,
                  });
                });
                observer.observe(document.body, {
                  childList: true,
                  characterData: true,
                  subtree: true,
                });
                target.click();
                dispatchMs = performance.now() - startedAt;
                if (headingMatches()) {
                  observer.disconnect();
                  resolve({ totalMs: performance.now() - startedAt, dispatchMs });
                }
                window.setTimeout(() => {
                  observer.disconnect();
                  reject(new Error(`heading did not become visible: ${expectedHeading}`));
                }, 8_000);
              };
              targetObserver.observe(document.body, { childList: true, subtree: true });
              startMeasurement();
            })""",
            {"stepId": "step-scout", "expectedHeading": "趋势洞察"},
        )
        total_ms = round(float(measurement["totalMs"]), 2)
        dispatch_ms = round(float(measurement["dispatchMs"]), 2)
        ready_wait_ms = round(max(total_ms - dispatch_ms, 0), 2)
        total_samples.append(total_ms)
        dispatch_samples.append(dispatch_ms)
        ready_wait_samples.append(ready_wait_ms)

    return (
        round(float(statistics.median(total_samples)), 2),
        round(float(statistics.median(dispatch_samples)), 2),
        round(float(statistics.median(ready_wait_samples)), 2),
        total_samples,
        dispatch_samples,
        ready_wait_samples,
    )


def measure_warm_navigation(page: Page, selector: str) -> dict[str, Any]:
    """Take repeated warm reload samples and retain raw observations for review."""

    wall_samples: list[float] = []
    reload_samples: list[float] = []
    ready_wait_samples: list[float] = []
    for _ in range(PERFORMANCE_SAMPLE_COUNT):
        for attempt in range(PAGE_READY_ATTEMPTS):
            started_at = time.perf_counter()
            try:
                page.reload(wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
                reload_ms = round((time.perf_counter() - started_at) * 1000, 2)
                ready_started_at = time.perf_counter()
                wait_for_page(page, selector, settle_ms=0)
                wall_ms = round(
                    float(
                        page.evaluate(
                            """() => performance.now() - (
                              window.__publicUxNavigationStartedAt || performance.now()
                            )"""
                        )
                    ),
                    2,
                )
                ready_wait_ms = round((time.perf_counter() - ready_started_at) * 1000, 2)
                wall_samples.append(wall_ms)
                reload_samples.append(reload_ms)
                ready_wait_samples.append(ready_wait_ms)
                break
            except PlaywrightTimeoutError:
                if attempt + 1 >= PAGE_READY_ATTEMPTS:
                    raise

    return {
        "wall_ms": round(float(statistics.median(wall_samples)), 2),
        "reload_ms": round(float(statistics.median(reload_samples)), 2),
        "ready_wait_ms": round(float(statistics.median(ready_wait_samples)), 2),
        "wall_samples_ms": wall_samples,
        "reload_samples_ms": reload_samples,
        "ready_wait_samples_ms": ready_wait_samples,
    }


def audit_page(
    page: Page,
    *,
    name: str,
    url: str,
    ready_selector: str,
    expected_theme: str | None,
    expected_locale: str | None,
    axe_script: Path,
    screenshot: Path | None = None,
) -> dict[str, Any]:
    for attempt in range(PAGE_READY_ATTEMPTS):
        started_at = time.perf_counter()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
            wait_for_page(page, ready_selector)
            break
        except PlaywrightTimeoutError:
            if attempt + 1 >= PAGE_READY_ATTEMPTS:
                raise
    wall_ms = round((time.perf_counter() - started_at) * 1000, 2)
    wait_for_motion_settle(page)
    overflow = assert_no_horizontal_overflow(page)
    if expected_theme:
        html_class = (page.locator("html").get_attribute("class") or "").split()
        is_dark = "dark" in html_class
        if is_dark != (expected_theme == "dark"):
            raise AssertionError(f"theme mismatch: expected={expected_theme}, class={html_class}")
    if expected_locale:
        actual_locale = page.evaluate("localStorage.getItem('language') || 'zh-CN'")
        if actual_locale != expected_locale:
            raise AssertionError(
                f"locale mismatch: expected={expected_locale}, actual={actual_locale}"
            )
    page.add_script_tag(path=str(axe_script))
    violations = scan_axe(page)
    if screenshot:
        screenshot.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(screenshot), full_page=True)
    return {
        "name": name,
        "url": url,
        "wall_ms": wall_ms,
        "overflow": overflow,
        "web_vitals": collect_web_vitals(page),
        "axe_serious_critical": violations,
    }


def percentile(values: list[float], percentage: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return round(values[0], 2)
    return round(statistics.quantiles(values, n=100, method="inclusive")[int(percentage) - 1], 2)


def summarize_metrics(records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = (
        "wall_ms",
        "response_end_ms",
        "dom_content_loaded_ms",
        "load_event_ms",
        "lcp_ms",
        "cls",
        "warm_wall_ms",
        "cached_select_to_render_ms",
    )
    summary: dict[str, Any] = {}
    for field in fields:
        values: list[float] = []
        for record in records:
            if field in {"wall_ms", "warm_wall_ms", "cached_select_to_render_ms"}:
                value = record.get(field)
            else:
                value = record["web_vitals"].get(field)
            if isinstance(value, (int, float)):
                values.append(float(value))
        summary[field] = {
            "count": len(values),
            "p50": percentile(values, 50),
            "p75": percentile(values, 75),
            "p95": percentile(values, 95),
        }
    return summary


def apply_network_profile(page: Page, network_profile: str) -> None:
    settings = NETWORK_PROFILES[network_profile]
    if not settings:
        return
    cdp = page.context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send("Network.emulateNetworkConditions", {"offline": False, **settings})


def run_audit(
    base_url: str,
    screenshot_dir: Path | None,
    max_combinations: int | None = None,
    network_profile: str = "online",
    save_data: bool = False,
    allow_existing_public: bool = False,
) -> dict[str, Any]:
    browser_path = shutil.which("chromium-browser") or shutil.which("chromium")
    if not browser_path:
        raise RuntimeError("Chromium executable not found; install Chromium or set PATH")
    if not AXE_SCRIPT.is_file():
        raise RuntimeError(
            f"axe-core browser script not found: {AXE_SCRIPT}; run npm install in frontend"
        )

    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    performance_outliers: list[dict[str, Any]] = []
    performance_sample_outliers: list[dict[str, Any]] = []
    performance_budget_failures: list[dict[str, Any]] = []
    live_record: dict[str, Any] | None = None
    live_public_case_count = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=browser_path,
            headless=False,
            args=["--no-sandbox"],
            timeout=NAVIGATION_TIMEOUT_MS,
        )

        live_context = browser.new_context(viewport={"width": 390, "height": 844})
        live_context.add_init_script(PERFORMANCE_INIT_SCRIPT)
        if save_data:
            live_context.add_init_script(SAVE_DATA_INIT_SCRIPT)
        live_page = live_context.new_page()
        live_page.set_default_timeout(8000)
        apply_network_profile(live_page, network_profile)
        live_page.goto(f"{base_url}/", wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT_MS)
        live_page.locator("#cases h3").first.wait_for(state="visible")
        live_public_case_count = live_page.locator(".case-card").count()
        if live_public_case_count != 0 and not allow_existing_public:
            raise AssertionError("live public list is not private-by-default")
        live_record = audit_page(
            live_page,
            name="live/showcase-empty",
            url=f"{base_url}/",
            ready_selector="#cases h3",
            expected_theme=None,
            expected_locale=None,
            axe_script=AXE_SCRIPT,
            screenshot=(screenshot_dir / "live-showcase-empty.png") if screenshot_dir else None,
        )
        if live_page.locator(".case-card").count() != live_public_case_count:
            raise AssertionError("live public list changed during the audit")
        records.append(live_record)
        live_context.close()

        combinations = [
            (width, locale, theme, motion)
            for width in VIEWPORTS
            for locale in LOCALES
            for theme in THEMES
            for motion in MOTIONS
        ]
        if max_combinations is not None:
            combinations = combinations[:max_combinations]

        for motion in MOTIONS:
            motion_combinations = [item for item in combinations if item[3] == motion]
            if not motion_combinations:
                continue
            context = browser.new_context(
                viewport={"width": motion_combinations[0][0], "height": 844},
                reduced_motion="reduce" if motion == "reduced" else "no-preference",
            )
            context.add_init_script(PERFORMANCE_INIT_SCRIPT)
            if save_data:
                context.add_init_script(SAVE_DATA_INIT_SCRIPT)
            context.add_init_script(
                """(() => {
                  const [locale, theme, storageMode] = window.name.split('::');
                  if (storageMode !== 'keep') {
                    localStorage.clear();
                    sessionStorage.clear();
                  }
                  if (locale) localStorage.setItem('language', locale);
                  if (theme) localStorage.setItem('xhs-theme-mode', theme);
                })();"""
            )
            try:
                for width, locale, theme, _motion in motion_combinations:
                    page = context.new_page()
                    page.set_default_timeout(8000)
                    install_mock_api(page)
                    apply_network_profile(page, network_profile)
                    label = f"fixture/{width}/{locale}/{theme}/{motion}"
                    try:
                        page.set_viewport_size({"width": width, "height": 844})
                        page.evaluate(f"window.name = {json.dumps(f'{locale}::{theme}::reset')}")
                        showcase_screenshot = None
                        replay_screenshot = None
                        if (
                            screenshot_dir
                            and width in (390, 1440)
                            and locale == "en"
                            and theme == "dark"
                            and motion == "reduced"
                        ):
                            showcase_screenshot = (
                                screenshot_dir / f"showcase-{width}-{locale}-{theme}-{motion}.png"
                            )
                            replay_screenshot = (
                                screenshot_dir / f"replay-{width}-{locale}-{theme}-{motion}.png"
                            )
                        showcase_record = audit_page(
                            page,
                            name=f"{label}/showcase",
                            url=f"{base_url}/",
                            ready_selector="#featured-heading",
                            expected_theme=theme,
                            expected_locale=locale,
                            axe_script=AXE_SCRIPT,
                            screenshot=showcase_screenshot,
                        )
                        page.evaluate(f"window.name = {json.dumps(f'{locale}::{theme}::keep')}")
                        warm_measurement = measure_warm_navigation(page, "#featured-heading")
                        showcase_record["warm_wall_ms"] = warm_measurement["wall_ms"]
                        showcase_record["warm_reload_ms"] = warm_measurement["reload_ms"]
                        showcase_record["warm_ready_wait_ms"] = warm_measurement["ready_wait_ms"]
                        showcase_record["warm_wall_samples_ms"] = warm_measurement[
                            "wall_samples_ms"
                        ]
                        showcase_record["warm_reload_samples_ms"] = warm_measurement[
                            "reload_samples_ms"
                        ]
                        showcase_record["warm_ready_wait_samples_ms"] = warm_measurement[
                            "ready_wait_samples_ms"
                        ]
                        records.append(showcase_record)
                        if showcase_record["warm_wall_ms"] > WARM_NAVIGATION_BUDGET_MS:
                            performance_outliers.append(
                                {
                                    "name": f"{label}/showcase-warm",
                                    "error": (
                                        f"warm navigation exceeded {WARM_NAVIGATION_BUDGET_MS}ms: "
                                        f"{showcase_record['warm_wall_ms']}ms"
                                    ),
                                }
                            )
                        performance_sample_outliers.extend(
                            {
                                "name": f"{label}/showcase-warm/sample-{index}",
                                "value_ms": value,
                                "budget_ms": WARM_NAVIGATION_BUDGET_MS,
                            }
                            for index, value in enumerate(
                                showcase_record["warm_wall_samples_ms"], start=1
                            )
                            if value > WARM_NAVIGATION_BUDGET_MS
                        )
                        if page.locator('a[href*="/replay/case-demo"]').count() < 1:
                            raise AssertionError("fixture showcase has no replay link")
                        replay_record = audit_page(
                            page,
                            name=f"{label}/replay",
                            url=f"{base_url}/replay/{CASE_ID}?from=%2F",
                            ready_selector="#step-detail-heading",
                            expected_theme=theme,
                            expected_locale=locale,
                            axe_script=AXE_SCRIPT,
                            screenshot=replay_screenshot,
                        )
                        if page.locator("[data-step-id]").count() != len(STEPS):
                            raise AssertionError("fixture replay step count mismatch")
                        ensure_step_list_visible(page)
                        phase = page.locator('[data-phase-index="0"]')
                        phase.focus()
                        page.keyboard.press("ArrowRight")
                        active_phase = page.evaluate(
                            "document.activeElement?.getAttribute('data-phase-index')"
                        )
                        if active_phase != "1":
                            raise AssertionError(
                                f"phase keyboard navigation failed: {active_phase}"
                            )
                        (
                            replay_record["cached_select_to_render_ms"],
                            replay_record["cached_select_click_ms"],
                            replay_record["cached_select_ready_wait_ms"],
                            replay_record["cached_select_to_render_samples_ms"],
                            replay_record["cached_select_click_samples_ms"],
                            replay_record["cached_select_ready_wait_samples_ms"],
                        ) = measure_cached_select_to_render(page)
                        records.append(replay_record)
                        if replay_record["cached_select_to_render_ms"] > CACHED_SELECT_BUDGET_MS:
                            performance_outliers.append(
                                {
                                    "name": f"{label}/replay-cached-select",
                                    "error": (
                                        f"cached select exceeded {CACHED_SELECT_BUDGET_MS}ms: "
                                        f"{replay_record['cached_select_to_render_ms']}ms"
                                    ),
                                }
                            )
                        performance_sample_outliers.extend(
                            {
                                "name": f"{label}/replay-cached-select/sample-{index}",
                                "value_ms": value,
                                "budget_ms": CACHED_SELECT_BUDGET_MS,
                            }
                            for index, value in enumerate(
                                replay_record["cached_select_to_render_samples_ms"], start=1
                            )
                            if value > CACHED_SELECT_BUDGET_MS
                        )
                    except (AssertionError, PlaywrightTimeoutError) as error:
                        failures.append({"name": label, "error": str(error)})
                    finally:
                        page.close()
            finally:
                context.close()

        browser.close()

    axe_records = [record for record in records if record["axe_serious_critical"]]
    metrics = summarize_metrics(records)
    for field, budget, label in (
        ("warm_wall_ms", WARM_NAVIGATION_BUDGET_MS, "warm navigation"),
        ("cached_select_to_render_ms", CACHED_SELECT_BUDGET_MS, "cached select"),
    ):
        p75 = metrics[field]["p75"]
        if isinstance(p75, (int, float)) and p75 > budget:
            performance_budget_failures.append(
                {
                    "name": f"matrix/{field}-p75",
                    "error": f"{label} p75 exceeded {budget}ms: {p75}ms",
                }
            )
    if network_profile == "online":
        failures.extend(performance_budget_failures)
    return {
        "base_url": base_url,
        "network_profile": network_profile,
        "save_data": save_data,
        "allow_existing_public": allow_existing_public,
        "fixture": "synthetic-non-sensitive-case-demo",
        "viewports": list(VIEWPORTS),
        "locales": list(LOCALES),
        "themes": list(THEMES),
        "motions": list(MOTIONS),
        "live_public_case_count": live_public_case_count,
        "live_private_by_default": live_record is not None and live_public_case_count == 0,
        "live_empty_state_verified": live_public_case_count == 0,
        "matrix_page_count": len(records) - 1,
        "records": records,
        "metrics": metrics,
        "axe_serious_critical_record_count": len(axe_records),
        "performance_outliers": performance_outliers,
        "performance_sample_count": PERFORMANCE_SAMPLE_COUNT,
        "performance_sample_outliers": performance_sample_outliers,
        "performance_budget_enforced": network_profile == "online",
        "performance_budget_failures": performance_budget_failures,
        "failures": failures,
        "passed": not failures and not axe_records,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", default=DEFAULT_BASE_URL, help="deployed frontend/backend origin"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("/tmp/public-ux-audit.json"),
        help="JSON evidence output path",
    )
    parser.add_argument(
        "--screenshot-dir",
        type=Path,
        help="optional directory for representative full-page screenshots",
    )
    parser.add_argument(
        "--max-combinations",
        type=int,
        help="limit fixture combinations for a quick local smoke; the default runs the full matrix",
    )
    parser.add_argument(
        "--network-profile",
        choices=tuple(NETWORK_PROFILES),
        default="online",
        help="browser network profile; use slow-4g for constrained-network evidence",
    )
    parser.add_argument(
        "--save-data",
        action="store_true",
        help="expose navigator.connection.saveData=true during the audit",
    )
    parser.add_argument(
        "--allow-existing-public",
        action="store_true",
        help=(
            "run the matrix when the deployment has owner-approved public cases; "
            "does not certify an empty private-by-default state"
        ),
    )
    args = parser.parse_args()

    result = run_audit(
        args.base_url.rstrip("/"),
        args.screenshot_dir,
        args.max_combinations,
        args.network_profile,
        args.save_data,
        args.allow_existing_public,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "passed": result["passed"],
                "network_profile": result["network_profile"],
                "save_data": result["save_data"],
                "allow_existing_public": result["allow_existing_public"],
                "live_public_case_count": result["live_public_case_count"],
                "live_empty_state_verified": result["live_empty_state_verified"],
                "matrix_page_count": result["matrix_page_count"],
                "axe_serious_critical_record_count": result["axe_serious_critical_record_count"],
                "performance_outlier_count": len(result["performance_outliers"]),
                "performance_sample_outlier_count": len(result["performance_sample_outliers"]),
                "performance_budget_enforced": result["performance_budget_enforced"],
                "performance_budget_failure_count": len(result["performance_budget_failures"]),
                "metrics": result["metrics"],
                "failures": result["failures"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
