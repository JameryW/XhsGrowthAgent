# Showcase summary LLM call downgrade WRITING→POLISH (public_showcase:906)

## Goal

`backend/api/routes/public_showcase.py:906` generates a ONE 40-80 char Chinese
summary sentence from already-published note data (`_SUMMARY_PROMPT`, line 836)
on the **public showcase list read path** — but routes it via
`TaskType.WRITING` → `astron-code-latest` (the expensive Xunfei model,
$0.0006/1K out, 90s timeout). This is a narrow paraphrase-of-existing-content
task identical in nature to POLISH (de_ai_taste). It runs ×4 concurrently
during lazy backfill (`_SUMMARY_BACKFILL_CONCURRENCY = 4`, line 849).

Downgrade to `TaskType.POLISH` → `deepseek-v4-flash` ($0.00028/1K out, 60s).
Same "窄转换 → deepseek" rationale as #467/#470/#490. ~½ the cost, faster,
on a public read path.

## What I already know

- Site: `public_showcase.py:905-910` — `get_llm_service().enrich_with_llm(task_type=TaskType.WRITING, ...)`. The `TaskType` import is local (line 902), `WRITING` the only use at this site.
- `models.py:110` `TaskType.WRITING: "astron-code-latest"`; `:125`
  `TaskType.POLISH: "deepseek-v4-flash"`. Cost: astron $0.0006/1K out vs
  deepseek $0.00028/1K out (`models.py:146`). POLISH comment (:124):
  "去套话润色是窄转换，用 deepseek-v4-flash（更轻/便宜）" — exactly this task's shape.
- `_SUMMARY_PROMPT` (line 836) asks for ONE 40-80 char sentence — narrow
  conversion, not draft generation. WRITING→astron is for草稿生成 (drafts).
- Precedent PRs (all narrow/fabrication tasks astron→deepseek):
  - #467 POLISH (de_ai_taste)
  - #470 VIRAL_MATCHING (viral_matcher)
  - #490 MOCK_GEN (blogger_gate mock-note-gen)
- Runs on public read path ×4 concurrent during backfill (line 849).
  `_fallback` (line 912) catches LLM failure → still returns summary. Safe
  downgrade — failure path unchanged.
- Tests (`tests/unit/api/test_public_showcase.py:679-733`) mock
  `enrich_with_llm` and assert `assert_awaited_once()` / `assert_not_called()`
  — do NOT pin `task_type`. Safe.
- No conflict with #499 (open, GHA-outage-blocked): #499 touches
  `content_strategist.py` + `settings.py` RippleSettings; this touches
  `public_showcase.py` only. Branch off `origin/main`.
- Investigator bonus gap (NOT this PR): this route LLM call's cost is invisible
  to the cost dashboard (no `_tool_llm_cost` ContextVar set — only
  `BaseAgent.__call__` does, per #491). The downgrade reduces invisible cost;
  full visibility needs a ContextVar wrapper (mirrors #493, ~bigger). Later.

## Recommended approach (ponytail)

One-line change:

```python
# public_showcase.py:906:
# before:
task_type=TaskType.WRITING,
# after:
task_type=TaskType.POLISH,
```

`TaskType` already imported at line 902 (local import inside the function).
No new import. `_fallback` path (line 911-912) unchanged. ~1 LOC.

- Pros: ~½ cost + faster on a public read path ×4 concurrent; exact #467/#470
  precedent; zero behavior change (same prompt, same fallback, same output
  shape). No test breakage.
- Cons: none. deepseek-v4-flash is prod-verified (PR#471 confirmed real callable).

**Rejected: also add cost-visibility ContextVar.** Out of scope — that's a
~20+ LOC wrapper mirroring #493, different concern (visibility vs routing).
Keep this PR to the 1-LOC routing downgrade. Note for later.

## Requirements

- `public_showcase.py:906` uses `TaskType.POLISH` instead of `TaskType.WRITING`.
- No other change to the call (prompt, fallback, output handling unchanged).

## Acceptance Criteria

- [ ] `public_showcase.py:906` is `task_type=TaskType.POLISH,`.
- [ ] `tests/unit/api/test_public_showcase.py` (the 6 enrich_with_llm tests)
      still pass — no `task_type` pinning to break.
- [ ] New test: assert the showcase summary route passes `TaskType.POLISH` to
      `enrich_with_llm` (pin the task_type so a revert to WRITING fails —
      non-vacuous). The existing tests assert await-count but not task_type;
      add the assertion to one existing test or a new focused test.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- public_showcase.py 1-line change
- 1 non-vacuous test pinning task_type=POLISH
- Pre-push triple green
- PR off `origin/main`, separate branch (no #499 conflict)

## Out of Scope

- Cost-visibility ContextVar for this route (separate PR, mirrors #493).
- Tuning `_SUMMARY_PROMPT` or backfill concurrency.
- Other WRITING→POLISH candidates (orphan tools have zero prod callers —
  investigator confirmed no measurable benefit; CLAUDE.md flags as placeholders).
- ripple_gate.py hardcoded thresholds (conflicts with #499's RippleSettings
  touch — defer until #499 merges).

## Technical Notes

- File: `backend/api/routes/public_showcase.py` (line 906) + test.
- Precedent: #467 (POLISH de_ai_taste), #470 (VIRAL_MATCHING), #490 (MOCK_GEN).
  Memory: `polish-lighter-model-deepseek.md`, `viral-matcher-lighter-model.md`,
  `blogger-gate-mock-gen-lighter-model.md`, `deepseek-v4-flash-global-rename.md`.
- Cost context: astron $0.0006/1K out vs deepseek $0.00028/1K out (`models.py:146-149`).
- #499 non-conflict: different file, #499 = content_strategist.py + settings.py.

## Decision (ADR-lite)

**Context**: public_showcase summary LLM call routes a narrow 1-sentence
paraphrase through the expensive WRITING→astron model on a public read path
×4 concurrent. Same narrow-conversion shape POLISH was created for.
**Decision**: downgrade task_type WRITING→POLISH (→deepseek-v4-flash). 1 LOC.
**Consequences**: ~½ cost + faster on public read path. Exact #467/#470
precedent. Fallback path unchanged. No test breakage. Cost still invisible
to dashboard (separate ContextVar PR later).
