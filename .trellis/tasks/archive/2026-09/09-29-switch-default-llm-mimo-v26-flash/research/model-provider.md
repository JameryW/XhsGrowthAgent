# Model provider research

## Repository findings

- Xiaomi MiMo is already supported as `ModelProvider.XIAOMIMIMO` in `backend/config/models.py` and `backend/models/router.py`.
- The router reads `XIAOMIMIMO_API_KEY` and uses `XIAOMIMIMO_BASE_URL`, defaulting to the Token Plan endpoint.
- `deepseek-v4-flash` is already registered and uses the existing DeepSeek endpoint/key.
- Retryability is currently defined in `backend/models/retry.py`: HTTP 429/5xx and connection/timeout/transport-style errors retry; authentication and other 4xx errors do not.
- Xiaomi's public page advertises V2.6 access through its Token Plan. The reviewed page did not provide V2.6 Flash per-token input/output prices, so no new price estimate is asserted.

## Sources

- Xiaomi MiMo API Open Platform: https://platform.xiaomimimo.com/
- Xiaomi MiMo API documentation: https://platform.xiaomimimo.com/#/docs/api/chat/openai-api
