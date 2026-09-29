# PRD: Switch the default LLM to MiMo V2.6 Flash

## Goal

Use MiMo V2.6 Flash as the primary model for the application's general LLM routes, with DeepSeek V4 Flash as an automatic backup for retryable MiMo service failures.

## Background

- `backend/config/models.py` currently routes general workflow tasks to `astron-code-latest`; `viral_matching`, `polish`, and `mock_gen` have explicit `deepseek-v4-flash` routes.
- The model registry contains `mimo-v2.5-pro` and `deepseek-v4-flash`, but not MiMo V2.6 Flash.
- `backend/models/retry.py` retries transient failures on the same model. The router currently has no provider failover.
- `ModelSettings.model_routing` in `backend/config/settings.py` is an unused legacy default map set to MiMo V2.5 Pro.
- Ripple simulations have an independent LLM setting and are not part of the application model router.

## Requirements

1. Register MiMo V2.6 Flash with the existing Xiaomi MiMo provider, API key, and base URL support.
2. Route the general application task types that currently use `astron-code-latest` to MiMo V2.6 Flash.
3. Keep explicit DeepSeek task routes and caller-supplied routing overrides unchanged.
4. After the existing MiMo retry policy is exhausted, use DeepSeek V4 Flash for retryable rate-limit, server, network, or timeout failures. Do not fail over for authentication, invalid-request, or other non-retryable errors.
5. Apply the same primary/fallback behavior to plain, bound, and structured-output model calls made through the router.
6. Update the stale default map and user-facing model-routing documentation to match runtime behavior.

## Acceptance criteria

- Every general task type previously routed to `astron-code-latest` resolves to the registered `mimo-v2.6-flash` model.
- The router uses `deepseek-v4-flash` only after retryable MiMo call failures exhaust existing retries.
- Authentication and other non-retryable errors propagate without failover.
- Explicit DeepSeek routes and caller-provided model overrides continue to resolve unchanged.
- The fallback works for standard and structured-output calls, and existing call/result contracts remain intact.
- Documentation describes the primary route, the specialized DeepSeek routes, and the backup behavior accurately.

## Out of scope

- Changing Ripple's separate `RIPPLE_LLM_MODEL_NAME` / `RIPPLE_LLM_MODEL` configuration.
- Changing task-specific DeepSeek routes, explicit caller overrides, provider credentials, or API endpoints.
- Assigning a per-token cost estimate for MiMo V2.6 Flash without a verified rate.

## Risks and deferred items

- Automatic failover requires a valid `DEEPSEEK_API_KEY`; MiMo remains the primary route.
- The public Xiaomi page currently describes V2.6 access through Token Plan subscriptions, but does not list per-token input/output rates. Until verified rates are available, the analytics estimator will use its existing generic fallback for MiMo V2.6 Flash. This is an inference from the published pricing page and is recorded in `research/model-provider.md`.
