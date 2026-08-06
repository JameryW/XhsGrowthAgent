# Backend Quality Guidelines

> Enforceable coding standards for the `backend/` package. Derived from actual
> configuration and code patterns in this repository.

---

## 1. Linting (Ruff)

**Configuration** (`pyproject.toml`):

```toml
[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "SIM"]

[tool.ruff.lint.per-file-ignores]
"backend/api/routes/*.py" = ["B008"]
```

### Rule set meaning

| Prefix | Category            | Key enforcements                                        |
| ------ | ------------------- | ------------------------------------------------------- |
| E      | pycodestyle errors  | Whitespace, indentation, blank-line rules               |
| F      | pyflakes            | Unused imports, undefined names                         |
| I      | isort               | Import ordering: stdlib, third-party, local             |
| N      | pep8-naming         | ClassNames, function_names, UPPER_CASE constants        |
| UP     | pyupgrade           | Modern Python 3.11 syntax (`X | Y`, no `Optional`)      |
| B      | flake8-bugbear      | Mutable defaults, unused loops, `except` shadowing      |
| SIM    | flake8-simplify     | Simplifies `if x: return True else: return False`       |

### Per-file ignores

- `B008` (function-call-in-default-argument) suppressed in
  `backend/api/routes/*.py` because Pydantic `Field(default=...)` and
  `Query(default=...)` are standard FastAPI patterns.

### Not selected

- **ERA** (eradicate): Commented-out code detection is too noisy.
- **C90** (complexity): No McCabe threshold; prefer readable code.
- **D** (docstrings): Not enforced by linter; follow comment conventions.

### Commands

```bash
ruff check .          # lint
ruff format .         # auto-format
ruff check --fix .    # auto-fix safe violations
ruff format --check . # CI gate: fail when formatting is not committed
```

CI runs the formatting check in `--check` mode, so run `ruff format .` and
commit the resulting changes before opening a pull request. This keeps local
formatting drift from breaking an otherwise passing build.

---

## 2. Type Checking (mypy)

**Configuration** (`pyproject.toml`):

```toml
[tool.mypy]
python_version = "3.11"
strict = true
```

`strict = true` enables: `disallow_untyped_defs`, `disallow_any_generics`,
`warn_return_any`, `disallow_untyped_calls`, and more.

### Practical implications

- Every public function must declare parameter types and return type.
- Use `dict[str, Any]` for unstructured data (API responses, parsed JSON).
- Use Python 3.11 union syntax (`X | Y`, `X | None`) instead of
  `Optional[X]` or `Union[X, Y]`.

```python
# Correct
async def execute(self, state: XHSGrowthState, store: BaseStore) -> dict[str, Any]: ...

# Wrong
async def execute(self, state, store): ...
```

---

## 3. Testing Patterns

### 3.1 Framework

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- **pytest-asyncio** in `auto` mode: `async def test_*` functions are
  automatically async tests. No `@pytest.mark.asyncio` decorator needed.

### 3.2 Directory structure

```
tests/
  conftest.py              # Global fixtures (autouse LLM/Ripple mocks)
  test_*.py                # Top-level unit tests
  unit/
    agents/                # Agent unit tests
    api/                   # API unit tests
    cli/                   # CLI unit tests
    config/                # Config unit tests
    core/                  # Core module tests
    graph/                 # Graph builder tests
    memory/                # Memory store tests
    realtime/              # WebSocket/EventBus tests
    services/              # Service tests (ripple, xhs_client, etc.)
    state/                 # State schema tests
    tools/                 # Tool tests
      content/             # Content tool tests
  integration/
    test_api_routes.py     # Full API route tests with TestClient
    test_workflow_status_flow.py
    test_optimization_flow.py
    test_sse_eventbus.py
  contract/
    test_type_sync.py      # OpenAPI spec sync verification
```

### 3.3 Global autouse fixtures

Two `autouse=True` fixtures prevent real API calls:

**`_mock_get_model`**: Patches `get_model` in all import locations.

