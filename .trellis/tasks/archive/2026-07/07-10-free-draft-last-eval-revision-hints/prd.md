# free draft last_evaluation revision_hints

## Goal

`last_evaluation` on the draft record (added #216) stores only `{overall_score, decision}` — the `revision_hints` from the evaluation are NOT persisted. The full `evaluation_result` (incl. hints) is returned to the agent and shown once in the TUI (multi-line, #215), but if the user doesn't act immediately or revisits the draft via `/draft <id>`, the hints are gone — only the score+decision remain. Add `revision_hints` to the persisted `last_evaluation` so the user can review past revision advice when viewing a draft.

## What I already know

- `backend/api/routes/free.py:215` — `draft["last_evaluation"] = {"overall_score": ..., "decision": ...}`. Only the summary pair is written back. Comment (line 212) says "only the {overall_score, decision} pair is written back".
- `evaluation_result` (from `EvaluatorAgent`, `backend/agents/evaluator.py:266`) = `{overall_score, decision, revision_hints, bias_warning, dimensions, summary}`. `revision_hints` is a `list[str]` (line 270; `_compute_decision` returns `(decision, hints)`).
- `list_drafts` (free.py:297-305) returns `last_evaluation` as-is (the stored dict). TUI `/drafts` badges (handleDrafts) show overall_score+decision only — hints not shown in the list (correct, too verbose for a list line).
- TUI `/draft <id>` (handleDraft, #218) renders the draft record — it shows last_evaluation if present. With hints added, handleDraft should render the hints too (currently it shows the eval summary; need to check if it renders hints or just score/decision).
- #216 spec note (free-creation.md ~182) says last_evaluation = `{overall_score, decision} | None`, "Only the summary pair is persisted". This task changes that to include revision_hints — spec note must update.

## Open Questions (resolved)

- **Scope**: Add `revision_hints` (list[str]) to the persisted `last_evaluation`. evaluate_draft writes it. list_drafts returns it (already returns last_evaluation as-is). TUI `/draft <id>` renders the hints below the eval score/decision. `/drafts` list badges unchanged (hints too verbose for a list line).
- **Empty hints**: when decision=approved, revision_hints is often `[]`. Store `[]` (or the actual value) — don't special-case. handleDraft renders hints only if non-empty.
- **Backward compat**: existing drafts have last_evaluation without revision_hints — handleDraft must degrade (hints absent → don't render). No migration.

## Requirements

- `evaluate_draft` writes `last_evaluation = {overall_score, decision, revision_hints}` (revision_hints = evaluation.get("revision_hints") or []).
- `list_drafts` already returns last_evaluation as-is — no change needed (but verify).
- TUI `/draft <id>` (handleDraft): if `last_evaluation.revision_hints` is a non-empty array, render each hint as a line (dim/bulleted) under the eval score/decision.
- Graceful: drafts with old last_evaluation (no revision_hints key) → no hints rendered.
- Spec: update free-creation.md last_evaluation field description to include revision_hints.

## Acceptance Criteria

- [ ] After `xhs_free_evaluate`, the draft's `last_evaluation` includes `revision_hints`.
- [ ] `/draft <id>` shows the revision hints (if non-empty) below the eval score/decision.
- [ ] Approved drafts (empty hints) show no hints section.
- [ ] Old drafts (last_evaluation without revision_hints) don't crash — no hints rendered.
- [ ] `pytest tests/unit/api/test_free_routes.py` passes (+ updated test asserting hints persisted); `ruff` + `mypy backend` clean; `vue-tsc` clean; CI green.

## Definition of Done

- Tests pass; ruff + mypy clean; vue-tsc clean; CI green.
- Spec note updated in `.trellis/spec/backend/free-creation.md` (last_evaluation includes revision_hints).

## Out of Scope

- Storing full evaluation history (multiple past evals) — still only last_evaluation (latest).
- Showing hints in the `/drafts` list (too verbose).
- bias_warning persistence (separate concern).

## Technical Notes

- Backend: `backend/api/routes/free.py:215` — add `"revision_hints": evaluation.get("revision_hints") or []` to the dict.
- Frontend: `frontend/src/views/AgentTUI.vue` `handleDraft` — find where it renders last_evaluation (the status section); add hints rendering if `last_evaluation.revision_hints?.length`. i18n key for the hints label (both locales).
- Tests: `tests/unit/api/test_free_routes.py` — the existing evaluate-write-back test asserts `{overall_score, decision}`; update to also assert `revision_hints`.
- Conflict safety: edits evaluate_draft body (free.py:215) + handleDraft status section (AgentTUI.vue) — #220 (showHelp) doesn't touch these regions; #221 (spec) touches the same spec file but different line (Signatures table vs metadata section) — rebase-safe.
