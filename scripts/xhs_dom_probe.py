#!/usr/bin/env python3
"""XHS 发布页 DOM 回归探针 — CLI 入口.

用法:
  python3 scripts/xhs_dom_probe.py [--cdp URL] [--cookie STR] [--no-headless]

环境变量（CLI 参数优先）:
  XHS_CDP_ENDPOINT  CDP 连接真实 Chrome
  XHS_COOKIE        cookie 字符串

无 cookie 且无 CDP → graceful skip，退出码 0（CI 友好）。
任一关键选择器 fail → 退出码 1。
"""

from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="XHS publish page DOM regression probe")
    parser.add_argument("--cdp", default=os.environ.get("XHS_CDP_ENDPOINT", ""))
    parser.add_argument("--cookie", default=os.environ.get("XHS_COOKIE", ""))
    parser.add_argument("--no-headless", action="store_true", help="show browser window")
    parser.add_argument("--json", action="store_true", help="print full JSON report")
    args = parser.parse_args()

    import asyncio

    from backend.services.xhs_dom_probe import run_probe

    report = asyncio.run(
        run_probe(
            cookie=args.cookie,
            cdp_endpoint=args.cdp,
            headless=not args.no_headless,
        )
    )

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        if report.skipped:
            print(f"SKIP: {report.error}")
            return 0
        if report.error:
            # probe exception (not graceful skip) → real failure
            print(f"ERROR: {report.error}")
            return 1
        print(f"URL: {report.url}")
        for f in report.findings:
            mark = "✓" if f.passed else "✗"
            print(f"  {mark} {f.name}: count={f.count}  ({f.selector})")
            if not f.passed and f.html_snippet:
                print(f"      snippet: {f.html_snippet[:200]}")
        print(f"\n{'ALL PASS' if report.all_passed else 'SOME FAIL'}")

    # graceful skip → 0; probe error/some fail → 1; all pass → 0
    if report.skipped:
        return 0
    if report.error:
        return 1
    return 0 if report.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
