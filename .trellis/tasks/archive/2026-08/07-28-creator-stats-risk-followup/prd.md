# Creator Stats Risk-Control Follow-up

## Objective

Finish and verify the ongoing Creator Center statistics risk-control work. The
sync pipeline must minimize unnecessary browser activity while preserving an
explicit manual refresh path and stable API behavior.

## Scope

- Keep scheduled imports list-only by default, with a bounded deep-enrichment
  cadence controlled by configuration.
- Apply account freshness and authentication gates before opening or enriching
  a browser session; scope authentication cooldowns to the active account.
- Ensure empty, fresh, skipped, and failed runs do not incorrectly consume
  global cooldowns or scheduled light-run cadence.
- Treat malformed and non-finite environment values as safe defaults, and keep
  risk-control defaults documented in `.env.example` and configuration docs.
- Add regression tests for the state-machine boundaries and run backend quality
  checks.

## Non-goals

- No changes to the Creator Center scraping selectors or persisted metric
  schema.
- No changes to unrelated workflow, publishing, or frontend behavior.
- No automatic QR login or retry loop that could increase platform activity.

## Acceptance Criteria

1. Scheduled sync skips fresh snapshots before login preflight and does not
   advance the light-run streak.
2. A failed scheduled fetch restores the prior light-run streak so retries do
   not become deep runs merely because of a failure.
3. Manual sync-all can explicitly request bounded enrichment, while a
   single-account sync still honors freshness unless explicitly bypassed by a
   login-triggered path.
4. Empty batches do not start a successful-sync cooldown; active-account auth
   cooldowns do not block unrelated accounts.
5. Non-finite numeric configuration values fall back safely; documentation and
   tests match runtime defaults.
6. Targeted and full unit tests, Ruff, mypy, and diff checks pass.

## Risks and Mitigations

- Process-local cadence state can drift after failures; snapshot and restore
  the counter around each scheduled attempt and cover it with tests.
- A freshness check can fail due to a transient database error; fail open to
  the existing sync path and log only the existing recoverable behavior.
- Manual bypasses can become accidental scheduler defaults; keep scheduler and
  API call sites explicit and assert their keyword arguments in tests.
