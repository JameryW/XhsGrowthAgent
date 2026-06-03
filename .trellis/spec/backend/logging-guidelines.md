# Logging Guidelines

> How logging is done in this project.

---

## Overview

This project uses Python's built-in `logging` module. All loggers are created via
`logging.getLogger(...)` with a hierarchical `xhs_growth.*` namespace. No
third-party logging libraries (structlog, loguru, etc.) are used.

---

## Logger Creation

Use the `xhs_growth.*` hierarchy. The convention is:

| Layer | Logger name pattern | Example |
|---|---|---|
| Core / base classes | `xhs_growth.core` | `getLogger("xhs_growth.core")` |
| Agents | `xhs_growth.agents.<name>` | `getLogger("xhs_growth.agents.content_strategist")` |
| Agent base (shared) | `xhs_growth.agents` | `getLogger("xhs_growth.agents")` |
| Graph nodes | `xhs_growth.graph.nodes` | `getLogger("xhs_growth.graph.nodes")` |
| Services | `xhs_growth.services.<name>` | `getLogger("xhs_growth.services.ripple")` |
| Services (flat) | `xhs_growth.<name>` | `getLogger("xhs_growth.xhs_client")` |
| Tools | `xhs_growth.tools.<name>` | `getLogger("xhs_growth.tools.ripple")` |
| API routes | `xhs_growth.api.<name>` | `getLogger("xhs_growth.api.runner")` |
| API middleware | `xhs_growth.api` | `getLogger("xhs_growth.api")` |
| Models / cost | `xhs_growth.cost_tracker` | `getLogger("xhs_growth.cost_tracker")` |
| Error handling | `xhs_growth.error_handling` | `getLogger("xhs_growth.error_handling")` |

**Canonical form** -- declare at module top, after imports:

```python
import logging

logger = logging.getLogger("xhs_growth.agents.content_strategist")
```

**Exceptions** (avoid): Two files use `__name__` instead of a literal string:
- `backend/api/routes/workflow.py` uses `getLogger(__name__)` at module level but
  overrides with `getLogger("xhs_growth.api.workflow")` inside callbacks.
- `backend/agents/version_generator.py` uses `getLogger(__name__)`.

New code should always use a literal `"xhs_growth.*"` string for consistency.

---

## Log Levels

### DEBUG -- Transient polling / internal state

Used for high-frequency or low-importance operational details that would be noisy
at INFO level.

```python
# ripple_service.py -- poll status during long-running simulation
logger.debug(f"Ripple simulation {job_id} status: {state}, waiting {poll_interval}s...")

# draft_gate.py -- gate resume detail
logger.debug("Draft gate resumed with user decision: %s", decision.get("title", "no title"))

# brief_gate.py -- skip logic
logger.debug("Brief clarification resolved or not needed, proceeding")
```

### INFO -- Normal operations, milestones, and fallback activations

Used for successful completions, significant state changes, and when fallback
paths are intentionally activated.

```python
# ripple_service.py -- health check success
logger.info(f"Ripple health check passed: {latency:.0f}ms")

# ripple_service.py -- simulation completion
logger.info(f"Ripple simulation {job_id} completed after {elapsed:.0f}s")

# ripple_service.py -- fallback activation (intentional, not an error)
logger.info(f"Ripple unavailable (reason={reason}), using fallback prediction")

# cost_tracker.py -- per-call cost tracking
logger.info(f"Cost: ${cost:.4f} | Model: {model} | Task: {task}")

# content_strategist.py -- strategic decision
logger.info(f"Low viral probability ({ripple_prediction['viral_probability']:.2f}), regenerating strategy with Ripple insights")

# visual_analysis.py -- cache hit
logger.info(f"Using cached analysis for scene: {scene}")

# publisher.py -- dry-run mode
logger.info("dry_run=True, executing trial publish")
```

### WARNING -- Recoverable problems, retries, degraded service

Used when something went wrong but the system recovered or fell back. Includes
retry attempts, timeouts with fallbacks, missing optional data, and
unexpected-but-handled responses.

