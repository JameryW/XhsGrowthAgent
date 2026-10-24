"""Assert anti-detect camouflage and fake signing stay hard-deleted."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def test_ci_stealth_hard_delete_gate_passes() -> None:
    path = REPO / "scripts" / "gates" / "stealth_default_off.py"
    proc = subprocess.run([sys.executable, str(path)], check=False, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "stealth_hard_delete: ok" in proc.stdout


def test_playwright_stealth_not_in_pyproject() -> None:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "playwright-stealth" not in text
    assert "playwright_stealth" not in text
    assert "fake-useragent" not in text


def test_login_module_has_no_stealth_helpers() -> None:
    src = (REPO / "backend" / "services" / "xhs_login.py").read_text(encoding="utf-8")
    assert "_apply_stealth" not in src
    assert "_stealth_injection_enabled" not in src
    assert "XHS_BROWSER_STEALTH" not in src
    assert "playwright_stealth" not in src
    assert "navigator.webdriver" not in src
    assert "AutomationControlled" not in src
