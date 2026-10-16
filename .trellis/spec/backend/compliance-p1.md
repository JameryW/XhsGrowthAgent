# Compliance P1 (Observability, Privacy, Auth)

Executable contracts from PR #659
(`10-16-compliance-p1-observability-privacy`). Extends
[Compliance Baseline (P0)](./compliance-baseline.md); do not regress P0
invariants while changing these surfaces.

## Scenario: Account health panel

### 1. Scope / Trigger

- Changing `GET /api/system/risk-gates`, `get_account_health`, Settings
  `XhsAccountsPanel`, or risk-gate KV fields.

### 2. Signatures

```python
# backend/services/xhs_risk_gate.py
def get_account_health(account_id: str = "") -> dict[str, Any]: ...
```

Returned (and exposed as `account_health` on risk-gates API) MUST include:

- effective cooldown policy (`get_cooldown_policy`)
- last risk hit time / reason (when known)
- remaining ban / cooldown seconds
- SAFE_MODE / min risk pressure indicators
- `engagement_pause` (reason + remaining)

### 3. Contracts

| Field | Location | Notes |
|-------|----------|--------|
| `account_health` | `GET /api/system/risk-gates?account_id=` | Per-account summary |
| `engagement_pause` | same response | P0 pause + P1 panel |
| Frontend | `XhsAccountsPanel` via `getRiskGates` | Must mock in vitest |

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| Missing `account_id` | Policy may be null; pause/health scoped empty |
| No recent risk | `last_risk_hit` absent/null — not fabricated |

### 5. Good / Base / Bad

- **Good**: Settings shows policy + pause + last hit matching API.
- **Base**: Account with no pause — health still returns effective policy.
- **Bad**: UI calling unmocked `/risk-gates` in vitest → toast.error.

### 6. Tests Required

- `tests/unit/services/test_account_health.py`
- `tests/unit/api/test_risk_gates_routes.py`
- `frontend/tests/components/XhsAccountsPanel.spec.ts` (mock `getRiskGates`)

### 7. Wrong vs Correct

#### Wrong
```ts
// Mount panel without mocking getRiskGates
expect(toastMock.error).not.toHaveBeenCalled() // flakes / fails
```

#### Correct
```ts
vi.mock('@/api/system', () => ({
  getRiskGates: vi.fn().mockResolvedValue({ engagement_pause: { paused: false }, account_health: {...} }),
}))
```

---

## Scenario: Scrape budget + minimization

### 1. Scope / Trigger

- Editing `backend/services/scrape_budget.py`, `XHSClient` homefeed/search/comments,
  or scrape cache retention.

### 2. Signatures

```python
class ScrapeBudgetExhaustedError(RuntimeError):
    error_code = "scrape_budget_exhausted"

def consume_or_cache(account_id, kind, fetcher) -> list: ...
def mask_nickname(value: str | None) -> str: ...
def mask_user_id(value: str | None) -> str: ...
def minimize_scrape_row(row: Any) -> Any: ...
```

### 3. Contracts

| Env | Default | Kind |
|-----|---------|------|
| `XHS_SCRAPE_HOMEFEED_DAILY_LIMIT` | 50 | homefeed |
| `XHS_SCRAPE_SEARCH_DAILY_LIMIT` | 50 | search |
| `XHS_SCRAPE_COMMENTS_DAILY_LIMIT` | 100 | comments |

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| Under budget | Fetch, store minimized cache, return |
| Over budget + cache hit | Return cache (no invent) |
| Over budget + no cache | Raise `scrape_budget_exhausted` |
| Stored rows | Nickname/ID masked (`U**r` / `***` style) |

### 5–7. Cases / Tests / Wrong-Correct

- Tests: `tests/unit/services/test_scrape_budget.py`; client tests expect masked names.
- **Wrong**: Fabricate mock trending data when budget exhausted.
- **Correct**: Cache or explicit `error_code=scrape_budget_exhausted`.

---

## Scenario: Privacy retention + Audience export/delete