```python
# ripple_service.py -- retry attempts
logger.warning(f"Ripple request failed (attempt {attempt + 1}): {e}")

# ripple_service.py -- health check failure (service unavailable, not crashed)
logger.warning(f"Ripple health check failed: HTTP {resp.status_code}")

# ripple_service.py -- simulation timeout (caller handles fallback)
logger.warning(f"Ripple spread prediction timed out: job_id={e.job_id}")

# content_strategist.py -- optional feature skipped
logger.warning(f"Ripple prediction skipped: {e}")

# trend_scout.py -- individual tool failure (agent continues)
logger.warning(f"xhs_trending failed: {e}")

# base_agent.py -- LLM response parse failure (returns raw_content)
logger.warning(f"Failed to parse JSON response from {self.agent_name}: {content[:200]}")

# xhs_client.py -- missing credentials
logger.warning("Cookie not configured, cannot fetch trending topics")

# cost_tracker.py -- budget exceeded
logger.warning(f"Daily budget exceeded: ${self.today_total():.2f} > ${self.daily_budget:.2f}")

# choice_gate.py -- fallback selection
logger.warning("Selected version not found or missing, falling back to first version")
```

### ERROR -- Unrecoverable failures, unexpected exceptions

Used when an operation failed and could not be recovered. Always include
`exc_info=True` when the error originates from a caught exception (to get the
full traceback), unless using `logger.exception()` which adds it automatically.

```python
# base_agent.py -- agent crash with traceback
logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)

# ripple_service.py -- unrecoverable service error
logger.error(f"Ripple health check error: {e}")

# ripple_service.py -- request error after all retries exhausted
logger.error(f"Ripple request error: {e}")

# xhs_publisher.py -- publish failure with traceback
logger.error(f"Publish failed: {e}", exc_info=True)

# _runner.py -- graph execution crash (uses logger.exception for auto exc_info)
logger.exception("Graph execution failed (source=%s, thread=%s)", source, thread_id)

# middleware.py -- unhandled server error
logger.exception(f"Unexpected error [{request_id}]: {e}")

# image_prompt.py -- tool crash
logger.error(f"image_prompt_generator error: {e}")
```

**Guideline for exc_info**: Use `exc_info=True` on `logger.error()` when you
catch an exception and want the traceback. Use `logger.exception()` as a
shorthand (it auto-sets `exc_info=True` and always logs at ERROR level).

---

## Message Formatting

### Primary style: f-strings

The dominant pattern across the codebase is f-string interpolation:

```python
logger.info(f"Ripple simulation {job_id} completed after {elapsed:.0f}s")
logger.warning(f"Ripple request failed (attempt {attempt + 1}): {e}")
logger.error(f"Agent {self.agent_name} failed: {e}", exc_info=True)
```

### Secondary style: %-formatting (legacy / API-layer)

A few files use `%s`-style formatting. This is found in the API layer and one
gate node:

```python
# workflow.py callback
logger.error("Background task for %s failed: %s", thread_id, e)

# _runner.py
logger.exception("Graph execution failed (source=%s, thread=%s)", source, thread_id)

# draft_gate.py
logger.debug("Draft gate resumed with user decision: %s", decision.get("title", "no title"))
```

**New code should use f-strings** for consistency with the majority of the
codebase. The `%s` style is acceptable in the API layer where it is already
established.

### No JSON structured logging

The project does not use structured/JSON logging. All messages are plain
human-readable strings. Key-value context is embedded inline:

```python
logger.info(f"Cost: ${cost:.4f} | Model: {model} | Task: {task}")
logger.info(f"Ripple unavailable (reason={reason}), using fallback prediction")
```

### Bilingual messages

Some log messages are in Chinese (particularly in platform-facing services and
tools), while agent and infrastructure code uses English. This is acceptable and
reflects the domain -- XHS platform operations naturally use Chinese terms:

```python
# Chinese (platform services)
logger.warning("Cookie not configured, cannot fetch trending topics")  # was: 未配置 Cookie
logger.error(f"获取热门话题失败: {e}")

# English (infrastructure, agents)
logger.warning(f"Ripple request failed (attempt {attempt + 1}): {e}")
logger.info(f"Ripple simulation {job_id} completed after {elapsed:.0f}s")
```

---

## What to Log

### Always log

