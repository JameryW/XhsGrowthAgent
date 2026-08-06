# Sanitize omp-session-start exception leak (agent.py:125)

## Goal

`backend/api/routes/agent.py:125` sends raw `str(e)` to the websocket client
in the omp-session-start failure path:

```python
except Exception as e:
    logger.exception("failed to start omp session")
    await websocket.send_json(
        {
            "type": ServerEventType.ERROR,
            "message": f"omp session failed: {e}",
        }
    )
```

Same class of information-leakage security gap fixed in #497 for the 3 other
sites (middleware 500, workflow task_error, agent ws handler). This 4th site
was flagged out-of-scope by trellis-check in #497 and deferred. This PR closes
it — raw exception text (internal paths, library class names, config fragments)
no longer reaches the omp websocket client. Server-side logging unchanged.

## What I already know

- Site: `agent.py:120-129`. `except Exception as e:` → `logger.exception(...)`
  (server-side full detail preserved) → `websocket.send_json({"message":
  f"omp session failed: {e}"})` (client-facing raw leak).
- #497 pattern (agent.py:286 ws handler): `except Exception:` (drop `e`
  binding, ruff F841) → `logger.exception("...")` (unchanged) →
  `"message": "internal error"` (generic). `logger.exception` captures the
  active exception automatically without the binding.
- The site 3 fix in #497 is the exact precedent — same file, same pattern,
  same ws client. This site just wasn't in #497's scope (3-site PR).
- `get_or_create_session` (line 119) can raise for: DB errors, config issues,
  bridge manager failures, auth — all carry internals in `str(e)`.
- Server-side `logger.exception("failed to start omp session")` already
  captures the full traceback (line 121) — unchanged.
- No frontend parses the raw message (verified in #497: grep
  `details\.exception|\.exception\b` in frontend returned nothing; omp TUI
  consumes the ws ERROR event generically).

## Recommended approach (ponytail)

One-line sanitization, mirroring #497's site 3 exactly:

```python
# before (agent.py:120-129):
except Exception as e:
    logger.exception("failed to start omp session")
    await websocket.send_json(
        {
            "type": ServerEventType.ERROR,
            "message": f"omp session failed: {e}",
        }
    )
# after:
except Exception:
    logger.exception("failed to start omp session")
    # ponytail: raw str(e) to the omp ws client leaks internals;
    # full detail preserved in logger.exception above. Same fix as #497 site 3.
    await websocket.send_json(
        {
            "type": ServerEventType.ERROR,
            "message": "omp session failed",
        }
    )
```

~2 lines changed (drop `as e`, generic message). Keep "omp session failed"
prefix (without `: {e}`) — it's a useful context label (which subsystem
failed), not internal detail. `logger.exception` unchanged (full traceback
server-side).

- Pros: closes the last flagged client-facing exception leak. ~2 LOC, exact
  #497 precedent, low risk. Server-side logging unchanged.
- Cons: none. Client loses raw exception text (the point).

**Rejected: generic "internal error"** — "omp session failed" is a useful
subsystem label (vs #497 site 3's bare "internal error" which was a generic
ws handler). The omp TUI can show "omp session failed" meaningfully. Keep the
label, drop the `: {e}`.

## Requirements

- `agent.py:125` no longer sends raw `str(e)` to the ws client.
- Server-side `logger.exception` unchanged (full traceback preserved).
- Client receives `"omp session failed"` (label without internals).
- `except Exception as e:` → `except Exception:` (e unused after fix; ruff
  F841 — same as #497 site 3).

## Acceptance Criteria

- [ ] `agent.py:125` message is `"omp session failed"` (no `str(e)`/`{e}`).
- [ ] `logger.exception("failed to start omp session")` unchanged.
- [ ] `except Exception as e:` → `except Exception:` (no F841).
- [ ] Test: omp-session-start failure sends generic message, raw exception
      text not in ws payload (non-vacuous — fails on revert). Match #497's
      `test_ws_handler_error_does_not_leak_raw_exception_text` shape.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- agent.py 1-site fix
- Non-vacuous test
- Pre-push triple green
- PR off `origin/main`, separate branch

## Out of Scope

- Other leak sites (all closed by #497 + this PR).
- Structured error codes / omp error-response redesign.
- Frontend changes (omp TUI consumes ws ERROR generically).

## Technical Notes

- File: `backend/api/routes/agent.py` (lines 120-129) + test.
- Precedent: #497 site 3 (`agent.py:286`) — same file, same pattern. Copy the
  test shape from `tests/unit/api/test_agent_ws.py::test_ws_handler_error_does_not_leak_raw_exception_text`.
- Test: mock `manager.get_or_create_session` to raise a secret-bearing
  exception (e.g. `RuntimeError("secret internal path /etc/passwd")`), hit the
  ws connect path, assert the ERROR message is "omp session failed" and the
  secret does not appear in the sent JSON.
- `# ponytail:` comment explaining the sanitization (matches #497's comment
  style).

## Decision (ADR-lite)

**Context**: agent.py:125 sends raw `str(e)` to omp ws client on
session-start failure — same leak class as #497's 3 sites, flagged
out-of-scope there.
**Decision**: sanitize to "omp session failed" (label without internals);
drop `as e` binding; logger.exception unchanged. Exact #497 site-3 precedent.
**Consequences**: last flagged client-facing exception leak closed. ~2 LOC,
low risk. Server-side logging fully preserved.
