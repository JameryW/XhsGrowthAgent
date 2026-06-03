# Research: Ripple Codebase Audit

- **Query**: Find exact code for SYNTHESIZE phase, job lifecycle/phase orchestration, LLM client, and configuration in the Ripple service repository at /tmp/ripple-repo
- **Scope**: Internal (ripple-repo at /tmp/ripple-repo)
- **Date**: 2026-06-03

## Findings

### 1. SYNTHESIZE Phase

#### Files Found

| File Path | Description |
|---|---|
| `ripple/agents/omniscient.py` (lines 585-675) | SYNTHESIZE phase implementation - `synthesize_result()` method and `_build_synth_prompt()` |
| `ripple/prompts.py` (lines 274-672) | All SYNTHESIZE prompt templates: RELATIVE, ANCHORED, and their v4 SYSTEM/USER splits |
| `ripple/engine/runtime.py` (lines 888-930) | Runtime orchestration calling `omniscient.synthesize_result()` at Phase 4 |

#### Code Patterns

**Method**: `OmniscientAgent.synthesize_result()` (omniscient.py:585-634)

- Takes 3 arguments: `field_snapshot`, `observation`, `simulation_input`
- Calls `_build_synth_prompt()` to build (phase_system_prompt, user_prompt) tuple
- Calls `_call_llm(user_prompt, phase="SYNTHESIZE", phase_system_prompt=phase_system)`
- Parses with `_parse_json(raw)` (json.loads after stripping markdown fences)
- Has retry loop: max 1 + self._max_retries (default max_retries=2, so 3 total attempts)
- On all retries failing, returns fallback dict: `{"prediction": {"error": str(last_error)}, "timeline": [], "bifurcation_points": [], "agent_insights": {}}`

**Prompt construction**: `_build_synth_prompt()` (omniscient.py:636-670)

- Serializes 3 dicts to JSON with `json.dumps(..., ensure_ascii=False, indent=2, default=str)`:
  - `snapshot_json` = field_snapshot
  - `obs_json` = observation
  - `input_json` = simulation_input
- Selects template based on `has_historical = bool(simulation_input.get("historical"))`:
  - If historical data present: ANCHORED templates (absolute values, anchored to baseline)
  - If no historical data: RELATIVE templates (relative percentages only)
- v4 split: system prompt = instructions/schema, user prompt = runtime data

**Prompt templates** (prompts.py):

- `OMNISCIENT_SYNTHESIZE_RELATIVE` (lines 279-329) - Legacy combined template
- `OMNISCIENT_SYNTHESIZE_ANCHORED` (lines 333-390) - Legacy combined template
- `OMNISCIENT_SYNTHESIZE_RELATIVE_SYSTEM` (lines 556-603) - v4 system prompt: instructions + JSON schema
- `OMNISCIENT_SYNTHESIZE_RELATIVE_USER` (lines 605-609) - v4 user prompt: `{snapshot_json}`, `{obs_json}`, `{input_json}`
- `OMNISCIENT_SYNTHESIZE_ANCHORED_SYSTEM` (lines 612-666) - v4 system prompt: instructions + JSON schema
- `OMNISCIENT_SYNTHESIZE_ANCHORED_USER` (lines 668-672) - v4 user prompt: `{snapshot_json}`, `{obs_json}`, `{input_json}`

**Key findings about SYNTHESIZE prompt size / truncation**:

- **NO truncation or size limit on prompts**: The `snapshot_json`, `obs_json`, and `input_json` are serialized with `indent=2` and no size cap. The field_snapshot includes full agent stats, topology, evidence_pack, and extra_phase_outputs. If a simulation runs many waves, the snapshot can be very large.
- **NO per-phase max_tokens override**: The SYNTHESIZE phase uses the same `max_tokens` configured for the `omniscient` role (default 4096 from `ModelEndpointConfig.max_tokens`).
- **NO per-phase timeout**: The SYNTHESIZE phase uses the same timeout configured for the `omniscient` role (default 120.0s from adapters).
- **JSON output expected**: The LLM is instructed to output "strict JSON" with a schema template, but there is NO `response_format` / `json_schema` / structured output enforcement at the API level. The JSON is parsed from the raw text response using `OmniscientAgent._parse_json()` (simple markdown-fence stripping + `json.loads`), NOT the more robust `ripple.utils.json_parser.parse_json_from_llm()`.

