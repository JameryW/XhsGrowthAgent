# PRD: fix add_session.py skips journal file on first session

## Problem
`add_session.py` appends session content only `if target_file:`. When no
`journal-*.md` exists (e.g. workspace has `index.md` but no journal file — the
real JameryW state before session 35), `get_latest_journal_info` returns
`(None, 0, 0)`, `target_file` stays `None`, and the append is skipped. The
session lands only in `index.md`; `journal-0.md` is never created.

## Fix
- In `add_session()`: when `target_file is None`, create `journal-{num}.md`
  via `create_new_journal_file` before appending.
- In `create_new_journal_file()`: `mkdir(parents=True)` the parent, and emit a
  non-continuation header for part 0 (avoid "Continuation from journal--1.md").

## Acceptance
- Case A (index present, no journal): session written to a newly created journal file.
- Case B (totally empty workspace): journal file created, session written.
- Case C (journal exists): unchanged normal-append behavior.
