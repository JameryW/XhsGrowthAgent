"""Segmented prompt schema (P1b-S3): markers map prompt text to L0-L5 layers.

Red line (task info.md §四): segmentation never rewrites semantic text — the
parser only splits on ``<!-- ctx:<layer> -->`` marker lines and keeps every
other line verbatim.  A prompt without markers degrades to a single L0
segment, so YAML files become progressively layered without any behavior
flip; the S4 agent migrations add markers one file at a time.

Fail-fast rules (same spirit as P0-W2): an unknown layer name or a marker
order that breaks the canonical L0->L5 stability (descending or repeated
layer) raises :class:`SegmentSchemaError` instead of silently producing an
unstable prefix.
"""

from __future__ import annotations

from backend.context.models import LAYER_ORDER, PromptLayer

_MARKER_START = "<!-- ctx:"
_MARKER_END = "-->"


class SegmentSchemaError(ValueError):
    """Raised for malformed segment markers (unknown layer, bad order)."""


def marker_for(layer: PromptLayer) -> str:
    """The canonical marker line for ``layer`` (single source of truth)."""
    return f"{_MARKER_START}{layer.value} {_MARKER_END}"


def _layer_from_marker(line: str) -> PromptLayer:
    name = line.strip()[len(_MARKER_START):-len(_MARKER_END)].strip()
    try:
        return PromptLayer(name)
    except ValueError as exc:
        raise SegmentSchemaError(
            f"unknown prompt layer in segment marker: {name!r}"
        ) from exc


def parse_system_segments(system: str) -> dict[PromptLayer, str]:
    """Split a prompt ``system`` text into L0-L5 segments.

    - Text before the first marker belongs to L0 (the policy header).
    - Segment bodies are kept verbatim; only blank lines at the segment
      edges are trimmed (inner blank lines and indentation untouched).
    - No markers at all -> the whole text is one L0 segment (backward
      compatible with every existing prompt YAML).
    - Markers must appear in canonical L0->L5 order and at most once per
      layer; violations raise :class:`SegmentSchemaError`.
    """
    lines = system.splitlines()
    buckets: dict[PromptLayer, list[str]] = {}
    current: PromptLayer = PromptLayer.L0_SYSTEM  # preamble -> L0
    buckets.setdefault(current, [])
    last_order = -1
    seen: set[PromptLayer] = set()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(_MARKER_START) and stripped.endswith(_MARKER_END):
            layer = _layer_from_marker(stripped)
            order = LAYER_ORDER.index(layer)
            if order < last_order:
                raise SegmentSchemaError(
                    f"segment markers out of canonical order at {layer.value}"
                )
            if layer in seen:
                raise SegmentSchemaError(
                    f"duplicate segment marker for {layer.value}"
                )
            seen.add(layer)
            last_order = order
            current = layer
            buckets.setdefault(current, [])
            continue
        buckets[current].append(line)
    if seen:
        result: dict[PromptLayer, str] = {}
        for layer in LAYER_ORDER:
            if layer not in buckets:
                continue
            text = "\n".join(buckets[layer]).strip("\n")
            if text:
                result[layer] = text
        return result
    return {PromptLayer.L0_SYSTEM: system.strip("\n")}


def segments_equivalent_to_source(system: str) -> bool:
    """The red-line invariant: segmentation preserved every content line.

    True when the non-marker lines of ``system`` appear exactly once, in
    order, across the parsed segments joined in canonical layer order
    (blank-only lines ignored — the parser may collapse edge blanks but
    never rewrites a content line).
    """

    def content_lines(text: str) -> list[str]:
        return [ln for ln in text.splitlines() if ln.strip()]

    source_lines = [
        ln
        for ln in content_lines(system)
        if not (ln.strip().startswith(_MARKER_START) and ln.strip().endswith(_MARKER_END))
    ]
    segments = parse_system_segments(system)
    rebuilt: list[str] = []
    for layer in LAYER_ORDER:
        if layer in segments:
            rebuilt.extend(content_lines(segments[layer]))
    return rebuilt == source_lines


__all__ = [
    "SegmentSchemaError",
    "marker_for",
    "parse_system_segments",
    "segments_equivalent_to_source",
]
