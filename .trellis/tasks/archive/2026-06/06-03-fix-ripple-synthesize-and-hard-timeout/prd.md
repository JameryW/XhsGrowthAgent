# Fix: Ripple SYNTHESIZE Limits + Hard Timeout + Structured JSON

## Goal

Implement the 3 remaining Ripple service-side fixes to prevent simulations from hanging indefinitely (SYNTHESIZE bottleneck) and crashing on malformed JSON — so that jobs complete within bounded time and produce valid results.

## What I already know

* **SYNTHESIZE is the main bottleneck**: 3 running jobs are stuck at SYNTHESIZE phase. No per-phase timeout, no prompt truncation, no max_tokens override.
* **No hard timeout at any level**: `SimulationRuntime.run()` has no `asyncio.wait_for()` wrapper. `JobManager._execute()` doesn't wrap simulation in timeout. Only per-LLM-call timeout exists (httpx adapter, default 120s).
* **Fragile JSON parsing**: `OmniscientAgent._parse_json()` is simple markdown-fence stripping + `json.loads()`. The robust `parse_json_from_llm()` exists but isn't used in production.
* **No structured output enforcement**: No `response_format`, `json_schema`, or structured output mode. JSON compliance relies on prompt instructions + retry.
* **SYNTHESIZE prompt is unbounded**: `snapshot_json`, `obs_json`, `input_json` serialized with `indent=2`, no size cap. High-wave simulations can exceed context windows.
* **SYNTHESIZE max_tokens = 4096** (same as all phases). For complex outputs, may produce truncated JSON.
* Config resolution: role-level code > global code > role-level file > global file. Per-role `max_tokens` and `timeout` are supported in `ModelEndpointConfig`.
* Phase sequence: INIT → SEED → RIPPLE → (DELIBERATE) → OBSERVE → SYNTHESIZE
* Ripple repo: `/tmp/ripple-repo`, fork at `https://github.com/JameryW/Ripple`

## Assumptions (temporary)

* Per-phase timeout is new pattern in Ripple — no existing `asyncio.wait_for()` usage in engine/agents
* Structured JSON output requires changes to all 4 LLM adapters (chat_completions, responses, anthropic, bedrock)
* Prompt truncation needs careful design — truncating observation data could lose critical signals

## Open Questions

* None blocking — requirements are clear from previous task analysis

## Requirements

### Fix #1: Per-phase and per-job hard timeout

- Add configurable per-phase timeout defaults to `SimulationRuntime`:
  - INIT: 60s, SEED: 30s, RIPPLE: 1200s (20min), DELIBERATE: 600s (10min), OBSERVE: 120s, SYNTHESIZE: 180s
  - Overall job timeout: 1800s (30min)
- Wrap each phase execution in `asyncio.wait_for()` with phase-specific timeout
- Wrap entire `SimulationRuntime.run()` in overall job timeout
- When timeout expires, mark job as `timed_out` (not `failed` or leave as `running`)
- Add `PHASE_TIMEOUTS` and `JOB_TIMEOUT` to runtime config/env vars

### Fix #1b: Per-LLM-call timeout tracking

- Add per-call timeout tracking in LLM adapters — log elapsed time per call and warn if approaching phase timeout budget
- Add `call_timeout` override parameter to `_call_llm()` in OmniscientAgent, StarAgent, SeaAgent
- When a single LLM call exceeds its allocated timeout, cancel the httpx request and raise `TimeoutError` (not wait for adapter default)
- Track cumulative LLM call time per phase; if cumulative time exceeds phase timeout budget, stop retrying

### Fix #2: SYNTHESIZE limits (prompt size, max_tokens, timeout)

- Add `_truncate_json(data, max_chars)` helper to truncate large JSON blobs before injecting into prompts
- Default limits: snapshot_json ≤ 20000 chars, obs_json ≤ 15000 chars, input_json ≤ 5000 chars
- Override `max_tokens` for SYNTHESIZE phase to 8192 (from default 4096)
- Override `timeout` for SYNTHESIZE LLM call to 180s
- Add `SYNTHESIZE_MAX_CHARS_*` config constants (env-var configurable)