```python
@pytest.fixture(autouse=True)
def _mock_get_model():
    mock_model = MagicMock()
    mock_model.ainvoke = AsyncMock(return_value=MagicMock(content='{"result": "mocked"}'))
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("backend.models.router.get_model", lambda *a, **kw: mock_model)
        mp.setattr("backend.agents.base.get_model", lambda *a, **kw: mock_model)
        mp.setattr("backend.services.llm_enrichment.get_model", lambda *a, **kw: mock_model)
        mp.setattr("backend.core.base_agent.get_model", lambda *a, **kw: mock_model)
        yield
```

**`_mock_ripple_service`**: Patches `RippleService.get_instance` to return
an unhealthy mock with fallback predictions.

**Key rule**: When adding a new import location for `get_model`, add it to
this fixture.

### 3.4 Standard fixtures

- `initial_state` -- complete `XHSGrowthState` dict with defaults
- `mock_llm` -- `AsyncMock` returning `MagicMock(content='{"hot_topics": ...}')`
- `mock_store` -- `AsyncMock` with `asearch` and `aput`
- `mock_graph` (integration) -- Mock compiled graph
- `client` (integration) -- FastAPI `TestClient` with mocked graph

### 3.5 Mocking patterns

**Patch the import location, not the original module.**

```python
# Correct
with patch.object(service, "_get_config", return_value={...}): ...
with patch("backend.services.ripple_service.httpx.AsyncClient", return_value=mock_client): ...

# Wrong
with patch("httpx.AsyncClient", ...): ...
```

**Use `MagicMock` for sync, `AsyncMock` for async.**

```python
mock_response = MagicMock()
mock_response.status_code = 200
mock_response.json.return_value = {"job_id": "test-123"}

mock_client.post = AsyncMock(return_value=mock_response)
```

### 3.6 Test organization

- Group tests into classes: `class TestRippleServiceRetry:`
- Descriptive docstrings (Chinese acceptable): `"""第二次尝试成功"""`
- Each test verifies one behavior; use parameterized tests for variants.

---

## 4. Import Conventions

### 4.1 Import order (enforced by ruff `I`)

1. **Standard library**: `from __future__ import annotations`, `json`, `logging`
2. **Third-party**: `httpx`, `pydantic`, `langchain_core`, `fastapi`
3. **Local**: `from backend.core import ...`, `from backend.state import ...`

### 4.2 `from __future__ import annotations`

Place as the first import in every file. Enables PEP 604 union syntax
and forward references without quotes.

```python
"""Module docstring."""
from __future__ import annotations

import json
import logging
...
```

### 4.3 Lazy imports for circular-avoidance

When a module only needs a type at type-checking time or a function at call
time, use a local import inside the function:

```python
def _get_model_id(self) -> str:
    from backend.config.models import get_model_id_for_task
    return get_model_id_for_task(self.task_type)
```

This pattern appears in `BaseAgent._get_model_id`, `RippleService._emit_progress`,
and `emit_error_event`.

### 4.4 Module-level singletons

Agent instances are created at module level:

```python
_trend_scout = TrendScoutAgent()

async def trend_scout_node(state: XHSGrowthState, *, store: BaseStore) -> dict[str, Any]:
    result = await _trend_scout(state, store=store)
```

Prefix with `_` to signal "private module-level".

### 4.5 Banned imports

- Never import `pytest` in production code.
- Never import from `tests/` in production code.
- Avoid `from typing import Optional, Union` -- use `X | Y` syntax.

---

## 5. Code Style and Comments

### 5.1 Philosophy

1. **Three similar lines is better than a premature abstraction.** Do not
   extract a shared function until you have at least three concrete call sites.

2. **Don't add error handling for scenarios that can't happen.** If a function
   is only called with valid inputs, don't guard against invalid ones.

3. **Default to writing no comments.** Only add one when the WHY is
   non-obvious. Code should explain WHAT; comments should explain WHY.

4. **Don't add features, refactor, or introduce abstractions beyond what the
   task requires.** YAGNI. No speculative generalization.

5. **Avoid backwards-compatibility hacks like renaming unused `_vars`.** Clean
   breaks are preferred over accumulating aliases.

6. **No emoji in code.** Emoji in docstrings, comments, or string literals
   sent to users is acceptable (e.g., `"⚠️ {note}"`). No emoji in variable
   names, function names, or log messages.

