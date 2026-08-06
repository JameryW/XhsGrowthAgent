# Viral-probability gate read from Settings (content_strategist:283)

## Goal

`backend/agents/content_strategist.py:283` hardcodes the low-viral-probability
gate at `0.3`:

```python
if (
    ripple_prediction
    and "ripple_reason" not in ripple_prediction
    and ripple_prediction.get("viral_probability", 1.0) < 0.3
):
    ...
    retry_response = await self._llm_ainvoke([SystemMessage(...), HumanMessage(...)])
```

When `viral_probability < threshold`, the strategist fires a **second**
`_llm_ainvoke` (line 294) to regenerate the strategy with Ripple insights.
content_strategist is the single slowest node (~352s wall-clock in prod —
two serial astron calls); the regen adds a third. The threshold is a tuning
knob (how aggressive to be about re-trying low-virality plans) that's
currently un-tunable without a code change + redeploy.

Same dead-config pattern as #465 (`ripple-sim-params-read-settings`): a
Ripple behavioral parameter hardcoded in the agent instead of read from
`Settings().ripple`. Make it configurable via `RIPPLE_LOW_VIRAL_THRESHOLD`
env var (default `0.3` — byte-identical behavior until ops tunes it).

## What I already know

- Site: `content_strategist.py:280-284` (the `if ripple_prediction ...
  viral_probability < 0.3` guard). The `< 0.3` is the only hardcoded value.
- The branch (lines 285-308) fires `self._llm_ainvoke` (line 294) — a full
  LLM round-trip + `_build_ripple_context` + `_build_system_prompt` +
  `_parse_json_response`. Expensive.
- `Settings` already imported at `content_strategist.py:14` and used 4×
  in the same file (lines 145, 165, 531, 582) — all `Settings().ripple.<field>`.
  No new import needed.
- `RippleSettings` (`backend/config/settings.py:77-104`, `env_prefix="RIPPLE_"`)
  has no `low_viral_threshold` field — needs adding. Default `0.3`.
  `model_config = {"env_prefix": "RIPPLE_", ..., "extra": "ignore"}` → env var
  is `RIPPLE_LOW_VIRAL_THRESHOLD`.
- #465 precedent: added `default_max_waves`/`default_simulation_horizon`/
  `default_ensemble_runs` to RippleSettings, read via
  `Settings().ripple.<field>` in `_ripple_predict`/`_ripple_validate_pmf`.
  Exact same shape.
- Test coverage: `tests/unit/agents/test_content_strategist.py:134` uses
  `viral_probability: 0.3` — exactly at threshold (`< 0.3` is False), so it
  does NOT exercise the regen branch. Changing the gate to
  `Settings().ripple.low_viral_threshold` with default `0.3` keeps this test
  green (0.3 still not `< 0.3`). The regen branch itself has no covering
  test today.
- `system_config` SYSTEM_KEYS override whitelist: `low_viral_threshold` is NOT
  in it (only embed-related + a few others). So DB override won't clobber
  the env var — `Settings()` reads env directly. (Same as #465's ripple fields.)
- content_strategist is the costliest node (PR#472 flagged 352s, 2× serial
  astron). The regen adds a 3rd call on the low-virality path — the
  threshold directly controls how often that 3rd call fires.

## Recommended approach (ponytail)

Two-line change, exact #465 precedent:

```python
# settings.py — add to RippleSettings (after default_ensemble_runs or near
# the other tuning defaults):
low_viral_threshold: float = 0.3  # 传播概率低于此值则注入 Ripple 数据重新生成策略

# content_strategist.py:283:
# before:
and ripple_prediction.get("viral_probability", 1.0) < 0.3
# after:
and ripple_prediction.get("viral_probability", 1.0) < Settings().ripple.low_viral_threshold
```

~2 lines (1 field + 1 site). Default `0.3` = byte-identical behavior; ops
can raise it (regen less often → faster/cheaper) or lower it (regen more)
without a redeploy via `RIPPLE_LOW_VIRAL_THRESHOLD`.

- Pros: makes the costliest-node's 3rd-call gate tunable; exact #465
  precedent; zero behavior change at default. Closes a hardcoded-magic-number.
- Cons: none. The `0.3` default is preserved; nobody has to set the env var.

**Rejected: also add a test for the regen branch.** The branch already
exists and works; adding a test for it is scope-creep for a config-extraction
PR. The existing `:134` test (0.3 at threshold, no regen) stays green and
proves the gate still works. Keep the diff minimal — config extraction only.

## Requirements

- `content_strategist.py:283` reads `Settings().ripple.low_viral_threshold`
  instead of hardcoded `0.3`.
- `RippleSettings` gains `low_viral_threshold: float = 0.3` field
  (env `RIPPLE_LOW_VIRAL_THRESHOLD`).
- Default behavior unchanged (0.3 threshold → same regen decisions).

## Acceptance Criteria

- [ ] `RippleSettings` has `low_viral_threshold: float = 0.3`.
- [ ] `content_strategist.py:283` uses `Settings().ripple.low_viral_threshold`.
- [ ] `tests/unit/agents/test_content_strategist.py:134` (0.3 at threshold)
      still passes — no regen, gate unchanged at default.
- [ ] New test: setting `RIPPLE_LOW_VIRAL_THRESHOLD` env (or monkeypatching
      `Settings().ripple.low_viral_threshold`) to e.g. `0.5` makes a
      `viral_probability: 0.3` prediction trigger the regen branch (proves
      the setting is actually read, not dead). Non-vacuous — fails if the
      hardcoded `0.3` stays.
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- settings.py 1-field add
- content_strategist.py 1-site change
- 1 non-vacuous test proving the env var is read
- Pre-push triple green
- PR off `origin/main`, separate branch

## Out of Scope

- Tuning the threshold value (default stays 0.3; ops tunes via env).
- Refactoring the regen branch itself.
- Adding system_config SYSTEM_KEYS entry (env-only is fine, matches #465's
  other ripple fields).
- Other hardcoded magic numbers in content_strategist (separate audit).

## Technical Notes

- Files: `backend/config/settings.py` (RippleSettings, ~line 84) +
  `backend/agents/content_strategist.py` (line 283) + test.
- Precedent: #465 `ripple-sim-params-read-settings` — same Settings().ripple
  extraction pattern, same file, same env_prefix. Memory:
  `ripple-sim-params-read-settings.md`.
- content_strategist cost context: #472 (cost-track), 352s prod latency,
  2× serial astron + this 3rd regen call on low-virality.
- `Settings()` is per-call instantiation (pydantic BaseSettings); matches
  existing :145/:165/:531/:582 usage — no caching concern beyond what's
  already there.

## Decision (ADR-lite)

**Context**: content_strategist:283 hardcodes the viral-probability gate at
0.3, controlling whether the costliest node fires a 3rd LLM call. Untunable
without code change. Same dead-config class as #465.
**Decision**: extract to `RippleSettings.low_viral_threshold` (default 0.3,
env `RIPPLE_LOW_VIRAL_THRESHOLD`), read via `Settings().ripple.<field>`.
**Consequences**: threshold tunable at deploy time without redeploy (raise =
fewer 3rd calls = faster/cheaper). Default preserves behavior. ~2 LOC + 1
non-vacuous test. Low risk.
