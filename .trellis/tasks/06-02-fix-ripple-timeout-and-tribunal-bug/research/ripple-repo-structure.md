# Research: Ripple CAS Service Repository Structure

- **Query**: Research the Ripple CAS service repository at https://github.com/xyskywalker/Ripple to find tribunal.py score coercion bug, SYNTHESIZE phase timeout issues, and job lifecycle timeout patterns
- **Scope**: External (GitHub repository)
- **Date**: 2026-06-03

## Findings

### 1. Tribunal Score Coercion Bug (`int(v)`)

**File Path**: `ripple/agents/tribunal.py`

**Line 67** (in `evaluate` method):
```python
scores = {k: int(v) for k, v in data.get("scores", {}).items()}
```

**Line 127** (in `revise` method):
```python
scores = {k: int(v) for k, v in data.get("scores", {}).items()}
```

**Problem**: The `int(v)` coercion will raise `ValueError` if `v` is a string like `"3.5"` (float string) or `TypeError` if `v` is `None`. The LLM may return scores as float strings (e.g., `"4.0"`) which would crash the evaluation.

**Current Error Handling**: The code catches `ValueError` and falls back to default scores of 3 for all dimensions, but this loses the actual LLM output.

**Fix Should Look Like**:
```python
def _safe_int_score(value: Any, default: int = 3) -> int:
    """Safely coerce score to int, handling float strings and None."""
    if value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value.strip()))  # Handle "4.0" -> 4
        except (ValueError, TypeError):
            return default
    return default

# Usage:
scores = {k: _safe_int_score(v) for k, v in data.get("scores", {}).items()}
```

---

### 2. Other `int(v)` Score Coercion Locations

| File Path | Line | Context | Risk |
|-----------|------|---------|------|
| `ripple/api/simulate.py` | 753 | Ensemble kappa calculation: `iv = int(v)` | Low - wrapped in try/except, sets `ok=False` |
| `examples/e2e_ab_test_fmcg_coffee.py` | 661 | `role_scores[role] = {k: int(v) for k, v in scores.items()}` | Medium - example code, no error handling |
| `examples/e2e_helpers.py` | 197 | `int(v)` in metrics computation | Low - filtered by `isinstance(v, (int, float))` |

**Note**: The `simulate.py:753` case is properly handled with try/except. The `e2e_ab_test_fmcg_coffee.py:661` case has the same bug as tribunal.py.

---

### 3. SYNTHESIZE Phase Code - No Timeout/Prompt-Size Limits

**File Path**: `ripple/agents/omniscient.py`

**Method**: `synthesize_result()` (lines 585-634)

**Current Code**:
```python
async def synthesize_result(
    self,
    field_snapshot: Dict[str, Any],
    observation: Dict[str, Any],
    simulation_input: Dict[str, Any],
) -> Dict[str, Any]:
    # ... builds prompts ...
    for attempt in range(1 + self._max_retries):
        try:
            raw = await self._call_llm(
                user_prompt,
                phase="SYNTHESIZE",
                phase_system_prompt=phase_system,
            )
            # ... parse JSON ...
```

**Problems**:
1. **No timeout**: The `self._call_llm()` call has no per-call timeout wrapper. The LLM adapter has a default 120s timeout, but there's no hard limit on the SYNTHESIZE phase itself.
2. **No prompt-size limits**: The `field_snapshot` and `observation` JSON blobs are serialized directly into the user prompt without size checks. Large simulations (many waves, many agents) could produce prompts exceeding context windows.
3. **No token budget tracking**: No awareness of remaining context window budget.

**Prompt Templates** (in `ripple/prompts.py`):
- `OMNISCIENT_SYNTHESIZE_RELATIVE_SYSTEM` (lines 556-603): ~500 tokens
- `OMNISCIENT_SYNTHESIZE_ANCHORED_SYSTEM` (lines 612-666): ~600 tokens
- User templates inject `{snapshot_json}`, `{obs_json}`, `{input_json}` without size limits

**Fix Should Look Like**:
```python
# Add to synthesize_result():
MAX_SYNTHESIZE_PROMPT_CHARS = 50000  # ~12k tokens

async def synthesize_result(self, ...):
    # Truncate large JSON blobs
    snapshot_json = self._truncate_json(field_snapshot, max_chars=20000)
    obs_json = self._truncate_json(observation, max_chars=15000)
    input_json = self._truncate_json(simulation_input, max_chars=5000)
    
    # Add per-phase timeout
    try:
        raw = await asyncio.wait_for(
            self._call_llm(...),
            timeout=180.0  # 3 min hard cap
        )
    except asyncio.TimeoutError:
        return {"prediction": {"error": "SYNTHESIZE timeout"}}
```

---

### 4. LLM Agent Base Class - No Structured JSON Output Support

**File Path**: `ripple/llm/chat_completions_adapter.py`, `ripple/llm/anthropic_adapter.py`, `ripple/llm/responses_adapter.py`

