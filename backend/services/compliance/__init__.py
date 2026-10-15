"""Deterministic compliance lexicon scanning (P0-4)."""

from backend.services.compliance.lexicon import (
    LexiconHit,
    LexiconScanResult,
    scan_text,
)

__all__ = ["LexiconHit", "LexiconScanResult", "scan_text"]