### Fix #3: Structured JSON output + robust parsing

- Switch `OmniscientAgent._parse_json()` to use `ripple.utils.json_parser.parse_json_from_llm()` instead of simple `json.loads()`
- Add `json_mode: bool` field to `ModelEndpointConfig` (default False)
- When `json_mode=True`:
  - `ChatCompletionsAdapter`: add `response_format={"type": "json_object"}`
  - `AnthropicAdapter`: add prefill `\n{` to force JSON start
  - `ResponsesAdapter`: add `response_format={"type": "json_object"}` (if supported)
- Enable `json_mode=True` for ALL 4 agents in default config: omniscient, star, sea, tribunal
- Keep retry loop for backward compatibility
- Apply `parse_json_from_llm()` across all agents (not just Omniscient)

## Acceptance Criteria

- [ ] Per-phase timeout enforced: each phase has configurable timeout, simulation fails gracefully on timeout
- [ ] Overall job timeout enforced: jobs that exceed 30min are marked `timed_out`
- [ ] SYNTHESIZE prompt size is truncated: large JSON blobs capped before injection
- [ ] SYNTHESIZE max_tokens override: 8192 for synthesis, 4096 for other phases
- [ ] Per-LLM-call timeout tracking: cumulative time tracked per phase, warnings when approaching budget
- [ ] Robust JSON parser used: `parse_json_from_llm()` replaces `_parse_json()` across all agents
- [ ] `json_mode` config field exists and is functional for chat_completions and anthropic adapters
- [ ] `json_mode=True` enabled for omniscient, star, sea, tribunal roles in default config
- [ ] Existing tests pass; new tests for timeout, truncation, json_mode
- [ ] E2E: simulation completes within 30min or is marked timed_out

## Definition of Done

- Tests added/updated
- Lint/typecheck green
- Docs updated (config changes documented)
- Rollback: all new features have defaults matching current behavior (no timeout = old behavior if env vars unset)

## Out of Scope

- Optimizing Ripple simulation speed (separate effort)
- Changing the XHS workflow graph topology
- Bedrock adapter json_mode (low priority, not commonly used)
- Migrating all agents to structured output (just omniscient for now)

## Technical Notes

### Files to modify (Ripple repo)

- `ripple/engine/runtime.py` — add per-phase and job-level timeout with `asyncio.wait_for()`
- `ripple/agents/omniscient.py` — prompt truncation, max_tokens override, robust JSON parser, per-call timeout
- `ripple/agents/star.py` — robust JSON parser, json_mode integration
- `ripple/agents/sea.py` — robust JSON parser, json_mode integration
- `ripple/agents/tribunal.py` — robust JSON parser, json_mode integration (already has _safe_int_score)
- `ripple/llm/config.py` — add `json_mode` field to `ModelEndpointConfig`
- `ripple/llm/chat_completions_adapter.py` — add `response_format` when json_mode=True, per-call timeout tracking
- `ripple/llm/anthropic_adapter.py` — add prefill when json_mode=True
- `ripple/llm/responses_adapter.py` — add `response_format` when json_mode=True
- `ripple/service/job_manager.py` — add timed_out status, overall job timeout in `_execute()`
- `ripple/service/settings.py` — add JOB_TIMEOUT env var
- `llm_config.example.yaml` — add json_mode field example

### Research References
- [`research/ripple-codebase-audit.md`](research/ripple-codebase-audit.md) — Full audit of SYNTHESIZE, job lifecycle, LLM client, and configuration

## Decision (ADR-lite)

**Context**: 3 remaining fixes need architectural changes in Ripple repo (no existing timeout/prompt-size/structured-output patterns).
**Decision**: Implement all 3 fixes with backward-compatible defaults (timeout disabled if env vars unset, json_mode defaults to False, truncation defaults to reasonable caps).
**Consequences**: Adds asyncio.wait_for pattern to runtime (new), requires adapter-level json_mode support (medium complexity). All features have safe defaults matching current behavior.