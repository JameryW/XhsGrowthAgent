# trend_scout: parallelize independent XHS API fetches

## Goal

`backend/agents/trend_scout.py:24-77` `_fetch_real_data` runs 3 XHS API tool
calls **serially** on every trend_scout execute (trend_scout is the workflow
entry node — START → orchestrator → trend_scout):

```python
trending = await xhs_trending.ainvoke({"category": niche, "account_id": account_id})      # :35
# ... keywords built from trending[:3] ...
monitor_data = await keyword_monitor.ainvoke({"keywords": keywords, ...})                  # :55
competitor_data = await competitor_analyzer.ainvoke({...})                                 # :65
```

XHS API calls are slow network round-trips (slower than Postgres store
`asearch`). Serialized = 3 serial RTTs on the trend_scout critical path.

**Dependency analysis:**
- `xhs_trending` (`:35`) — independent (niche, account_id).
- `competitor_analyzer` (`:65`) — independent (niche, account_id). Writes
  `data["competitor_analysis"]`.
- `keyword_monitor` (`:55`) — **DEPENDS on `trending`**: `:48-53` builds the
  keyword seed from `trending[:3]` topic titles. Cannot start before
  `xhs_trending` returns. Must stay sequential after trending.

So the safe parallelization: gather `xhs_trending` + `competitor_analyzer`
(both independent, both swallow own exceptions, write disjoint `data` keys),
then run `keyword_monitor` after (needs `trending`). Saves ~1 serial RTT
(competitor now overlaps with trending instead of serial after it).

XHS API RTT > Postgres RTT, so 1 saved serial XHS RTT is a bigger absolute
win than the copywriter/strategist memory-recall gathers (#502/#503).

## What I already know

- **3 calls, 2 independent + 1 dependent.** Verified by reading `:24-77`:
  - `xhs_trending.ainvoke` (`:35`) → `trending` list → `data["hot_topics"]`.
  - `keyword_monitor.ainvoke` (`:55`) → needs `trending` for keywords
    (`:48-53`: `for t in trending[:3]: keywords.append(t.get("topic"))`).
  - `competitor_analyzer.ainvoke` (`:65`) → `data["competitor_analysis"]`,
    only uses niche/account_id, no dependency on trending or monitor.
- **Each call swallows its own exceptions** (`:38-39`, `:60-61`, `:74-75` —
  each in its own try/except, logs warning, continues; `data[...]` just not
  set on failure). Gather adds no new exception surface.
- **Disjoint `data` keys**: `hot_topics`, `keyword_monitor`, `competitor_analysis`.
  But `data` is a shared dict — concurrent writes to DIFFERENT keys are safe
  under GIL (dict key assignment is atomic), but to avoid any doubt the
  cleanest pattern is: each call returns its own value, then assign to `data`
  sequentially after the gather (not concurrent dict mutation). This is the
  ponytail pattern — return values, merge after.
- `keyword_monitor` keyword seed (`:45-53`): starts `[niche]`, inserts
  `user_topic` at front if set, then appends `trending[:3]` topics. This
  logic MUST run after `trending` is available — keep it between the gather
  and the `keyword_monitor` call.
- `asyncio` import status in trend_scout — verify during implement; if not
  imported, add it.
- Test coverage: `tests/unit/agents/test_trend_scout.py` (verify exists +
  mock shape during implement). Existing tests likely mock the 3 tools and
  assert `data` keys — gather keeps them green if return values + data dict
  are populated identically.
- **Precedent: PR #502/#503** (gather-parallel series) — same idiom, same
  exception-surface proof. But those gathered ALL calls; here only 2 of 3
  (the dependent one stays serial). New wrinkle: partial gather with a
  dependent follow-up.
- content_strategist:218 + copywriter:41 + this would be the 3rd gather in
  the codebase.

## Recommended approach (ponytail)

Gather the 2 independent calls; keep `keyword_monitor` serial after (needs
`trending`). Return-value pattern (no concurrent dict mutation):

```python
import asyncio  # if not already imported

async def _fetch_real_data(self, niche, account_id="", user_topic=""):
    from backend.tools.xhs.trending import (
        competitor_analyzer, keyword_monitor, xhs_trending,
    )

    # xhs_trending + competitor_analyzer are independent (no data dependency,
    # disjoint data keys, each swallows own exceptions) → run concurrently.
    # keyword_monitor DEPENDS on trending (builds keyword seed from
    # trending[:3] topic titles) so it stays serial after the gather.
    trending, competitor_data = await asyncio.gather(
        _safe_xhs_trending(niche, account_id),
        _safe_competitor_analyzer(niche, account_id),
    )

    data: dict[str, Any] = {}
    if trending:
        data["hot_topics"] = trending
    if competitor_data:
        data["competitor_analysis"] = competitor_data

    # keyword_monitor needs trending (enriches keyword seed) — sequential.
    try:
        keywords = [niche]
        if user_topic and user_topic not in keywords:
            keywords.insert(0, user_topic)
        if trending:
            for t in trending[:3]:
                topic = t.get("topic", "")
                if topic and topic not in keywords:
                    keywords.append(topic)
        monitor_data = await keyword_monitor.ainvoke(
            {"keywords": keywords, "account_id": account_id}
        )
        if monitor_data:
            data["keyword_monitor"] = monitor_data
    except Exception as e:
        logger.warning(f"keyword_monitor failed: {e}")

    return data
```

Where `_safe_xhs_trending` / `_safe_competitor_analyzer` are small inline
wrappers preserving the original try/except (swallow + log + return None/[]):

```python
async def _safe_xhs_trending(niche, account_id):
    try:
        return await xhs_trending.ainvoke({"category": niche, "account_id": account_id})
    except Exception as e:
        logger.warning(f"xhs_trending failed: {e}")
        return []

async def _safe_competitor_analyzer(niche, account_id):
    try:
        return await competitor_analyzer.ainvoke(
            {"account_id": niche, "niche": niche, "credential_account_id": account_id}
        )
    except Exception as e:
        logger.warning(f"competitor_analyzer failed: {e}")
        return None
```

~20 LOC net (2 small wrappers + gather + reorder). Behavior identical: same
3 values, same `data` keys, same keyword seed logic.

**Alternative (simpler, less LOC):** inline the try/except inside the gather
via a helper that returns the value, OR keep the try/except wrapping the
gather result. But the 2-wrapper approach is cleanest — each tool's failure
isolation preserved exactly as today (separate try/except, separate warning
message). Match the existing per-tool try/except granularity.

- Pros: ~1 fewer serial XHS API RTT on trend_scout (workflow entry node);
  XHS API > Postgres RTT so absolute win > #502/#503; exact #502/#503
  exception-surface proof; zero behavior change.
- Cons: slightly more LOC than #502/#503 (2 wrappers needed because each
  tool has its own try/except warning message to preserve). Partial gather
  (2 of 3) — keyword_monitor stays serial. Acceptable: the dependency is
  real, can't be removed without changing keyword-seed behavior.

