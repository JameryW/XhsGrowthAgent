# Design: MiMo default route with DeepSeek failover

## Boundary

The change belongs in the backend model registry and `ModelRouter`, which are the shared path for agent and LLM-enrichment calls. Ripple simulations use their own setting and stay unchanged. Explicit DeepSeek routes and caller-provided overrides are preserved.

## Routing and provider construction

- Add `mimo-v2.6-flash` to `MODEL_REGISTRY` with `ModelProvider.XIAOMIMIMO`; reuse the existing MiMo API key and base URL resolution.
- Change only the general default entries in `resolve_model_id` from `astron-code-latest` to `mimo-v2.6-flash`.
- Synchronize `ModelSettings.model_routing` with the new MiMo model so the dormant configuration does not advertise V2.5 as the default.
- Keep `viral_matching`, `polish`, and `mock_gen` routed directly to `deepseek-v4-flash`.

## Failover behavior

- Keep the existing retry wrapper as the first layer around a MiMo call.
- Add an outer failover wrapper only when the resolved primary model is `mimo-v2.6-flash`. After the primary wrapper exhausts retries, fail over only when the final exception meets the existing retryable-error policy (429/5xx, connection, timeout, or transport errors).
- Build the DeepSeek model lazily so a missing backup key does not prevent healthy MiMo calls from starting. Use the task timeout and existing retry policy for the backup call; do not chain to another provider.
- Preserve non-retryable errors, including authentication and malformed-request errors, without calling DeepSeek.
- Wrap model-derived `bind` and `with_structured_output` runnables so structured-output calls follow the same policy. Keep synchronous and asynchronous invocation behavior aligned.
- Let response metadata identify the model that actually answered for telemetry. Do not add a guessed MiMo V2.6 cost rate; retain the estimator's existing generic fallback until an official per-token rate is verified.

## Compatibility

- No API, database, or persisted routing schema changes.
- Existing route overrides and task-specific DeepSeek model selection remain supported.
- The backup is an availability path for transient MiMo service failures; it does not mask configuration/authentication errors.

## Rollback

Restore the old default routing IDs and remove the router's MiMo-to-DeepSeek failover wrapper. The new registry entry can remain unused or be removed independently.
