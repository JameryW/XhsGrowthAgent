# Implementation plan

1. Update `backend/config/models.py`: register `mimo-v2.6-flash`, change only general route defaults, keep explicit DeepSeek routes, and leave MiMo cost estimation on the existing generic fallback until an official rate is confirmed.
2. Update `backend/config/settings.py` so the legacy `model_routing` map agrees with the requested MiMo V2.6 Flash defaults.
3. Extend the shared retry/model-call wrappers and `backend/models/router.py` with lazy DeepSeek V4 Flash failover for retryable MiMo call failures. Cover both plain invocation and derived bound/structured-output runnables; preserve auth/4xx behavior.
4. Update the existing routing assertions and model-routing references in `README.md`, `README.zh-CN.md`, `CLAUDE.md`, and `docs/configuration.md`.
5. Document the reusable model retry/fallback contract in `.trellis/spec/backend/error-handling.md`.
6. Review the final diff against this PRD and run a syntax/whitespace check. Do not run the test suite unless the user asks for verification.

## Expected files

- `backend/config/models.py`
- `backend/config/settings.py`
- `backend/models/router.py`
- `backend/models/retry.py`
- `.trellis/spec/backend/error-handling.md`
- `tests/unit/config/test_model_routing.py` (update existing expectations only)
- `tests/unit/config/test_models.py` (update existing expectations only)
- `README.md`
- `README.zh-CN.md`
- `CLAUDE.md`
- `docs/configuration.md`

## Risk checkpoints

- Ensure structured-output and bound runnables are wrapped; the current router returns models used through both forms.
- Ensure DeepSeek is not eagerly constructed and missing backup credentials do not break healthy MiMo calls.
- Ensure explicit DeepSeek routes and routing overrides do not acquire a second fallback layer.
- Keep cost estimates clearly approximate because a V2.6 Flash token rate was not available in the reviewed official pricing page.