| Event | Level | Example |
|---|---|---|
| Agent execution failure | ERROR + exc_info | `Agent {name} failed: {e}` |
| External service health checks | INFO (pass) / WARNING (fail) | `Ripple health check passed: {latency}ms` |
| External service unavailability with fallback | INFO | `Ripple unavailable (reason={reason}), using fallback prediction` |
| Retry attempts | WARNING | `Ripple request failed (attempt {n}): {e}` |
| Workflow milestones | INFO | `Ripple simulation {job_id} completed after {elapsed}s` |
| LLM cost per call | INFO | `Cost: ${cost:.4f} \| Model: {model} \| Task: {task}` |
| Budget threshold breach | WARNING | `Daily budget exceeded: ${total} > ${budget}` |
| Gate interrupts | INFO | `Interrupting at draft_gate for user confirmation` |
| JSON parse failures | WARNING | `Failed to parse JSON response from {agent}` |
| Graph execution crash | ERROR (exception) | `Graph execution failed (source={s}, thread={t})` |
| Unexpected API errors | WARNING | `API Error [{request_id}]: {code} - {message}` |
| Unhandled exceptions | ERROR (exception) | `Unexpected error [{request_id}]: {e}` |

### Sometimes log (DEBUG only)

| Event | Level | Example |
|---|---|---|
| Poll/heartbeat status during waits | DEBUG | `Ripple simulation {job_id} status: {state}, waiting...` |
| Gate resume details | DEBUG | `Draft gate resumed with user decision: {decision}` |
| LLM enrichment invocation | DEBUG | `Invoking LLM for {task_type} enrichment` |

---

## What NOT to Log

### Never log these values

The following fields from `backend/config/settings.py` and `.env.example` must
never appear in log output:

| Setting | Why |
|---|---|
| `ANTHROPIC_API_KEY` | LLM provider credential |
| `OPENAI_API_KEY` | LLM provider credential |
| `DEEPSEEK_API_KEY` | LLM provider credential |
| `DASHSCOPE_API_KEY` | LLM provider credential |
| `XIAOMIMIMO_API_KEY` | LLM provider credential |
| `XHS_COOKIE` | Platform session token (full auth) |
| `XHS_USER_ID` | PII / platform identity |
| `RIPPLE_API_TOKEN` | Service credential |
| `POSTGRES_URI` | Contains DB password |
| `REDIS_URI` | May contain password |
| `IMAGE_GEN_API_KEY` | Service credential |
| `NOTIFICATION_WEBHOOK_URL` | Internal endpoint |
| `AUTH_SECRET_KEY` | JWT signing key |
| `AUTH_ADMIN_PASSWORD` | Admin credential |

### Partial masking convention

When you must reference a credential for debugging, mask all but the last 4
characters:

```python
# Good
logger.info(f"Connecting with API key ...{api_key[-4:]}")

# Bad
logger.info(f"Connecting with API key {api_key}")
```

### Additional sensitive data to exclude

- **Full LLM prompt/response bodies** -- log only truncated content
  (`content[:200]`) or a summary, never the entire response
- **User-generated content containing PII** -- do not log user DMs, comments,
  or personal info verbatim
- **HTTP Authorization headers** -- the `Bearer` token must not be logged;
  `ripple_service.py` builds headers via `_get_headers()` but never logs them
- **Cookie values in XHS client** -- `xhs_client.py` logs operations like
  "Fetching trending topics" but never logs the cookie value itself

### Pattern for safe logging of LLM responses

```python
# base.py -- truncate content on parse failure
logger.warning(f"Failed to parse JSON response from {self.agent_name}: {content[:200]}")
```

This truncation pattern should be followed whenever logging user-generated or
LLM-generated content that could be large or contain unexpected PII.

---

## Summary of Conventions

1. **Logger naming**: Always use `logging.getLogger("xhs_growth.<layer>.<name>")`
   with a literal string, not `__name__`.
2. **Message format**: Use f-strings (dominant pattern). `%s`-style is
   acceptable only in the API layer where already established.
3. **No structured/JSON logging**: Plain human-readable strings with inline
   key-value pairs.
4. **exc_info**: Add `exc_info=True` to `logger.error()` when catching
   exceptions, or use `logger.exception()` for automatic traceback.
5. **DEBUG for noise**: Poll status, heartbeat checks, and gate resume details
   go to DEBUG, never INFO.
6. **INFO for fallbacks**: When a degraded path is intentionally activated
   (e.g., "using fallback prediction"), log at INFO, not WARNING.
7. **WARNING for retries**: Transient failures and retry attempts are WARNING,
   not ERROR.
8. **ERROR for crashes**: Only use ERROR when the operation failed and no
   fallback is available.
9. **Never log secrets**: API keys, cookies, tokens, passwords, and URIs with
   credentials must never appear in log output. Mask to last 4 chars if
   reference is necessary.
10. **Truncate large content**: When logging LLM responses or user content,
    truncate to a reasonable length (200 chars by convention).