**Validation**: `_validate_synth_result()` (omniscient.py:672-675)

- Only checks `if not result` (empty dict check). No field-level validation.
- Comment: "OBSERVE / SYNTHESIZE: output fields defined by Skill prompt, engine no longer hardcodes validation."

### 2. Job Lifecycle / Phase Orchestration

#### Files Found

| File Path | Description |
|---|---|
| `ripple/engine/runtime.py` | Main simulation orchestrator - `SimulationRuntime` class, `run()` method |
| `ripple/service/job_manager.py` | Job lifecycle manager - `create_job()`, `_execute()`, status transitions |
| `ripple/service/runner.py` | Thin wrapper delegating to `simulate()` API |
| `ripple/api/simulate.py` | High-level `simulate()` function creating runtime, loading skill, creating LLM router |
| `ripple/service/app.py` | FastAPI app with job CRUD endpoints and SSE streaming |

#### Phase Sequence

The default phases are defined at runtime.py:112:

```python
_DEFAULT_PHASES = ["INIT", "SEED", "RIPPLE", "OBSERVE", "SYNTHESIZE"]
```

Skills can inject extra phases (e.g., DELIBERATE) via `extra_phases` parameter. DELIBERATE is inserted after RIPPLE (before OBSERVE).

**Phase transitions in `run()` method** (runtime.py:424-931):

1. **INIT** (line 443): Calls `omniscient.init()` (3 sub-calls for dynamics, agents, topology)
2. **SEED** (line 551): Creates seed Ripple from init result
3. **RIPPLE** (line 604): Wave loop with `omniscient.ripple_verdict()` per wave, bounded by `max_waves`
4. **OBSERVE** (line 826): Calls `omniscient.observe()`, incorporating DELIBERATE output if present
5. **SYNTHESIZE** (line 888): Calls `omniscient.synthesize_result()`

Between each pair of default phases, `_run_extra_phases_between()` executes any skill-registered extra phases.

**No per-phase or per-job timeout in the runtime**: The `SimulationRuntime.run()` method has NO timeout wrapper. Timeouts exist only at:
- LLM adapter level (per HTTP request, default 120s, configurable via `timeout` in config or `llm_timeout` parameter)
- Job manager `wait()` method (line 90): `asyncio.wait_for(self._tasks[job_id], timeout=timeout)` - but this is only called externally, not internally during execution

**Job status transitions** (job_manager.py):

- `create_job()` (line 43): creates job, status "queued" (in SQLite), then spawns `asyncio.Task`
- `_execute()` (line 68): sets status "running", then calls `_run_simulation()`
- On success: sets "completed", publishes "job.completed"
- On `CancelledError`: sets "cancelled"
- On any other `Exception`: sets "failed", stores error dict

**What happens when a phase fails or hangs**:

- **Phase failure (LLM error)**: Each Omniscient method has a retry loop (max_retries=2, so 3 total attempts). If all retries fail, a fallback/safe-degradation result is returned. For SYNTHESIZE, this returns `{"prediction": {"error": ...}}`. For RIPPLE verdict, this returns a verdict with `continue_propagation=False`.
- **Phase hang (no timeout)**: There is NO per-phase timeout or overall simulation timeout in the runtime itself. If a LLM call hangs indefinitely (beyond the adapter-level timeout), the `httpx.Timeout` will eventually kill the HTTP request. But if the adapter timeout is misconfigured or very long, the simulation can hang for a very long time.
- **Job-level timeout**: The `JobManager.wait()` method can accept a timeout, but this is external (called by the service layer). The service layer does NOT set a timeout on job execution.
- **RIPPLE loop safety**: The wave loop has `max_waves` as a hard cap (`estimated_waves * SAFETY_WAVE_MULTIPLIER` where multiplier = 3), preventing infinite wave loops even if the Omniscient always says `continue_propagation=True`.

### 3. LLM Client

#### Files Found

| File Path | Description |
|---|---|
| `ripple/llm/router.py` | `ModelRouter` class - role-based adapter selection, budget management |
| `ripple/llm/config.py` | `ModelEndpointConfig` dataclass, `LLMConfigLoader` - three-tier config resolution |
| `ripple/llm/chat_completions_adapter.py` | OpenAI Chat Completions adapter via httpx |
| `ripple/llm/responses_adapter.py` | OpenAI Responses API adapter via httpx |
| `ripple/llm/anthropic_adapter.py` | Anthropic Messages API adapter via httpx |
| `ripple/llm/bedrock_adapter.py` | AWS Bedrock adapter via boto3 |
| `ripple/utils/json_parser.py` | Robust JSON parser from LLM output (NOT used by OmniscientAgent) |

