# blogger_gate mock note gen use lighter MOCK_GEN model

## Goal

`blogger_gate._generate_mock_notes` generates **fictional** blogger notes (mock
data, no real XHS search) but routes the LLM call through `TaskType.SCOUTING`
(astron-code-latest, the heavy/expensive model). The sibling `blogger_scout`
agent — which does the same kind of mock generation — was already migrated to
`TaskType.MOCK_GEN` (deepseek-v4-flash, lighter/cheaper) in PR #468.
`blogger_gate` was missed. Align it: pure-fiction JSON generation does not need
the heavy model; use `MOCK_GEN` for cost + latency savings with no behavior
change (same prompt, same output schema).

## What I already know

- `backend/agents/blogger_scout.py:23` → `task_type = TaskType.MOCK_GEN` (PR #468, correct)
- `backend/agents/nodes/blogger_gate.py:152` → `get_model(TaskType.SCOUTING.value)` (missed)
- `_generate_mock_notes` is the mock path: `user_id.startswith("mock_")` OR
  always-falls-through (line ~107: both branches call `_generate_mock_notes`).
  Pure LLM fiction, no tools, no real search — exactly the MOCK_GEN use case.
- Model routing (config/models.py): `SCOUTING → astron-code-latest`,
  `MOCK_GEN → deepseek-v4-flash`.
- Precedent: PR #467 (de_ai_taste→POLISH), #468 (blogger_scout→MOCK_GEN),
  #470 (viral_matcher→VIRAL_MATCHING) — all "pure-fiction/transform → lighter
  model" migrations off main, one PR each.
- `TaskType` already imported in blogger_gate.py. Fix is one token: `SCOUTING` → `MOCK_GEN`.

## Requirements

- Change `blogger_gate.py:152` from `TaskType.SCOUTING` to `TaskType.MOCK_GEN`.
- No other behavior change (prompt, parsing, output schema untouched).

## Acceptance Criteria

- [ ] `blogger_gate._generate_mock_notes` routes via `TaskType.MOCK_GEN`
- [ ] Unit test pins the routing (assert `get_model` called with `mock_gen`,
      mirroring how blogger_scout's routing is asserted) — guards regression
- [ ] `ruff format --check` + `ruff check .` clean
- [ ] `mypy backend` clean
- [ ] full `pytest` green (per pre-push triple gate memory)

## Definition of Done

- Tests added/updated
- Lint / typecheck / CI green
- PR off `origin/main`, separate branch (per separate-pr-per-feature memory)

## Out of Scope

- Cost/perf tracking via `_llm_ainvoke` for this node — blogger_gate is a bare
  node function, not a BaseAgent; it has no `self._llm_perf` / `_reset_llm_perf`.
  Migrating node-level LLM calls to cost tracking is a separate, larger change.
  This PR only fixes the model routing.

## Technical Notes

- Pattern identical to PR #468. Keep diff minimal (one line + test).
- Verify no other `SCOUTING` site is actually mock-gen (scanned: only
  `blogger_gate:152` is wrong; trend_scout legitimately uses SCOUTING for real
  trend analysis).

## Decision (ADR-lite)

**Context**: blogger_gate mock note gen uses heavy model for pure fiction.
**Decision**: Route via MOCK_GEN (deepseek-v4-flash), matching blogger_scout.
**Consequences**: Lower cost + latency per mock-note-gen call; output quality
unchanged (structured JSON fiction within both models' capability).
