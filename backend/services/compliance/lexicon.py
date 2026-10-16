"""Deterministic forbidden-word scanner — runs before the LLM evaluator."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("xhs_growth.compliance.lexicon")

_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config" / "compliance"

_NICHE_OVERLAYS: dict[str, str] = {
    "医疗": "niche_medical.yaml",
    "保健": "niche_medical.yaml",
    "药品": "niche_medical.yaml",
    "金融": "niche_finance.yaml",
    "投资": "niche_finance.yaml",
}


@dataclass(frozen=True)
class LexiconHit:
    term: str
    category: str
    source: str  # base | niche:<name>


@dataclass
class LexiconScanResult:
    is_blocking: bool
    hits: list[LexiconHit] = field(default_factory=list)
    scanned_chars: int = 0
    niche: str = ""
    lexicons_loaded: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_blocking": self.is_blocking,
            "hits": [asdict(h) for h in self.hits],
            "hit_count": len(self.hits),
            "scanned_chars": self.scanned_chars,
            "niche": self.niche,
            "lexicons_loaded": list(self.lexicons_loaded),
            "highlight_terms": [h.term for h in self.hits],
        }


@lru_cache(maxsize=16)
def _load_yaml(path_str: str) -> dict[str, list[str]]:
    path = Path(path_str)
    if not path.is_file():
        logger.warning("compliance lexicon missing: %s", path)
        return {}
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    categories = raw.get("categories") or {}
    cleaned: dict[str, list[str]] = {}
    for cat, terms in categories.items():
        if not isinstance(terms, list):
            continue
        cleaned[str(cat)] = [str(t).strip() for t in terms if str(t).strip()]
    return cleaned


def _terms_for_niche(niche: str) -> tuple[list[tuple[str, str, str]], list[str]]:
    """Return (term, category, source) triples and loaded file labels."""
    loaded: list[str] = []
    triples: list[tuple[str, str, str]] = []
    base_path = _CONFIG_DIR / "base.yaml"
    for cat, terms in _load_yaml(str(base_path)).items():
        loaded_label = "base"
        for term in terms:
            triples.append((term, cat, loaded_label))
    if "base" not in loaded:
        loaded.append("base")

    niche_key = (niche or "").strip()
    overlay = _NICHE_OVERLAYS.get(niche_key)
    if overlay:
        overlay_path = _CONFIG_DIR / overlay
        label = f"niche:{niche_key}"
        for cat, terms in _load_yaml(str(overlay_path)).items():
            for term in terms:
                triples.append((term, cat, label))
        loaded.append(label)
    # Longest first so "包治百病" wins over shorter substrings for highlight.
    triples.sort(key=lambda item: len(item[0]), reverse=True)
    return triples, loaded


def scan_text(text: str, *, niche: str = "") -> LexiconScanResult:
    """Scan ``text`` against base + niche lexicons. Any hit is blocking."""
    blob = text or ""
    triples, loaded = _terms_for_niche(niche)
    hits: list[LexiconHit] = []
    seen: set[str] = set()
    for term, category, source in triples:
        if term in seen:
            continue
        if term and term in blob:
            seen.add(term)
            hits.append(LexiconHit(term=term, category=category, source=source))
    return LexiconScanResult(
        is_blocking=bool(hits),
        hits=hits,
        scanned_chars=len(blob),
        niche=(niche or "").strip(),
        lexicons_loaded=loaded,
    )


def scan_state_content(state: dict[str, Any]) -> LexiconScanResult:
    """Scan title + body (+ hashtags) from workflow state."""
    copy = state.get("copy_content") or {}
    if not isinstance(copy, dict):
        copy = {}
    title = str(copy.get("selected_title") or "")
    body = str(copy.get("body_text") or "")
    tags = copy.get("hashtags") or []
    tag_blob = " ".join(str(t) for t in tags) if isinstance(tags, list) else ""
    niche = str(state.get("niche") or "")
    return scan_text(f"{title}\n{body}\n{tag_blob}", niche=niche)


def clear_lexicon_cache() -> None:
    """Test helper."""
    _load_yaml.cache_clear()


__all__ = [
    "LexiconHit",
    "LexiconScanResult",
    "clear_lexicon_cache",
    "scan_state_content",
    "scan_text",
]