#### LLM Call Pattern

All adapters share the same interface: `async call(system_prompt: str, user_message: str) -> str`

The call flow is:
1. `simulate()` creates `ModelRouter` (simulate.py:334-340)
2. `_make_llm_caller(router, role)` wraps adapter in an async function (simulate.py:91-114)
3. `OmniscientAgent._call_llm()` calls the injected `llm_caller` (omniscient.py:95-118)
4. The `llm_caller` checks budget, gets adapter via `router.get_model_backend(role)`, calls `adapter.call()`

**LLM call signature for Omniscient**: The `_llm_caller` function (injected at OmniscientAgent construction) accepts keyword arguments: `system_prompt` and `user_prompt`. The Omniscient merges `self._system_prompt` + `phase_system_prompt` into `combined_system`, then calls `self._llm_caller(system_prompt=combined_system, user_prompt=user_prompt)`.

**Supported providers / API modes**:

- `chat_completions`: OpenAI-compatible endpoints (standard, CN-compatible, Azure)
- `responses`: OpenAI Responses API (/responses endpoint)
- `anthropic`: Anthropic Messages API (direct or via config URL)
- `bedrock`: AWS Bedrock InvokeModel (Anthropic-on-Bedrock, Amazon Titan, etc.)

**Streaming**: All adapters support streaming (SSE) by default (`stream: bool = True` in config). Streaming is explicitly described as reducing timeout risk for long responses. The `ModelRouter` accepts a `stream` override and `timeout_override` parameter.

**response_format / json_schema / structured output**: NOT used anywhere. All LLM calls request plain text output. JSON is extracted from the raw text response by:
- `OmniscientAgent._parse_json()` (omniscient.py:120-136) - simple markdown-fence stripping + `json.loads()`
- This is LESS robust than `ripple.utils.json_parser.parse_json_from_llm()` which handles fenced blocks, balanced-brace extraction, and YAML fallback

**JSON parsing patterns**:

- `OmniscientAgent._parse_json()`: strips markdown fences, then `json.loads()`. Simple but fragile - will fail on: prose mixed with JSON, truncated JSON, YAML-style syntax (trailing commas, unquoted keys)
- `ripple.utils.json_parser.parse_json_from_llm()`: robust multi-strategy parser that tries: raw text, fenced blocks, balanced-brace extraction, JSON then YAML. Used only in tests, NOT in production OmniscientAgent code.

**Error handling for malformed JSON**:

- OmniscientAgent retries up to `max_retries` (default 2) on `json.JSONDecodeError`, `ValueError`, `KeyError`
- On retry, prepends `RETRY_JSON_PREFIX_SHORT` ("上一次输出解析失败: {error}\n请重新输出合法 JSON。")
- After all retries fail, returns a safe fallback dict

**Budget management**: `BudgetState` (router.py:48-114) tracks:
- `total_calls`, `max_calls` (default 800)
- `total_attempts` (includes failures)
- `calls_by_role`, `attempts_by_role`
- Auto-degradation at 80% usage, hard block at 100%
- `max_calls <= 0` means unlimited

### 4. Configuration

#### Files Found

| File Path | Description |
|---|---|
| `ripple/llm/config.py` | `ModelEndpointConfig`, `LLMConfigLoader` - three-tier config resolution |
| `ripple/llm/router.py` (lines 122-410) | `ModelRouter` initialization, budget, stream/timeout overrides |
| `ripple/service/settings.py` | `ServiceSettings` - service-level config (db_path, output_dir, api_token) |
| `llm_config.example.yaml` | Example LLM config YAML showing full config format |
| `ripple/api/simulate.py` (lines 248-273) | `simulate()` parameters: `llm_config`, `max_llm_calls`, `stream`, `llm_timeout` |

#### Configuration Parameters

**ModelEndpointConfig** (config.py:44-171):