### 5.2 Section divider comments

```python
# ── 健康检查 ──
# ── 重试机制 ──
# ── 降级策略 ──
# ── 高级 API ──
# ── 取消与恢复 ──
# ── 结果解析 ──
```

Use these for major logical sections within a file. Chinese labels acceptable.

### 5.3 Docstrings

- Module docstring: one line describing the module's purpose.
- Class docstring: brief description, may include feature list.
- Method docstring: only when public and non-obvious. Use Google-style
  `Args:` / `Returns:` / `Raises:` sections.

```python
async def wait_for_completion(
    self,
    job_id: str,
    poll_interval: float = 10.0,
    max_wait: float = 1800.0,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """轮询等待模拟完成

    Args:
        job_id: 模拟任务 ID
        poll_interval: 轮询间隔（秒）
        max_wait: 最大等待时间（秒）
        thread_id: 关联的工作流线程 ID，用于推送进度事件

    Returns:
        最终的模拟状态响应

    Raises:
        RippleTimeoutError: 超过最大等待时间（携带 job_id）
        RuntimeError: 模拟失败
    """
```

### 5.4 Logging

Use module-level loggers with the `xhs_growth` namespace:

```python
logger = logging.getLogger("xhs_growth.core")
logger = logging.getLogger("xhs_growth.services.ripple")
logger = logging.getLogger("xhs_growth.api.workflow")
```

Pattern: `xhs_growth.<package>.<module>`.

| Level   | When to use                                           |
| ------- | ----------------------------------------------------- |
| DEBUG   | Polling status, internal state dumps                  |
| INFO    | Successful operations, health check results           |
| WARNING | Retries, degraded service, unexpected but recoverable |
| ERROR   | Agent failures, unhandled exceptions                  |

Use `exc_info=True` for error logging when you want the full traceback:

```python
logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
```

---

## 6. Error Handling

### 6.1 Agent-level (BaseAgent)

`BaseAgent.__call__` wraps `execute()` in a try/except. Agents never need to
catch their own exceptions:

```python
async def __call__(self, state, *, store):
    try:
        result = await self.execute(state, store)
        result["performance_log"] = [{"status": "success", ...}]
        return result
    except Exception as e:
        logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
        return {
            "error": f"{self.agent_name}: {type(e).__name__}: {e}",
            "retry_count": state.get("retry_count", 0) + 1,
            "performance_log": [{"status": "error", ...}],
        }
```

**Key rule**: Agent `execute()` methods should let exceptions propagate.

### 6.2 Node-level cancellation

Use `_check_cancelled(state)` at the start of every node function:

```python
async def trend_scout_node(state, *, store):
    _check_cancelled(state)
    ...
```

Raises `WorkflowCancelledError` if phase is `CANCELLED` or `PAUSED`.

### 6.3 Service-level retry (RippleService)

`_request_with_retry` implements manual retry:

- Retries only on **5xx** errors and **connection errors**.
- 4xx errors (client errors) are **not retried**.
- Default: 3 retries, 1s base delay with linear increase.

```python
if resp.status_code >= 500 and attempt < max_retries - 1:
    await asyncio.sleep(retry_delay * (attempt + 1))
    continue
```

### 6.4 Service-level fallback

When external service is unavailable, return a structured default:

```python
def _default_spread_prediction(self) -> dict[str, Any]:
    return {
        "ripple_prediction": {
            "estimated_reach": 0,
            "viral_probability": 0.0,
            ...
        },
        "ripple_fallback": True,
        "ripple_reason": reason,
    }
```

Callers check `result.get("ripple_fallback")` to know if result is real or
degraded.

### 6.5 API-level error handling

**Exception hierarchy** (`backend/api/errors.py`):

```
APIError (base)
  ├── WorkflowNotFoundError    (404)
  ├── ReviewNotPendingError    (400)
  ├── ChoiceNotPendingError    (400)
  ├── ValidationError          (400)
  └── AuthenticationError      (401)
        ├── TokenMissingError
        ├── TokenInvalidError
        └── LoginFailedError
```

