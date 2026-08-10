#!/usr/bin/env python3
"""Capture the release-review screenshot archive for the public UX surfaces.

The archive deliberately covers the three review widths and both theme modes.
The live showcase uses the isolated empty-state deployment; the showcase and
replay pages use the same non-sensitive fixture as ``public_ux_audit.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Any

try:
    from scripts.acceptance.public_ux_audit import (
        CASE_ID,
        STEPS,
        install_mock_api,
        wait_for_heading,
        wait_for_motion_settle,
        wait_for_showcase_data,
    )
except ModuleNotFoundError as exc:  # pragma: no cover - direct script execution
    if exc.name != "scripts":
        raise
    from public_ux_audit import (
        CASE_ID,
        STEPS,
        install_mock_api,
        wait_for_heading,
        wait_for_motion_settle,
        wait_for_showcase_data,
    )

DEFAULT_BASE_URL = os.getenv("PUBLIC_UX_BASE_URL", "http://127.0.0.1:8889").rstrip("/")
VIEWPORT_SIZES = ((390, 844), (768, 1024), (1440, 900))
THEMES = ("light", "dark")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def add_storage_init_script(context: Any, theme: str) -> None:
    context.add_init_script(
        f"""(() => {{
          localStorage.clear();
          sessionStorage.clear();
          localStorage.setItem('language', 'en');
          localStorage.setItem('xhs-theme-mode', {json.dumps(theme)});
        }})();""",
    )


def capture(
    page: Any,
    path: Path,
    *,
    surface: str,
    width: int,
    height: int,
    theme: str,
) -> dict[str, Any]:
    page.screenshot(path=str(path), full_page=True)
    overflow = page.evaluate(
        """() => ({
          innerWidth: window.innerWidth,
          documentWidth: document.documentElement.scrollWidth,
          bodyWidth: document.body.scrollWidth,
        })"""
    )
    if (
        overflow["documentWidth"] > overflow["innerWidth"]
        or overflow["bodyWidth"] > overflow["innerWidth"]
    ):
        raise AssertionError(f"horizontal overflow in {surface}: {overflow}")
    return {
        "surface": surface,
        "width": width,
        "height": height,
        "theme": theme,
        "path": path.name,
        "bytes": path.stat().st_size,
        "overflow": overflow,
    }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover - environment guard
        raise SystemExit(f"Playwright is required: {exc}") from exc

    with sync_playwright() as playwright:
        browser_path = shutil.which("chromium-browser") or shutil.which("chromium")
        if not browser_path:
            raise RuntimeError("Chromium executable not found; install Chromium or set PATH")
        browser = playwright.chromium.launch(
            executable_path=browser_path,
            headless=False,
            args=["--no-sandbox"],
        )
        try:
            for width, height in VIEWPORT_SIZES:
                for theme in THEMES:
                    context = browser.new_context(
                        viewport={"width": width, "height": height},
                        reduced_motion="reduce",
                    )
                    add_storage_init_script(context, theme)
                    try:
                        live_page = context.new_page()
                        live_page.goto(f"{args.base_url}/", wait_until="domcontentloaded")
                        wait_for_showcase_data(live_page)
                        if live_page.locator("#cases .case-card").count() != 0:
                            raise AssertionError("live screenshot target is not empty")
                        wait_for_motion_settle(live_page)
                        records.append(
                            capture(
                                live_page,
                                args.output_dir / f"showcase-empty-{width}-{theme}.png",
                                surface="live-showcase-empty",
                                width=width,
                                height=height,
                                theme=theme,
                            )
                        )
                        live_page.close()

                        fixture_page = context.new_page()
                        install_mock_api(fixture_page)
                        fixture_page.goto(f"{args.base_url}/", wait_until="domcontentloaded")
                        wait_for_showcase_data(fixture_page)
                        if fixture_page.locator("#cases .case-card").count() != 1:
                            raise AssertionError("fixture showcase did not render one case")
                        wait_for_motion_settle(fixture_page)
                        records.append(
                            capture(
                                fixture_page,
                                args.output_dir / f"showcase-fixture-{width}-{theme}.png",
                                surface="fixture-showcase",
                                width=width,
                                height=height,
                                theme=theme,
                            )
                        )

                        fixture_page.goto(
                            f"{args.base_url}/replay/{CASE_ID}?from=%2F",
                            wait_until="domcontentloaded",
                        )
                        wait_for_heading(fixture_page, "趋势洞察")
                        if fixture_page.locator("[data-step-id]").count() != len(STEPS):
                            raise AssertionError("fixture replay step count mismatch")
                        wait_for_motion_settle(fixture_page)
                        records.append(
                            capture(
                                fixture_page,
                                args.output_dir / f"replay-fixture-{width}-{theme}.png",
                                surface="fixture-replay",
                                width=width,
                                height=height,
                                theme=theme,
                            )
                        )
                        fixture_page.close()
                    finally:
                        context.close()
        finally:
            browser.close()

    manifest = {
        "base_url": args.base_url,
        "viewports": [{"width": width, "height": height} for width, height in VIEWPORT_SIZES],
        "themes": list(THEMES),
        "surfaces": ["live-showcase-empty", "fixture-showcase", "fixture-replay"],
        "record_count": len(records),
        "records": records,
    }
    (args.output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
