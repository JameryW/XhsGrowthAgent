#!/usr/bin/env python3
"""CI gate: anti-detect camouflage and fake HTTP signing must stay gone.

Fails if production code reintroduces playwright-stealth, webdriver-hide
init scripts, AutomationControlled camouflage args, fake-useragent, or the
removed ``XHSSignature`` class.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
PYPROJECT = ROOT / "pyproject.toml"
SIGNATURE = ROOT / "backend" / "services" / "xhs_signature.py"

# Patterns that mean "we are forging or hiding automation fingerprints".
_FORBIDDEN_BACKEND = (
    (re.compile(r"playwright_stealth|\bStealth\b"), "playwright-stealth / Stealth"),
    (re.compile(r"_apply_stealth|_stealth_injection_enabled"), "stealth helpers"),
    (re.compile(r"XHS_BROWSER_STEALTH"), "stealth opt-in env"),
    (
        re.compile(r"navigator\.webdriver|defineProperty\(\s*navigator"),
        "webdriver-hide init script",
    ),
    (
        re.compile(r"disable-blink-features=AutomationControlled"),
        "AutomationControlled camouflage flag",
    ),
    (re.compile(r"fake[_-]?useragent", re.I), "fake-useragent"),
)


def _iter_backend_py() -> list[Path]:
    return sorted(p for p in BACKEND.rglob("*.py") if p.is_file())


def main() -> int:
    errors: list[str] = []

    for path in _iter_backend_py():
        src = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        for pattern, label in _FORBIDDEN_BACKEND:
            if pattern.search(src):
                errors.append(f"{rel}: forbidden {label}")

    pyproject = PYPROJECT.read_text(encoding="utf-8")
    if re.search(r"playwright-stealth|fake-useragent|fake_useragent", pyproject):
        errors.append(
            f"{PYPROJECT.relative_to(ROOT)}: stealth/fake-useragent must not be a dependency"
        )
    if "playwright_stealth" in pyproject:
        errors.append(
            f"{PYPROJECT.relative_to(ROOT)}: playwright_stealth mypy override must stay removed"
        )

    sig_src = SIGNATURE.read_text(encoding="utf-8")
    if re.search(r"^class\s+XHSSignature\b", sig_src, re.M):
        errors.append("backend/services/xhs_signature.py still defines class XHSSignature")
    if re.search(r"generate_x_s|XHS_WEB|md5.*sign", sig_src, re.I):
        errors.append("backend/services/xhs_signature.py reintroduced fake signing logic")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("stealth_hard_delete: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
