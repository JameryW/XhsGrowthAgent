# Track LLM cost of tool-path enrich_with_llm calls

## Goal

LLM calls made **inside tools** (via `backend/services/llm_enrichment.py` →
`enrich_with_llm` → `model.ainvoke`) produce real token cost but are **invisible
to the cost dashboard**. The cost reader (`backend/api/routes/analytics.py`)
aggregates `kind:"llm"` entries from `state.performance_log`. `BaseAgent._llm_ainvoke`
emits those entries (PR #417/#472), but tool-path calls bypass `_llm_ainvoke` —
they go through `enrich_with_llm`, which discards `response.usage_metadata`.

The one production workflow path affected: `copywriter` → `de_ai_taste.polish_copy`
→ `enrich_with_llm` (POLISH → deepseek-v4-flash). Every polish call costs tokens
the dashboard never sees. (The other 4 `enrich_with_llm` callers —
title_generator, hashtag_researcher, image_prompt, calendar — are omp-only/manual
tools, not imported by workflow agents; fixing the shared service covers them
too at no extra cost.)

## What I already know

- `llm_perf_entry(agent, response, model, *, started_at, completed_at)` in
  `backend/agents/nodes/_base.py` is **standalone** (not bound to BaseAgent) —
  builds the `kind:"llm"` cost entry from `response.usage_metadata` + cost table.
- `BaseAgent.__call__` merges `self._llm_perf_entries` into `performance_log`
  (state) — that's the only path entries reach the cost reader.
- `enrich_with_llm` returns only the parsed result dict; throws away `response`
  (and its `usage_metadata`). 5 callers, all consume the dict.
- Tool runs inside the agent's `execute()` → same asyncio task → a `ContextVar`
  set in `__call__` before `execute()` is visible inside `enrich_with_llm`.
- Cost reader: `analytics.py:991+` filters `kind=="llm"`, sums `cost_usd`,
  buckets by period/today on `entry["timestamp"]`.
- No existing `ContextVar` use in `backend/agents/`.

## Recommended approach (ContextVar accumulator)

**Approach A: ContextVar** (Recommended — ponytail: no signature changes)

1. New module-level `ContextVar[list[dict]]` in `llm_enrichment.py` (or
   `agents/nodes/_base.py`), e.g. `_tool_llm_cost: ContextVar[list[dict] | None]`.
2. `enrich_with_llm`: after `model.ainvoke`, build entry via `llm_perf_entry`
   (agent name = task_type.value or a "tool:<task>" tag), append to the
   ContextVar if it is set. Best-effort (never break the call — existing
   try/except already wraps).
3. `BaseAgent.__call__`: `token = _tool_llm_cost.set([])` before `execute()`;
   after, read `entries = _tool_llm_cost.get()`, reset via
   `_tool_llm_cost.reset(token)`, extend `self._llm_perf_entries` with them.
   The existing merge path then carries them into `performance_log`.

- Pros: zero changes to the 5 tool callers or `enrich_with_llm`'s return
  signature. Covers all callers (workflow + omp). Mechanism is local + tiny.
- Cons: new shared mechanism (ContextVar) — mild hidden coupling between
  service and BaseAgent. Must reset per-execute to avoid stale cross-request
  leakage (the set/reset token handles this).

**Approach B: return (result, entries) tuple** — changes `enrich_with_llm`
return type + all 5 callers + each tool's return path into the agent. More
invasive, more diff. Rejected unless ContextVar proves unworkable.

## Open Questions

- Agent name tag for the entry: `task_type.value` (e.g. "polish") vs
  `f"tool:{task_type.value}"` vs the calling agent's name? The cost reader
  groups by `model`, not `agent`, so agent name is for human readability only.
  Recommend `f"tool:{task_type.value}"` to distinguish tool-path from
  agent-direct calls in the perf log. (Preference, not blocking.)

## Requirements

- `enrich_with_llm` captures token usage + cost via `llm_perf_entry` and makes
  the entry available to the calling agent's `performance_log`.
- No change to `enrich_with_llm`'s public return signature (Approach A).
- Captured entries land in `state.performance_log` with `kind:"llm"`,
  readable by the existing cost dashboard (`/analytics/costs`).
- Best-effort: capture failure never breaks the LLM call (matching existing
  `_llm_ainvoke` semantics).
- No stale entry leakage across requests/excutes (ContextVar set/reset token).

## Acceptance Criteria

- [ ] Unit test: `enrich_with_llm` called inside a `BaseAgent.__call__`-style
      ContextVar scope → a `kind:"llm"` entry with `cost_usd` appears in the
      accumulated list (mock model returning `usage_metadata`).
- [ ] Unit test: entry absent when ContextVar not set (omp/standalone path —
      no crash, no entry, call still succeeds).
- [ ] Unit test: no leakage across two executes (set/reset token).
- [ ] `ruff format --check` + `ruff check .` clean
- [ ] `mypy backend` clean
- [ ] full `pytest` green (pre-push triple gate)

## Definition of Done

- Tests added
- Lint / typecheck / CI green
- PR off `origin/main`, separate branch

## Out of Scope

- Migrating the 4 omp-only tools' callers — they're covered for free by fixing
  the shared service; no per-tool work.
- `blogger_gate` / `workflow.py:2285` direct `model.ainvoke` (not via
  `enrich_with_llm`) — separate bare-node cost-tracking gap (noted in
  [[blogger-gate-mock-gen-lighter-model]] memory); different mechanism needed.
- Ripple sim cost (separate).

## Technical Notes

- Files: `backend/services/llm_enrichment.py` (capture), `backend/agents/base.py`
  (`__call__` set/reset/merge), `backend/agents/nodes/_base.py` (ContextVar
  home + `llm_perf_entry` reuse).
- `cap_context` already wraps messages in `enrich_with_llm` — capture goes
  after `response = await model.ainvoke(messages)`, before parse.
- Precedent: PR #417 (llm_perf_entry + _llm_ainvoke), #472 (remaining agents).

## Decision (ADR-lite)

**Context**: tool-path LLM calls invisible to cost dashboard.
**Decision**: ContextVar accumulator; enrich_with_llm captures, BaseAgent.__call__
drains. No signature changes.
**Consequences**: shared ContextVar coupling between service + BaseAgent; bounded
by set/reset per execute. Covers all enrich_with_llm callers (workflow + omp).
