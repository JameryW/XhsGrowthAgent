# Heavy residual: no auto-revise from LLM decision

## Goal

工作流评估后，quality `decision`（`needs_revision` / `rejected`）**不再自动**进 `revise_content`；修订/放行必须经现有 `POST /resume` + `human_decision=revise|approve`。放行仍只看 `publish_eligibility` + 后续 publish 人工确认。去掉修订上限 force 进 `publish_gate`。

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Residual level | **Heavy** |
| Human channel | Reuse `PAUSE_REASON_EVALUATOR_FAIL_CLOSED` + `/resume` `approve` \| `revise` |
| Cap force-publish | **Removed** — at cap still human channel, never auto `publisher` from quality reject |
| Auto `revise_content` from evaluator | **Removed** |
| Judgers / Action path | Unchanged (#717–#719) |
| RQGM panel | Kept; still writes scores/hints for UI |

## Requirements (MVP)

1. `evaluator_requires_human` / `evaluator_outcome`:
   - Degraded / decision-less → human (existing).
   - Eligibility blocking when would otherwise publish → human (existing).
   - Quality `needs_revision` / `rejected` → **human** (not `revise_content`), including under revision cap.
   - Quality approved + eligibility clear → `publisher` (→ publish_gate).
   - **No** force-publish at `max_revision_count`.
2. Evaluator node: park `PAUSED` + `PAUSE_REASON_EVALUATOR_FAIL_CLOSED` whenever `evaluator_requires_human` (including quality revise requests).
3. `/resume` path unchanged in shape: `revise` → revise loop with new budget; `approve` → continue toward publish (eligibility still enforced on next evaluator pass / gate).
4. Update tests that expected auto-revise or force-at-cap; add heavy-residual cases.
5. Update docs/spec (`compliance-baseline`, workflow/router notes, CLAUDE/router docstrings).

## Acceptance Criteria

* [ ] LLM/quality `needs_revision` does not enter `revise_content` without human `revise`
* [ ] At revision cap, quality reject does not route to `publisher`
* [ ] `/resume` approve|revise still works for parked evaluator threads
* [ ] Eligibility deny + LLM approved still fail-closed
* [ ] Unit/integration tests + CI green; specs updated

## Definition of Done

* Tests/CI green; PR; Trellis archive after merge

## Out of Scope

* Deleting RQGM panel
* Changing Action judgers / stamp loader
* Large Review UI redesign (minimal copy OK if resume prompt text needs tweak)
* New pause_reason vocabulary

## Technical Notes

* `backend/graph/routers.py` — `evaluator_requires_human`, `evaluator_outcome`
* `backend/agents/nodes/evaluator.py` — pause parking
* `backend/api/routes/_wf_runtime.py` — `_resume_past_evaluator_pause` (likely no API shape change)
* Tests: `tests/unit/graph/test_routers.py`, `tests/integration/test_evaluator_gate.py`, `tests/unit/api/test_resume_evaluator_pause.py`
* Prior light residual: #717
