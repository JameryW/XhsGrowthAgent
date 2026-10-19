"""The capability table in ``docs/tool-runtime.md`` must match the registry.

The table is a *published claim* about the runtime: a reader deciding whether a
capability is safe to retry, or which scope it needs, reads that table and not
the code. Nothing recomputed it, so it drifted — it said "10 capabilities" while
the registry had 12 (search.web / search.fetch were added and the table was not),
and it listed ``xhs.publish`` with a 120s budget when the declaration says 900.

A table nobody recomputes is prose with a border. This file is the recompute:

* capability set: both directions (a missing row and an extra row both fail);
* the heading's count: parsed, not trusted;
* side_effect / pass_style / retry / auth_scope / timeout: compared cell by cell,
  where the timeout is the **effective** one the Gateway enforces
  (``ToolSpec.effective_timeout_s``), not the declared override — the table says
  "what happens", so ``None`` must render its class default.

Formatting is normalised (backticks and ``**`` are documentation, not data), so
re-bolding a cell does not fail the test.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.tools.runtime.catalog import build_registry

DOC = Path(__file__).resolve().parents[4] / "docs" / "tool-runtime.md"

_HEADING = re.compile(r"^##\s*目录[:：]\s*(\d+)\s*个\s*capability", re.MULTILINE)
_CELL_JUNK = str.maketrans("", "", "`*")
DASH = "—"


def _normalise(cell: str) -> str:
    return cell.strip().translate(_CELL_JUNK).strip()


def _table_rows(text: str) -> list[list[str]]:
    match = _HEADING.search(text)
    assert match, "docs/tool-runtime.md lost its 目录 heading"
    block = text[match.end() :]
    lines = []
    for line in block.splitlines():
        if line.startswith("## "):
            break
        if line.startswith("|"):
            lines.append(line)
    rows = []
    for line in lines:
        cells = [_normalise(part) for part in line.strip().strip("|").split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):
            continue  # separator
        if cells and cells[0] == "capability":
            continue  # header
        rows.append(cells)
    return rows


def _expected_row(spec) -> list[str]:
    retry = (
        f"{spec.retry_policy.max_attempts}×{spec.retry_policy.backoff_s:g}s"
        if spec.retry_policy.max_attempts > 1
        else DASH
    )
    scope = ", ".join(spec.auth_scope) if spec.auth_scope else DASH
    timeout = spec.effective_timeout_s
    timeout_text = f"{timeout:.0f}" if float(timeout).is_integer() else f"{timeout:g}"
    return [
        spec.capability,
        spec.side_effect.value,
        spec.pass_style.value,
        retry,
        scope,
        timeout_text,
    ]


def _published() -> dict[str, list[str]]:
    return {row[0]: row for row in _table_rows(DOC.read_text(encoding="utf-8"))}


class TestThePublishedTable:
    def test_the_heading_counts_the_rows_it_has(self):
        text = DOC.read_text(encoding="utf-8")
        declared = int(_HEADING.search(text).group(1))  # type: ignore[union-attr]
        assert declared == len(_table_rows(text))

    def test_every_registered_capability_is_listed(self):
        published = _published()
        missing = sorted(set(build_registry().capabilities()) - set(published))
        assert missing == [], f"capabilities absent from the table: {missing}"

    def test_the_table_lists_nothing_that_does_not_exist(self):
        published = _published()
        extra = sorted(set(published) - set(build_registry().capabilities()))
        assert extra == [], f"the table documents capabilities that are gone: {extra}"

    def test_every_row_matches_the_declaration(self):
        registry = build_registry()
        mismatches = []
        for capability, row in _published().items():
            expected = _expected_row(registry.spec(capability))
            if row != expected:
                mismatches.append(f"{capability}: publishes {row} but declares {expected}")
        assert mismatches == [], "\n  ".join(["", *mismatches])