All API exceptions inherit `APIError` and carry:
- `code: ErrorCode` (enum like `"ERROR_WORKFLOW_NOT_FOUND"`)
- `message: str`
- `details: dict[str, Any] | None`
- `status_code: int`

**Unified response envelope** (`backend/api/responses.py`):

```python
# Success
success(data={"thread_id": "...", "status": "running"})

# Error
raise WorkflowNotFoundError(thread_id)  # caught by middleware, returns 404
```

Every API response follows `ApiResponse[T]`:

```python
class ApiResponse(BaseModel, Generic[T]):
    success: bool
    data: T | None = None
    error: ErrorDetail | None = None
    timestamp: datetime
    request_id: str | None = None
```

**Key rule**: Route handlers should `raise` domain errors, not return error
responses manually.

### 6.6 Publish error classification

`classify_publish_error(error_msg)` maps error strings to structured types:

```python
PublishErrorType.AUTH_EXPIRED     # cookie/login/token/auth/401/403
PublishErrorType.RATE_LIMITED     # rate limit/429/throttl
PublishErrorType.CONTENT_VIOLATION # violation/sensitive
PublishErrorType.IMAGE_MISSING    # image/photo/upload
PublishErrorType.NETWORK_ERROR    # network/timeout/connection
```

Each type carries a recovery action dict with `message`, `action`,
`action_label`, and `hint`.

---

## 7. State Management

### 7.1 Schema

`XHSGrowthState` is a `TypedDict(total=False)` -- all fields optional at type
level, but runtime code should provide defaults for new workflows.

### 7.2 Reducers

Fields that accumulate across graph steps use annotated reducers:

```python
messages: Annotated[list, add_messages]       # LangGraph built-in
engagement_actions: Annotated[list[EngagementAction], _append_list]
ripple_job_ids: Annotated[list[str], _append_list]
content_versions: Annotated[list[ContentVersion], _append_list]
brief_content: Annotated[BriefContent, _merge_dict]
```

**Reducer semantics** (`state/reducers.py`):

| Reducer      | Behavior                         | Use for                            |
| ------------ | -------------------------------- | ---------------------------------- |
| `merge_dict` | Shallow merge, right wins        | Sub-state dicts (brief, shooting)  |
| `append_list`| Concatenate right to left        | Growing lists (actions, versions)  |
| `replace`    | Right replaces left              | Simple scalar fields               |
| `max_value`  | Keep the larger numeric value    | Progress counters                  |

**Key rule**: When adding a new field, choose the correct reducer. If the
field should accumulate, use an annotated reducer. If it should overwrite,
leave it un-annotated.

### 7.3 Enums

All enums use `StrEnum` (Python 3.11+), not `Enum`:

```python
class WorkflowPhase(StrEnum):
    SCOUTING = "scouting"

class WorkflowStatus(StrEnum):
    RUNNING = "running"
```

`StrEnum` ensures `.value` is a plain string, serializes cleanly to JSON.

### 7.4 Status derivation

Workflow status is **derived, not stored**. `derive_status()` in
`state/machine.py` computes status from `StateSnapshot`:

1. Cancelled (phase flag)
2. Paused (phase flag)
3. Interrupt at review_gate -> awaiting_review
4. Interrupt at choice_gate -> awaiting_choice
5. Interrupt at draft_gate -> awaiting_draft
6. Error in state -> error
7. Phase is completed -> completed
8. Has next nodes but no active task -> stale
9. Has next nodes with active task -> running
10. No next nodes + no interrupt -> completed

**Key rule**: Never write `if status == "running"` directly. Always derive
status via `derive_status(snapshot, has_active_task=...)`.

---

## 8. API Route Patterns

### 8.1 Route structure

```python
from fastapi import APIRouter
from backend.api.errors import ValidationError, WorkflowNotFoundError
from backend.api.responses import success

router = APIRouter()

@router.post("/start")
async def start_workflow(req: WorkflowStartRequest, request: Request):
    if not req.account_id or req.account_id.strip() == "":
        raise ValidationError("account_id", "account_id cannot be empty")
    ...
    return success(data={...})
```