**Current Pattern**: All adapters return raw `str` text. No support for:
- `response_format={"type": "json_object"}` (OpenAI)
- Structured outputs / JSON mode
- Schema validation

**ChatCompletionsAdapter._build_request()** (lines 274-293):
```python
def _build_request(self, system_prompt: str, user_message: str) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": self._model,
        "messages": messages,
    }
    # No response_format parameter
```

**AnthropicAdapter._build_request()** (lines 260-275):
```python
def _build_request(self, system_prompt: str, user_message: str) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "model": self._model,
        "max_tokens": self._max_tokens,
        "messages": [...],
    }
    # No structured output support
```

**Fix Should Look Like**:
```python
# Add to ModelEndpointConfig:
json_mode: bool = False  # Enable JSON mode for structured output

# In ChatCompletionsAdapter._build_request():
if self._json_mode:
    body["response_format"] = {"type": "json_object"}

# In AnthropicAdapter (use tool use for structured output):
if self._json_mode:
    body["tools"] = [{
        "type": "json_schema",
        "name": "structured_output",
        "input_schema": {...}
    }]
```

---

### 5. Job Lifecycle - No Hard Timeout Per Phase

**File Path**: `ripple/service/job_manager.py`

**Current Code** (lines 68-84):
```python
async def _execute(self, job_id: str, request: dict) -> None:
    self.repo.update_status(job_id, "running")
    try:
        result = await self._run_simulation(request, lambda ev: self._on_progress(job_id, ev))
        # No timeout wrapper!
```

**File Path**: `ripple/engine/runtime.py`

**Method**: `SimulationRuntime.run()` (lines 424-931)

**Problems**:
1. No per-phase timeout enforcement
2. No overall job timeout (only LLM call timeout via adapters)
3. `asyncio.wait_for()` is never used in the runtime
4. The only timeout is at the LLM adapter level (default 120s per call)

**Fix Should Look Like**:
```python
# In JobManager._execute():
JOB_TIMEOUT_SECONDS = 1800  # 30 min overall

async def _execute(self, job_id: str, request: dict) -> None:
    try:
        result = await asyncio.wait_for(
            self._run_simulation(request, ...),
            timeout=JOB_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        self.repo.set_error(job_id, {"code": "timeout", "message": "Job exceeded 30 min limit"})

# In SimulationRuntime.run():
PHASE_TIMEOUTS = {
    "INIT": 60,
    "SEED": 10,
    "RIPPLE": 1200,  # 20 min
    "OBSERVE": 120,
    "SYNTHESIZE": 180,
}

async def run(self, ...):
    # Wrap each phase with asyncio.wait_for
    init_result = await asyncio.wait_for(
        self._omniscient.init(...),
        timeout=PHASE_TIMEOUTS["INIT"]
    )
```

---

### Files Found Summary

| File Path | Description |
|-----------|-------------|
| `ripple/agents/tribunal.py` | Tribunal agent with score coercion bug (lines 67, 127) |
| `ripple/agents/omniscient.py` | Omniscient agent with SYNTHESIZE phase (lines 585-634) |
| `ripple/engine/runtime.py` | Simulation runtime orchestrator (lines 424-931) |
| `ripple/engine/deliberation.py` | Deliberation orchestrator for tribunal |
| `ripple/service/job_manager.py` | Job lifecycle manager (lines 68-84) |
| `ripple/llm/chat_completions_adapter.py` | OpenAI Chat Completions adapter |
| `ripple/llm/anthropic_adapter.py` | Anthropic Messages API adapter |
| `ripple/llm/responses_adapter.py` | OpenAI Responses API adapter |
| `ripple/llm/config.py` | LLM config with ModelEndpointConfig |
| `ripple/llm/router.py` | Model router with BudgetState |
| `ripple/api/simulate.py` | Public API with ensemble kappa (line 753) |
| `ripple/prompts.py` | Prompt templates including SYNTHESIZE |
| `ripple/primitives/pmf_models.py` | PMF data models |

---

## Caveats / Not Found

1. **No existing timeout infrastructure**: The codebase does not use `asyncio.wait_for()` anywhere in the engine or agents. All timeout handling is delegated to the LLM adapters' HTTP client timeout.

2. **No structured output support**: None of the LLM adapters implement JSON mode or structured output. All parsing is done post-hoc with `parse_json_from_llm()` which handles markdown code blocks.

3. **No prompt size tracking**: There is no token counting or prompt size validation before sending to LLM. Large simulations could silently fail or produce truncated responses.

4. **The `e2e_ab_test_fmcg_coffee.py` example**: This file has the same `int(v)` bug as tribunal.py but is example code, not production code. Still worth fixing for consistency.

---

## Related Specs

- `.trellis/spec/backend/ripple-service.md` - Ripple service integration spec (if exists)