| Parameter | Default | Configurable via |
|---|---|---|
| `model_platform` | auto-inferred from model_name | code > file > env |
| `model_name` | REQUIRED (no default) | code > file > env |
| `api_key` | None | code > file > env (${VAR}) |
| `url` | None | code > file > env |
| `api_mode` | auto-inferred | code > file |
| `temperature` | None (omit from request) | code > file |
| `max_tokens` | 4096 | code > file |
| `timeout` | None (adapter default 120.0s) | code > file |
| `max_retries` | 3 | code > file |
| `stream` | True | code > file, ModelRouter override |

**Phase-specific timeouts**: NOT configurable. No per-phase timeout exists. Timeout is per-LLM-call only.

**Phase-specific max_tokens**: NOT configurable. Same `max_tokens` applies to all phases for a given role.

**Prompt size limits**: NOT configurable. No truncation or size cap on prompts.

**Environment variable patterns** (settings.py + config.py):

| Variable | Purpose | Default |
|---|---|---|
| `RIPPLE_API_TOKEN` | Service auth token | "" |
| `RIPPLE_DB_PATH` | SQLite database path | "data/ripple-service/ripple_service.db" |
| `RIPPLE_OUTPUT_DIR` | Output directory | "/data/ripple_outputs" |
| `RIPPLE_LLM_CONFIG_PATH` | LLM config YAML path | "/app/llm_config.yaml" |
| `RIPPLE_CANCEL_TTL_SECONDS` | Cancel token TTL | "60" |
| `ANTHROPIC_API_KEY` | Used in Anthropic adapter (via ${VAR} in YAML) | - |
| `OPENAI_API_KEY` | Used in OpenAI adapters (via ${VAR} in YAML) | - |

**LLM config resolution priority** (config.py:345-424):

1. Role-level code config (highest)
2. Global code default (`_default`)
3. Role-level file config
4. Global file default (`_default`)

**Degradation mapping**: `_degradation` key maps roles to fallback model names when budget exceeds 80%.

**simulate() configurable parameters** (simulate.py:248-273):

| Parameter | Default | Description |
|---|---|---|
| `max_llm_calls` | 800 | Total LLM call budget per simulation |
| `max_waves` | None (safety cap) | Max wave cap |
| `stream` | None (config default) | Force streaming mode |
| `llm_timeout` | None (config default) | Override per-call timeout |
| `deliberation_rounds` | 3 (server cap 4) | Tribunal rounds |
| `ensemble_runs` | 1 | Ensemble simulation count |
| `simulation_horizon` | None | Time horizon for deterministic wave calc |

## Caveats / Not Found

1. **No per-phase timeout**: The runtime has NO timeout wrapper for individual phases or the entire simulation. If the SYNTHESIZE LLM call hangs beyond the adapter timeout (default 120s, or whatever `llm_timeout` overrides), the only enforcement is the httpx-level timeout. There is no "simulation must complete within X minutes" safety net.

2. **No per-phase max_tokens**: SYNTHESIZE uses the same max_tokens (default 4096) as all other omniscient phases. For complex synthesis outputs with large evidence packs, 4096 tokens may be insufficient, leading to truncated JSON responses.

3. **OmniscientAgent uses fragile JSON parser**: `_parse_json()` is a simple markdown-fence stripper + `json.loads()`. The more robust `ripple.utils.json_parser.parse_json_from_llm()` exists but is NOT used in production OmniscientAgent code. This means truncated or malformed JSON will cause retries, and after max retries, a fallback error dict is returned.

4. **No structured output enforcement**: Despite requiring "strict JSON" output, no `response_format`, `json_schema`, or structured output mode is used at the API level. The LLM could output prose, incomplete JSON, or non-JSON, and the only enforcement is prompt instruction + retry on parse failure.

5. **SYNTHESIZE prompt size unbounded**: The `snapshot_json`, `obs_json`, and `input_json` are serialized with `indent=2` and no truncation. For simulations with many waves, extensive historical data, or large DELIBERATE output, the SYNTHESIZE prompt can become very large, potentially exceeding model context windows or causing very long generation times.

6. **No `ripple/config/` directory**: The `ripple/config/__init__.py` file does not exist. Configuration is handled by `ripple/llm/config.py` (LLM config) and `ripple/service/settings.py` (service settings).

7. **Job-level execution has no timeout**: `JobManager._execute()` does NOT wrap the simulation in `asyncio.wait_for()`. The only timeout is in `JobManager.wait()` which is called externally by consumers. The service API does not set a timeout on job execution either.