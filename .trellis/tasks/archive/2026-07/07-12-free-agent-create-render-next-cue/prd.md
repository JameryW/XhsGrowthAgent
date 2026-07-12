# Free agent: create render next-step cue

## Problem

`omp_bridge._execute_xhs_host_tool` renders `xhs_free_draft_create` results
(~line 1313) as `Free Draft Created — draft_id: <id>` + `Title: <title>` —
but NO next-step cue. Every other free-mode render carries a `next:`/`note:`
cue pointing the agent at the next step:
- evaluate → revise/re-run cue (#234)
- publish → analytics/mock/failed-recovery cue (#235/#239)
- draft list → badge-driven next-step cues (#236)
- analytics → (terminal)

The create render is the **first step** — the entry point that yields the
`draft_id` the whole chain depends on. It's the step where the agent most
needs a "now evaluate this" cue (the draft_id is freshly in hand, and evaluate
requires it). Instead it's the only render without one.

The create tool's `description` field does carry step numbering ("Step 1 of 3
(create) ... feed draft_id to xhs_free_evaluate (step 2)") per #234's
convention — but the rendered *output* the agent reads back doesn't reinforce
it. A weaker agent that skimmed the tool description may create a draft and
then stall, not realizing evaluate is the immediate next step. The other
renders reinforce their cues in the output; create doesn't, breaking the
symmetry that makes the chain self-describing from renders alone.

## Fix

In the `xhs_free_draft_create` render, when a `draft_id` is returned (success),
append a `next:` cue pointing at `xhs_free_evaluate(<draft_id>)` — run the
quality gate before publish. Mirrors the evaluate/publish render cue pattern
(#234/#235). No cue on a create failure (draft_id absent).

No backend route change (`create_draft` already returns draft_id). No frontend
change (create goes via the agent). No i18n (omp renders are hardcoded English).

## Scope

- `backend/services/omp_bridge.py` — `xhs_free_draft_create` render: append
  `next: call xhs_free_evaluate(<draft_id>) for a quality check before publish`
  when draft_id present (~3 lines).
- `.trellis/spec/backend/free-creation.md` — note the create render carries the
  create→evaluate next-step cue (aligns with #234/#235 render-cue pattern).
- `tests/unit/services/test_omp_bridge.py` — assert the create render contains
  the evaluate next-step cue + draft_id.

## Verification

- `ruff check .` + `ruff format --check .` clean.
- `mypy backend` clean.
- full `pytest`.

## Non-goals (YAGNI)

- No cue for a failed create (draft_id absent → no chain to continue).
- No frontend/TUI change — create is agent-driven; the TUI create flow isn't a
  slash command (creation is via the agent conversation).
