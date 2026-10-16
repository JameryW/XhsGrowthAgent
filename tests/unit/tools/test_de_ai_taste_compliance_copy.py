"""P1-4: de_ai_taste prompt must not imply evading AI labeling."""

from __future__ import annotations

from pathlib import Path


def test_de_ai_taste_yaml_forbids_evading_ai_label():
    path = Path("backend/config/prompts/tools/de_ai_taste.yaml")
    text = path.read_text(encoding="utf-8")
    assert "AI 生成" in text or "AI生成" in text
    assert "规避" in text
    assert "标识" in text
