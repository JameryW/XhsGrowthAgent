# Fix omp tool impl bugs across TS ext and Python bridge

## Problem

Audit of omp tool implementations (`backend/omp/extensions/xhsagent-ext/` TS ext +
`backend/services/omp_bridge.py` Python host-tool bridge) found implementation
logic / data-shape bugs against the backend API contract.

## Findings

### F1 — Stale evaluation dimension list in system prompts (TS ext)

`backend/omp/extensions/xhsagent-ext/src/commands/xhs.ts:14` and
`src/events.ts:28` hardcode a 6-dimension evaluation list:
"AI taste, image quality, commercial tone, compliance, reach, and audience fit".

Backend (`backend/agents/evaluator.py:34` `_DIMENSION_WEIGHTS`) defines **8 weighted
dimensions**: copywriting, visual, compliance, reach, audience, ai_taste,
image_quality, commercial_tone — plus a `bias_check` (9 total).
`evaluation_result.ts` and `xhs_evaluate.ts` already correctly list 9.

The stale prompt omits the two highest-weight core dims (copywriting 0.20,
visual 0.15), misleading the agent about what the evaluator scores.

### F2 — `workflow_list` reads `count`, backend returns `total` (TS ext)

`backend/omp/extensions/xhsagent-ext/src/tools/workflow_list.ts` types the
response as `{ workflows, count }` and renders `Workflows (${result.count})`.
Backend `GET /workflow/list` (`backend/api/routes/workflow.py:1592`) returns
`{ workflows, total, limit, offset }` — there is no `count` field. `result.count`
is always `undefined`; the `|| result.workflows.length` fallback masks it in
display, but the typed contract is wrong and the `details` payload leaks a
nonexistent key. The Python bridge (`omp_bridge.py:800`) already uses
`len(workflows)` and is correct.

### F3 — Dead `subscribeSSE` + incomplete SSE event list (TS ext)

`src/api_client.ts:115` exports `subscribeSSE`; grep shows **zero callers** in
the ext. Its `SSE_EVENT_TYPES` list omits `review.approved/rejected/needs_revision`,
`analytics.*`, `evaluator.epoch_evolved` from `backend/realtime/events.py`.
Since the function is uncalled, impact is latent — but the stale list would
silently drop events if ever wired up (per prior SSE-name-mismatch lesson).

## Scope (MVP)

- F1: fix `xhs.ts:14` + `events.ts:28` to list all 8 weighted dims + bias_check
  (match `xhs_evaluate.ts` / `evaluation_result.ts` wording).
- F2: fix `workflow_list.ts` — rename `count`→`total` in type + render; expose
  `account_id`/`status`/`limit`/`offset` filter params backend already supports.
- F3: delete dead `subscribeSSE` + `SSE_EVENT_TYPES` from `api_client.ts`; drop
  the unused `SSEEvent` type if no longer referenced. (Deletion > dead code.)

Out of scope: bridge missing 4 eval sub-tools (epochs/weights/samples/trend) —
intentional subset, not a bug. CLAUDE.md "6 dimensions" doc drift noted
separately (doc, not code).

## Acceptance

- `npm run typecheck` clean in `backend/omp/extensions/xhsagent-ext`.
- `pytest tests/unit/services/test_omp_bridge.py` green (31 tests).
- `pytest` full suite green (no regressions from bridge touch).
- `ruff check .` + `mypy backend` clean.
