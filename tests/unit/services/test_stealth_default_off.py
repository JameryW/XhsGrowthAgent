"""Assert stealth is opt-in and main deps stay clean."""

from __future__ import annotations

import runpy
from pathlib import Path

from backend.services.xhs_login import _stealth_injection_enabled

REPO = Path(__file__).resolve().parents[3]


def test_stealth_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("XHS_BROWSER_STEALTH", raising=False)
    assert _stealth_injection_enabled() is False


def test_stealth_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("XHS_BROWSER_STEALTH", "1")
    assert _stealth_injection_enabled() is True


def test_fake_useragent_not_in_main_deps() -> None:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    main = text.split("[project.optional-dependencies]", 1)[0]
    assert "fake-useragent" not in main


def test_ci_stealth_gate_script_passes() -> None:
    path = REPO / "scripts" / "gates" / "stealth_default_off.py"
    ns = runpy.run_path(str(path))
    assert ns["main"]() == 0
