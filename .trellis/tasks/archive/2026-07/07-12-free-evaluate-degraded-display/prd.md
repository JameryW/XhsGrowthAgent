# Free evaluate: surface degraded/failed evaluation (cross-stack)

## Problem

When the RQGM evaluator **degrades** (LLM timeout / parse failure), it returns a
fallback verdict: `overall_score=100.0, decision=APPROVED, revision_hints=[],
summary="评估器 LLM 超时，降级放行: ..."` (`backend/agents/evaluator.py`
`execute` timeout branch). The free-mode `evaluate_draft` route persists only
the `{overall_score, decision, revision_hints}` triple as `last_evaluation` —
the `summary` (which carries the degradation cause) is dropped.

So a degraded evaluation looks like a **perfect approved evaluation**:
- `/draft <id>` shows `Evaluation: 100.0 (approved)` — indistinguishable from a
  real perfect-score approval.
- `/drafts` shows the `[100 approved]` badge.
- The agent-side list (#236) shows `[100 approved]`.
- The agent-side evaluate render (#234) shows `Overall: 100 Decision: approved`.

The user/agent has no signal the evaluation actually **failed and fell back** —
they may publish a "100-approved" draft that was never really evaluated. The
degradation cause (timeout) is lost entirely (not persisted).

This is the evaluate-side mirror of the publish failure story (#239/#240/#241):
publish failure is now surfaced end-to-end, but evaluator degradation is silent.

## Fix

Persist the degradation signal + surface it on both surfaces.

### Backend — `backend/api/routes/free.py` `evaluate_draft`

Persist `summary` (the degradation cause) onto `last_evaluation` so the cause
survives the turn:

```python
draft["last_evaluation"] = {
    "overall_score": evaluation.get("overall_score"),
    "decision": evaluation.get("decision"),
    "revision_hints": evaluation.get("revision_hints") or [],
    "summary": evaluation.get("summary"),   # carries degradation cause when present
}
```

Detect degradation: the evaluator's fallback verdict carries a non-empty
`summary` mentioning "降级" / "degraded" / timeout. A real evaluation's
`summary` is either empty or a genuine quality summary — but to be robust,
gate the degraded display on a heuristic: `summary` present AND `decision ==
approved` AND `overall_score >= 100` is NOT reliable (a real eval could score
100). Instead, rely on the evaluator emitting a stable marker.

**Decision:** add a `degraded: bool` flag to the evaluator's fallback verdict
(the timeout branch already returns a fixed dict — add `"degraded": True`).
Real evaluations omit it (→ falsy). This is the clean, non-heuristic signal.
Then:
- `evaluate_draft` persists `degraded` onto `last_evaluation`.
- `_draft_matches_status` stays as-is (no `degraded` filter — YAGNI; the badge
  is enough, and degraded is rare).

### Backend — `backend/agents/evaluator.py`

Add `"degraded": True` to the timeout-fallback verdict dict (1 line). Real
verdicts (the `_build_evaluation_result` path) don't set it → absent/falsy.

### Frontend — `frontend/src/views/AgentTUI.vue`

- `/draft <id>` detail: when `last_evaluation.degraded` is truthy, render the
  eval line with a dim/yellow `⚠ degraded` marker + the `summary` (cause) on a
  following dim line, instead of presenting the fake "100 approved" as gospel.
- `/drafts` list badge: a degraded eval shows `[degraded]` instead of
  `[100 approved]` (the score is meaningless when degraded).

### Agent-side — `backend/services/omp_bridge.py`

- `xhs_free_evaluate` render: when `evaluation_result.degraded` is truthy,
  prepend a `⚠ Evaluation degraded (LLM timeout/failure) — verdict is a
  pass-through fallback, not a real score.` line so the agent knows not to
  trust the 100/approved.
- `xhs_free_draft_list` render: degraded draft shows `[degraded]` badge instead
  of `[score decision]`.

### Spec — `.trellis/spec/backend/free-creation.md`

- `last_evaluation` metadata: add `summary?` + `degraded?` fields.
- Agent-side evaluate render: note the degraded marker.
- Agent-side list render: note the `[degraded]` badge.
- TUI `/draft <id>` + `/drafts`: note the degraded display.

## Scope

- `backend/agents/evaluator.py` — add `"degraded": True` to fallback verdict.
- `backend/api/routes/free.py` — persist `summary` + `degraded` onto
  `last_evaluation`.
- `frontend/src/views/AgentTUI.vue` — `/draft <id>` degraded marker + `/drafts`
  `[degraded]` badge.
- `frontend/src/locales/{en,zh-CN}.json` — `draftDetailEvalDegraded` +
  `draftsBadgeDegraded` keys (zh + en).
- `backend/services/omp_bridge.py` — evaluate render degraded marker + list
  `[degraded]` badge.
- `.trellis/spec/backend/free-creation.md` — metadata + render notes.
- tests: evaluator fallback asserts `degraded: True`; free route asserts
  `last_evaluation.degraded` persisted; agent evaluate render + list badge
  assert degraded marker.

## Verification

- `ruff check .` + `ruff format --check .` clean.
- `mypy backend` clean.
- full `pytest`.
- `vue-tsc --noEmit` clean.

## Non-goals (YAGNI)

- `degraded` status filter for `/drafts` — rare; the badge is enough. Add when
  a user asks.
- Retry/re-run-evaluate automatically — just surface the degradation; the user
  re-runs `/evaluate` manually.
- Persisting the full `evaluation_result` (dimensions/bias) — only the summary
  + degraded flag, mirroring the existing triple.