### 1. Scope / Trigger

- `privacy_retention.py`, creator_agent audience routes, lifespan cleanup.

### 2. Signatures

```python
# backend/services/privacy_retention.py
DEFAULT_RETENTION_DAYS = 90
def retention_days() -> dict[str, int]: ...
async def run_privacy_cleanup() -> dict[str, Any]: ...
```

Audience Member:

- Export + Delete via creator_agent API (`GET`/`DELETE` audience by id).

### 3. Contracts

| Env | Default |
|-----|---------|
| `XHS_PRIVACY_AUDIENCE_RETENTION_DAYS` | 90 |
| `XHS_PRIVACY_COMMENTS_RETENTION_DAYS` | 90 |
| `XHS_PRIVACY_DM_RETENTION_DAYS` | 90 |
| `XHS_PRIVACY_RELATIONSHIP_RETENTION_DAYS` | 90 |

Cleanup covers relationship memory, scrape cache, inbound DM peer whitelist
(where no dedicated comments/DM tables exist — document in `docs/security.md`).

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| Past retention cutoff | Best-effort purge; errors recorded per family |
| Delete audience | Purge member + related memory rows |

### 5–7

- Tests: `tests/unit/services/test_privacy_retention.py`
- Docs: `docs/security.md` data inventory table MUST stay in sync.
- **Wrong**: Silent no-op cleanup without logging/result structure.
- **Correct**: `run_privacy_cleanup()` returns per-family purge stats/errors.

---

## Scenario: AI content declaration

### 1. Scope / Trigger

- Publish confirm UI, `PublishOptions.ai_content_declared`, publish_gate receipt,
  `de_ai_taste` prompt/docs.

### 2. Signatures / Contracts

| Field | Default | Location |
|-------|---------|----------|
| `ai_content_declared` | `true` | OpenAPI `PublishOptions`, Review checkbox, `publish_confirmation` |

### 3–4. Validation

- Default ON at confirm; stamp receipt alongside confirmer/source/time.
- `de_ai_taste.yaml` MUST forbid implying evasion of AI labeling requirements.

### 5–7

- Tests: dual_auto/commercial receipt tests; `test_de_ai_taste_compliance_copy.py`
  (resolve YAML via repo root `Path(__file__).parents[3]`, not cwd).
- **Wrong**: Strip unknown `ai_content_declared` in Pydantic models.
- **Correct**: Keep field on OpenAPI + generated + frontend `review.ts`.

---

## Scenario: Auth Redis + multi-instance cooldown

### 1. Scope / Trigger

- `backend/api/auth.py` token store; Redis URI; risk_gates DB KV sharing.

### 2. Signatures

```python
def get_token_backend() -> TokenBackend:  # "redis" | "memory"
def generate_token(...) -> TokenData: ...
def validate_token(token: str) -> TokenData | None: ...
```

### 3. Contracts

| Key | Behavior |
|-----|----------|
| `REDIS_URI` / settings `redis_uri` | If reachable → Redis + TTL; else memory |
| Log | `auth token store backend=redis\|memory` |
| Cooldown | Shared via `db/risk_gates` KV across processes |

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| Redis connect fail | Fall back to memory; log backend=memory |
| Token expired | Validate returns None; Redis TTL enforces |

### 5–7

- Tests: `tests/unit/api/test_auth_token_store.py` (mock Redis OK);
  `tests/unit/services/test_risk_gate_multi_instance.py`.
- **Wrong**: Assume process-local `_active_tokens` only in production.
- **Correct**: Prefer Redis; document fallback in `docs/security.md`.

---

## Common Mistakes

### Mistake: Docs anchors after editing `app.py` / `xhs_risk_gate.py`

**Symptom**: `test_docs_anchors` fails.  
**Fix**: Update `docs/execution-plane.md` `file:line` tokens to the new lines.

### Mistake: Client tests expect unmasked nicknames

**Symptom**: `assert user_name == "User"` fails with `U**r`.  
**Fix**: Assert masked form from `mask_nickname`.
