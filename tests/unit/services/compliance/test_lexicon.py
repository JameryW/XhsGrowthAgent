"""P0-4 deterministic lexicon scanner + 50/50 corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.services.compliance.lexicon import scan_state_content, scan_text

CORPUS = Path(__file__).resolve().parents[3] / "fixtures" / "compliance" / "lexicon_corpus.json"


def test_base_hit_is_blocking() -> None:
    result = scan_text("这款产品包治百病，立竿见影")
    assert result.is_blocking is True
    terms = {h.term for h in result.hits}
    assert "包治百病" in terms


def test_clean_text_not_blocking() -> None:
    result = scan_text("周末去公园散步拍到了好看的晚霞")
    assert result.is_blocking is False
    assert result.hits == []


def test_niche_overlay_loads_medical() -> None:
    result = scan_text("祖传秘方偏方治病", niche="医疗")
    assert result.is_blocking is True
    assert any(h.source.startswith("niche:") for h in result.hits)
    assert "niche:医疗" in result.lexicons_loaded


def test_scan_state_content() -> None:
    state = {
        "niche": "穿搭",
        "copy_content": {
            "selected_title": "日常分享",
            "body_text": "稳赚不赔的穿搭投资法",
            "hashtags": ["穿搭"],
        },
    }
    result = scan_state_content(state)
    assert result.is_blocking is True


def test_corpus_fifty_fifty() -> None:
    data = json.loads(CORPUS.read_text(encoding="utf-8"))
    positives = data["positives"]
    negatives = data["negatives"]
    assert len(positives) >= 50
    assert len(negatives) >= 50

    pos_fail = []
    for row in positives:
        result = scan_text(row["text"])
        if not result.is_blocking:
            pos_fail.append(row["id"])
    neg_fail = []
    for row in negatives:
        result = scan_text(row["text"])
        if result.is_blocking:
            neg_fail.append((row["id"], [h.term for h in result.hits]))

    assert not pos_fail, f"positives missed: {pos_fail}"
    assert not neg_fail, f"negatives false-positive: {neg_fail}"
