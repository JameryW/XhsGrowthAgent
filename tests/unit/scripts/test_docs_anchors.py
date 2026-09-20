"""Keep ``docs/execution-plane.md``'s ``file:line`` anchors from rotting.

The doc publishes the P2b execution-plane classification as machine-readable
tables: 34 execution points, the plane's own wiring points, and three negative
claims ("this token is *not* there"). Every one of those anchors breaks the
moment the code moves -- and a broken anchor is worse than no anchor, because
the reader trusts it.

So the doc owns the table and this test asserts it against the tree. Same
direction as ``TAKEOVER_HAZARDS``: an unclassified node raises rather than
falling back to a default that answers ``safe``.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "execution-plane.md"

_ANCHOR_BLOCK = re.compile(r"<!-- anchor-table:begin -->(.*?)<!-- anchor-table:end -->", re.DOTALL)
_ABSENCE_BLOCK = re.compile(
    r"<!-- anchor-absence:begin -->(.*?)<!-- anchor-absence:end -->", re.DOTALL
)
# A row looks like `| `path:line` | `token` | ...` -- only the first two cells
# carry meaning here. Header and separator rows have no backticks, so they drop.
_ROW = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|", re.MULTILINE)


def _lines(relative: str) -> list[str]:
    return (REPO / relative).read_text(encoding="utf-8", errors="replace").splitlines()


def _split(anchor: str) -> tuple[str, int | None]:
    """``path:12`` -> ``("path", 12)``; a bare ``path`` -> ``("path", None)``."""
    path, sep, tail = anchor.rpartition(":")
    if sep and tail.isdigit():
        return path, int(tail)
    return anchor, None


def _rows(block: re.Pattern[str]) -> list[tuple[str, str]]:
    """Every ``(anchor, token)`` pair inside the marked tables of that kind."""
    return _rows_in(DOC.read_text(encoding="utf-8"), block)


def _rows_in(text: str, block: re.Pattern[str]) -> list[tuple[str, str]]:
    """``_rows`` over an arbitrary document, so the check below can be trained."""
    rows: list[tuple[str, str]] = []
    for table in block.findall(text):
        rows.extend(_ROW.findall(table))
    return rows


def _unpinned_absence_rows(text: str) -> list[str]:
    """Absence rows whose line no presence row pins -- i.e. rows whose rot is silent.

    ``test_every_published_absence_is_still_absent`` asks ``token not in line``.  A
    shifted line holds something unrelated, and something unrelated does not
    contain the token -- so the row keeps passing while pointing at a line nobody
    chose.  The presence table has no such mode: its rows go red on the same shift.
    Requiring the two tables to share the line is what transfers that loudness.
    """
    pinned = {
        (path, line)
        for anchor, _token in _rows_in(text, _ANCHOR_BLOCK)
        for path, line in [_split(anchor)]
        if line is not None
    }
    return [
        anchor
        for anchor, _token in _rows_in(text, _ABSENCE_BLOCK)
        for path, line in [_split(anchor)]
        if line is not None and (path, line) not in pinned
    ]


def test_the_doc_is_here_and_its_marker_pairs_are_balanced():
    """A lost ``:end`` marker would silently hide rows from both checks below."""
    text = DOC.read_text(encoding="utf-8")
    for marker in ("anchor-table", "anchor-absence"):
        begins = text.count(f"<!-- {marker}:begin -->")
        ends = text.count(f"<!-- {marker}:end -->")
        assert begins == ends, f"{marker}: {begins} begin marker(s) vs {ends} end marker(s)"
        assert begins > 0, f"{marker}: no marked table found -- the checks below would be vacuous"


def test_every_published_anchor_still_points_at_its_token():
    rows = _rows(_ANCHOR_BLOCK)
    # The floor is the count the doc actually publishes (34 execution points +
    # 9 wiring points). Adding a row keeps this green; *losing* one trips it --
    # which is the failure a per-row check cannot see, because the lost row is
    # simply not there to be checked.
    assert len(rows) >= 43, f"the classification tables lost rows: {len(rows)}"

    complaints: list[str] = []
    for anchor, token in rows:
        path, line = _split(anchor)
        assert line is not None, f"anchor without a line number: {anchor}"
        if not (REPO / path).is_file():
            complaints.append(f"{anchor}: no such file")
            continue
        lines = _lines(path)
        if not 0 < line <= len(lines):
            complaints.append(f"{anchor}: out of range, the file has {len(lines)} lines")
            continue
        if token not in lines[line - 1]:
            complaints.append(f"{anchor}: want {token!r}, got {lines[line - 1].strip()!r}")

    detail = "\n  ".join(complaints)
    assert not complaints, f"docs/execution-plane.md anchors are stale:\n  {detail}"


def test_every_published_absence_is_still_absent():
    rows = _rows(_ABSENCE_BLOCK)
    # Same discipline as the anchor table above: the floor is the count the doc
    # actually publishes.  It was 3 until P2c-S4, which spread the ``start_lease``
    # absence over the six api-layer files -- a floor left behind at 3 would have
    # let any of the five new rows be dropped without a word.  (Found by mutation:
    # deleting one of them survived.)
    assert len(rows) >= 8, f"the absence table lost rows: {len(rows)}"

    complaints: list[str] = []
    for anchor, token in rows:
        path, line = _split(anchor)
        if not (REPO / path).is_file():
            complaints.append(f"{anchor}: no such file")
            continue
        if line is None:
            if token in "\n".join(_lines(path)):
                complaints.append(f"{path}: {token!r} is now present")
        elif token in _lines(path)[line - 1]:
            complaints.append(f"{anchor}: {token!r} is now present")

    detail = "\n  ".join(complaints)
    assert not complaints, f"docs/execution-plane.md absences no longer hold:\n  {detail}"


def test_a_line_level_absence_row_rots_loudly_because_a_presence_row_shares_it():
    """The absence table's silent-rot mode, closed by sharing the line.

    Adding the word 槽 to a sentence in §7.1 shifted ``_wf_actions.py:252`` to
    ``:268`` -- and the absence row there kept passing, because line 252 now holds
    an unrelated statement that also does not contain ``_background_tasks``.  A
    presence row shifted in the same edit and *did* go red, which is the asymmetry
    this pins: any absence row with a line has to point at a line the presence
    table pins too, so the loud failure can stand in for the quiet one.
    """
    assert not _unpinned_absence_rows(DOC.read_text(encoding="utf-8")), (
        "these absence rows point at a line no presence row pins, so their rot is "
        f"silent -- point them at an anchored line: "
        f"{_unpinned_absence_rows(DOC.read_text(encoding='utf-8'))}"
    )

    # Positive control: the doc as it stood before this slice -- the presence row
    # at :268 and the absence row still at :252 -- must be reported, otherwise the
    # check above would also pass on a scan that never ran.
    stale = (
        "<!-- anchor-table:begin -->\n"
        "| `backend/api/routes/_wf_actions.py:268` | `asyncio.create_task` | why |\n"
        "<!-- anchor-table:end -->\n"
        "<!-- anchor-absence:begin -->\n"
        "| `backend/api/routes/_wf_actions.py:252` | `_background_tasks` | why |\n"
        "<!-- anchor-absence:end -->\n"
    )
    assert _unpinned_absence_rows(stale) == ["backend/api/routes/_wf_actions.py:252"]

    # And a file-level row has no line to pin, so it is not asked for one.
    file_level = (
        "<!-- anchor-absence:begin -->\n"
        "| `backend/api/routes/workflow.py` | `start_lease` | why |\n"
        "<!-- anchor-absence:end -->\n"
    )
    assert _unpinned_absence_rows(file_level) == []