**Rejected: gather all 3.** `keyword_monitor` depends on `trending` (keyword
seed from `trending[:3]`). Gathering it would require giving up the
trending-enriched keyword seed = behavior change. Keep the dependency.

**Rejected: remove trending from keyword seed (then gather all 3).** Behavior
change — the trending-topic enrichment is intentional. Out of scope.

## Requirements

- `xhs_trending` + `competitor_analyzer` run via `asyncio.gather` (concurrent).
- `keyword_monitor` runs AFTER the gather (serial), preserving the
  trending-derived keyword seed logic exactly.
- Each tool's try/except + warning message preserved (per-tool failure
  isolation).
- `data` dict populated identically (same keys, same values) as before.
- Return-value pattern (no concurrent `data` dict mutation during gather).

## Acceptance Criteria

- [ ] `_fetch_real_data` uses `asyncio.gather` for `xhs_trending` +
      `competitor_analyzer`; `keyword_monitor` runs after, with its keyword
      seed built from the gathered `trending` result.
- [ ] Each tool's try/except + distinct warning message preserved.
- [ ] `data` keys (`hot_topics`, `keyword_monitor`, `competitor_analysis`)
      populated identically for all success/failure combinations.
- [ ] Existing `tests/unit/agents/test_trend_scout.py` passes unchanged.
- [ ] New non-vacuous test: assert `xhs_trending` + `competitor_analyzer` run
      concurrently (patch `asyncio.gather`, assert called once with 2
      awaitables — mirror #502/#503 pattern). Must fail if reverted to serial.
      Note: if trend_scout has OTHER gathers, filter to the 2-awaitable one.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- trend_scout.py gather refactor (~20 LOC, 2 small wrappers)
- 1 non-vacuous concurrency test (mirror #502/#503)
- Pre-push triple green
- PR off `origin/main`, separate branch

## Out of Scope

- Removing the `trending`→`keyword_monitor` dependency (behavior change).
- Parallelizing `keyword_monitor` (data-dependent on trending).
- Other trend_scout awaits (`:89` _recall_memory + `:99` _fetch_real_data —
  could gather those 2 too, but _fetch_real_data is the slow one and already
  being optimized internally; mixing the store recall with the API fetch is a
  different scope. Note for later if wanted.)
- Other agents (separate audits).

## Technical Notes

- File: `backend/agents/trend_scout.py` (`_fetch_real_data` `:24-77`) + test.
- Tools: `backend/tools/xhs/trending.py` — `xhs_trending`, `keyword_monitor`,
  `competitor_analyzer` (all `@tool`-decorated, `.ainvoke`).
- Precedent: PR #502 (copywriter), #503 (content_strategist) — gather-parallel
  series. Memory: `copywriter-parallel-memory-recalls`. New wrinkle: partial
  gather (2 of 3) with a dependent follow-up call.
- XHS API RTT > Postgres store RTT, so 1 saved serial XHS RTT here > 1 saved
  store RTT in #502/#503 in absolute terms.
- trend_scout is the workflow entry node (START→orchestrator→trend_scout);
  every workflow run hits this path.

## Decision (ADR-lite)

**Context**: trend_scout's `_fetch_real_data` runs 3 XHS API calls serially on
the workflow entry node. 2 are independent (xhs_trending, competitor_analyzer);
1 (keyword_monitor) depends on trending's result for its keyword seed. XHS
API calls are slow.
**Decision**: gather the 2 independent calls; keep keyword_monitor serial
after (preserves the trending→keyword dependency). Return-value pattern, each
tool's try/except preserved.
**Consequences**: ~1 fewer serial XHS API RTT on trend_scout (competitor
overlaps with trending). Zero behavior change. ~20 LOC + 1 non-vacuous test.
Partial-gather pattern (dependent call stays serial) is a new variant of the
#502/#503 idiom. Low risk.
