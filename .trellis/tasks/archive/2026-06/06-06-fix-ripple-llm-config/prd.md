# Fix Ripple LLM Config Missing

## Problem

Ripple CAS simulations fail with "omniscient role missing model_name" because:
1. Container lacks `/app/llm_config.yaml` — bootstrap needs 3 env vars (`RIPPLE_LLM_MODEL_PLATFORM`, `RIPPLE_LLM_MODEL_NAME`, `RIPPLE_LLM_API_KEY`) but they weren't passed to the container
2. Backend API requests don't include `llm_config` as fallback
3. Health check only verifies `/healthz` (HTTP reachable), not LLM config availability — shows green when simulations will actually fail

## Root Cause

`.env` used `RIPPLE_LLM_MODEL` (single field, not recognized by Ripple bootstrap) instead of the 3 required fields. Container startup command only passed `RIPPLE_PHASE_TIMEOUT_INIT` and `RIPPLE_INIT_MERGED`.

## Solution

1. **Container**: Restart with 4 LLM env vars so bootstrap generates `llm_config.yaml`
2. **Backend**: `RippleService.submit_simulation` auto-injects `llm_config` from Settings; `client.py` tools also inject it
3. **Health check**: Verify LLM config completeness; show `reason="llm_missing"` when incomplete
4. **Settings**: Add `llm_model_platform`, `llm_model_name`, `llm_api_key`, `llm_url` to `RippleSettings`
5. **.env/.env.example**: Replace `RIPPLE_LLM_MODEL` with the 4 proper fields