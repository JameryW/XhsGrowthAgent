#!/usr/bin/env python3
"""CI gate: default browser path must not inject stealth.

Fails if production login code calls ``_apply_stealth`` without the
``XHS_BROWSER_STEALTH`` opt-in guard, or if ``fake-useragent`` is in main deps.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOGIN = ROOT / "backend" / "services" / "xhs_login.py"
PYPROJECT = ROOT / "pyproject.toml"


def main() -> int:
    errors: list[str] = []
    login_src = LOGIN.read_text(encoding="utf-8")
    # Every call site must be guarded by _stealth_injection_enabled().
    call_sites = [m.start() for m in re.finditer(r"await\s+self\._apply_stealth\s*\(", login_src)]
    for pos in call_sites:
        window = login_src[max(0, pos - 400) : pos]
        if "_stealth_injection_enabled" not in window:
            errors.append(
                f"{LOGIN}: _apply_stealth call near offset {pos} is not guarded "
                "by _stealth_injection_enabled()"
            )
    if "def _stealth_injection_enabled" not in login_src:
        errors.append(f"{LOGIN}: missing _stealth_injection_enabled helper")

    pyproject = PYPROJECT.read_text(encoding="utf-8")
    # Main dependencies block only (before optional-dependencies).
    main_deps = pyproject.split("[project.optional-dependencies]", 1)[0]
    if "fake-useragent" in main_deps or "fake_useragent" in main_deps:
        errors.append(f"{PYPROJECT}: fake-useragent must not be in main dependencies")

    sig_src = (ROOT / "backend" / "services" / "xhs_signature.py").read_text(encoding="utf-8")
    if re.search(r"^class\s+XHSSignature\b", sig_src, re.M):
        errors.append("backend/services/xhs_signature.py still defines class XHSSignature")

    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("stealth_default_off: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