### 8.2 Request/Response models

Use Pydantic `BaseModel`:

```python
class WorkflowStartRequest(BaseModel):
    account_id: str = Field(default="default", description="账号 ID")
    phase: WorkflowPhase = Field(default=WorkflowPhase.SCOUTING)
    async_mode: bool = Field(default=True)
```

Response models use `Field(default_factory=...)` for mutable defaults:

```python
class WorkflowStatusResponse(BaseModel):
    trend_data: dict = Field(default_factory=dict)
    content_versions: list[dict] = Field(default_factory=list)
```

### 8.3 Validation

- Input validation: raise `ValidationError(field, reason)`
- Existence checks: raise `WorkflowNotFoundError(thread_id)`
- Guard checks: return `success(data={"status": "awaiting_review", ...})`

### 8.4 Background tasks

```python
task = asyncio.create_task(_run_async())
task.add_done_callback(_on_task_done(thread_id))
_background_tasks[thread_id] = task
```

The `_on_task_done` callback:
- Consumes exceptions to avoid "Task exception was never retrieved".
- Records `task_done_at` and `task_error` in registry.
- Marks orphaned running workflows as `stale`.

---

## 9. Naming Conventions

| Element              | Convention               | Example                              |
| -------------------- | ------------------------ | ------------------------------------ |
| Module files         | `snake_case.py`          | `ripple_service.py`, `base_agent.py` |
| Classes              | `PascalCase`             | `RippleService`, `NodeResult`        |
| Functions/methods    | `snake_case`             | `predict_spread`, `_parse_json`      |
| Constants            | `UPPER_SNAKE_CASE`       | `MODEL_REGISTRY`, `PHASE_PROGRESS`   |
| Private methods      | Leading `_`              | `_get_config`, `_default_spread`     |
| Private module vars  | Leading `_`              | `_workflow_registry`, `_instance`     |
| Pydantic models      | `PascalCase`             | `WorkflowStartRequest`               |
| Enums                | `PascalCase` members     | `WorkflowPhase.SCOUTING`             |
| Fixture functions    | Leading `_` if autouse   | `_mock_get_model`, `_mock_ripple`     |

---

## 10. Forbidden Patterns

### 10.1 Never do these

1. **Never catch `Exception` and pass silently.** Every caught exception must
   be logged or re-raised. Exception: `_on_task_done` consumes `CancelledError`.

2. **Never use `requests` library.** Use `httpx` for all HTTP calls.

3. **Never use `Enum` instead of `StrEnum`.** All enums must be `StrEnum`.

4. **Never store workflow status as a persistent field.** Always derive it.

5. **Never create agent instances inside node functions.** Instantiate at
   module level: `_agent = AgentClass()`.

6. **Never use `Optional[X]` or `Union[X, Y]`.** Use `X | Y` and `X | None`.

7. **Never use `from __future__ import annotations` inconsistently.** This
   codebase uses it everywhere.

### 10.2 Avoid unless you have a good reason

1. **Avoid `type: ignore` comments.** Fix the type error instead.
2. **Avoid `Any` in function signatures.** Use specific types or `dict[str, Any]`.
3. **Avoid global mutable state beyond module-level singletons.**
4. **Avoid `try/except` in agent `execute()` methods.** Let `BaseAgent.__call__`
   handle errors.

---

## 11. Required Patterns

### 11.1 Every new agent must

1. Extend `BaseAgent` and define `task_type`, `agent_name`, `prompt_file`.
2. Implement `async def execute(self, state, store) -> dict[str, Any]`.
3. Have a corresponding node function in `agents/nodes/` that:
   - Calls `_check_cancelled(state)`.
   - Emits `WORKFLOW_AGENT_STARTED` and `WORKFLOW_AGENT_COMPLETED` events.
   - Wraps result in `NodeResult(..., "agent_name").to_dict()`.
4. Import any needed tools via direct submodule imports inside `execute()` (no central registry).
5. Have edges added in `graph/builder.py`.
6. Be exported in `agents/__init__.py` and `agents/nodes/__init__.py`.

### 11.2 Every new API route must

1. Raise domain exceptions (`APIError` subclasses), not return error responses.
2. Return `success(data=...)` for successful responses.
3. Use Pydantic `BaseModel` for request/response types.
4. Validate inputs early (empty strings, missing fields).
5. Be mounted on a router in `api/app.py`.

### 11.3 Every new state field must

1. Be added to `XHSGrowthState` with appropriate type annotation.
2. Use an annotated reducer if it should accumulate.
3. Have a default value in `initial_state` fixture and `start_workflow`.
4. Be included in `WorkflowStatusResponse` if it should appear in status API.

---

## 12. Code Review Checklist

Before merging any PR that touches `backend/`:

- [ ] `ruff check .` passes with zero violations
- [ ] `ruff format --check .` shows no formatting changes needed
- [ ] `mypy backend` passes (strict mode)
- [ ] `pytest` passes with no warnings
- [ ] No real LLM or Ripple API calls in tests (autouse fixtures intact)
- [ ] New `get_model` import locations added to `_mock_get_model` fixture
- [ ] Agent exceptions propagate to `BaseAgent.__call__` (no swallowed errors)
- [ ] API routes raise `APIError` subclasses, return `success(data=...)`
- [ ] New state fields have appropriate reducers and defaults
- [ ] Enums use `StrEnum`, not `Enum`
- [ ] Union syntax uses `X | Y`, not `Optional` or `Union`
- [ ] No emoji in variable names, function names, or log messages
- [ ] Comments explain WHY, not WHAT
- [ ] No speculative abstractions (three similar lines before extracting)

## Scenario: Quality-consistency API and evaluator changes

### 1. Scope / Trigger
- Trigger: a change touches canonical historical-note reads, RQGM evaluation
  statuses, account filters, evaluation persistence, or cross-layer DTOs.

### 2. Signatures
- `list_note_stats_page(...) -> NoteStatsPage`
- `POST /api/evaluation/note`, `GET /api/evaluation/note/{account_id}/{note_id}/latest`
- `EvaluatorAgent._build_evaluation_result(...)` and historical sanitizer

### 3. Contracts
- Additive response metadata must include account/subject/scope,
  assessment type, status, coverage, snapshot/evaluation timestamps and the
  deterministic algorithm or evaluator fingerprint.
- Historical-note RQGM runs read the target note and the complete Creator Stats
  snapshot bundle together. Persist `result_json.source.snapshot_id`; cache
  hits and latest restore must not present a run as current when that canonical
  snapshot has changed. Older runs may use the timestamp fallback and must be
  treated as stale when compared with a current bundle.
- Use one `MIN_EVALUATION_COVERAGE` constant; no missing dimension may be filled
  with 70 and no degraded result may become a pass.
- Canonical history is stable cursor pagination with fraction engagement rates;
  old bounded readers remain compatibility previews.

### 4. Validation & Error Matrix
- Ruff check + format and mypy must pass for changed backend modules.
- Empty IDs, malformed cursors and unsupported sort values fail at the API boundary.
- DB/cache failures log a safe fallback; evaluator failures return explicit
  degraded/partial states and do not enter aggregates.

### 5. Good/Base/Bad Cases
- Good: focused tests prove >500 pagination, two-account isolation, idempotent
  evaluation, force versioning, canonical evaluation snapshots/stale restore,
  and threshold-aware UI metadata.
- Base: legacy workflow checkpoints remain readable through additive adapters.
- Bad: broad exception swallowing, hidden list caps, or changing score semantics
  without updating API types/tests/i18n.

### 6. Tests Required
- `tests/unit/api/test_quality_consistency_backend.py` and identity tests cover
  cursor, fractions, degraded/partial and durable runs.
- Existing evaluator tests cover omitted dimensions, timeout and no fake pass.
- Run `pytest -q tests/unit`, `ruff check`, `ruff format --check`, and compileall.

### 7. Wrong vs Correct
```python
# Wrong: a raw LLM score bypasses coverage and status normalization.
return {"overall_score": raw["overall_score"], "decision": raw["decision"]}

# Correct: normalize dimensions, coverage, status and nullability centrally.
return agent._build_evaluation_result(raw, historical=is_historical, state=state)
```
