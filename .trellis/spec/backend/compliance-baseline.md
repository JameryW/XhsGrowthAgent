# Compliance Baseline (P0 Account Safety)

Executable contracts for platform-rule / account-safety gates landed in
PR #657 (`10-15-compliance-risk-baseline`). Future changes to publish
automation, engagement DMs, fake-sign HTTP, or content compliance MUST
keep these invariants.

## Scenario: Dual-auto publish hard reject

### 1. Scope / Trigger

- Changing `AUTO_APPROVE_LOW_RISK`, `auto_publish`, review_gate auto-pass,
  publish_gate skip, CLI `xhs-growth run`, or `POST /start`.

### 2. Signatures

```python
# backend/services/compliance_policy.py
class DualAutoPublishError(ValueError):
    error_code = "dual_auto_publish_forbidden"

def assert_not_dual_auto(*, auto_publish: bool) -> None: ...
def auto_approve_low_risk_enabled() -> bool: ...
def state_is_commercial(state: dict | None) -> bool: ...
def state_is_blocking(state: dict | None) -> bool: ...
def is_high_risk_niche(niche: str | None) -> bool: ...
def commercial_disclosure_ok(state: dict | None) -> bool: ...
```

Call sites that MUST share `assert_not_dual_auto`:

- `backend/api/routes/_wf_application.start_workflow`
- `backend/cli/main.py` run path

### 3. Contracts

| Key / field | Type | Notes |
|-------------|------|--------|
| `AUTO_APPROVE_LOW_RISK` | env bool | Default off |
| `auto_publish` | bool on start / review | OR-ed from workflow + publish_options |
| `is_commercial` | bool on state + `/status` | Brief mode ⇒ true via `mode_spec` |
| `disclosure_confirmed` | bool on PublishOptions / confirmation | Required when commercial |
| `publish_confirmation.confirmer` | str | Receipt |
| `publish_confirmation.source` | `human` \| `auto_publish` \| `dry_run` | Receipt |
| `publish_confirmation.confirmed_at` | ISO timestamp | Receipt |
| `evaluation_result.lexicon_scan` | object | Deterministic scan before LLM |

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| `AUTO_APPROVE_LOW_RISK` ∧ `auto_publish` | Raise `DualAutoPublishError` (`dual_auto_publish_forbidden`); API 4xx / CLI abort |
| `state_is_blocking` / `state_is_commercial` / high-risk niche | Never `auto_low_risk` in review_gate |
| Commercial ∧ ¬`disclosure_confirmed` | Publish gate refuses |
| Commercial ∧ no disclosure markers in title/body | `commercial_disclosure_ok` false → blocking |
| Lexicon hit | `is_blocking=true` before LLM evaluator |

### 5. Good / Base / Bad Cases

- **Good**: Human review + human publish confirm; receipt has confirmer/source/time.
- **Base**: Only one of auto-approve / auto-publish enabled; low-risk non-commercial may auto-approve.
- **Bad**: Both autos on at start → hard reject. Commercial dry-run without `disclosure_confirmed` → fail closed.

### 6. Tests Required

- `tests/unit/agents/nodes/test_dual_auto_and_commercial.py` — dual reject + never-auto matrix
- `tests/unit/services/test_compliance_policy.py` — helpers
- `tests/integration/test_publish_gate_flow.py` — receipt fields
- `tests/unit/api/test_workflow_layering.py` — `/status` shape includes `is_commercial: bool`

### 7. Wrong vs Correct

#### Wrong

```python
# Separate CLI vs API dual-auto rules, or silent skip of publish_gate
if state.get("auto_publish"):
    return  # no human, no assert_not_dual_auto
```

#### Correct

```python
from backend.services.compliance_policy import assert_not_dual_auto
assert_not_dual_auto(auto_publish=req.auto_publish)
```

---

## Scenario: Fake signature removal & stealth default-off

### 1. Scope / Trigger

- Editing `xhs_signature.py`, `xhs_client._request`, `xhs_login._apply_stealth`,
  `pyproject.toml` browser extras, or CI gate `scripts/gates/stealth_default_off.py`.

### 2. Signatures

```python
# Cookie parsing only — NO XHSSignature / generate_x_s
class XHSCookieParser: ...

class XHSSignatureUnavailableError(RuntimeError):
    error_code = "signature_unavailable"
```

### 3. Contracts

| Key | Default | Meaning |
|-----|---------|---------|
| `XHS_BROWSER_STEALTH` | unset/off | Stealth inject only when `1`/`true`/`yes` |
| Main deps | no `fake-useragent` | Optional browser extra may keep playwright-stealth for explicit opt-in |

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| HTTP path that previously fake-signed | Raise `signature_unavailable` — never empty success |
| Default login / CI | No `_apply_stealth` call unless env opt-in |
| CI job Compliance Baseline Gate | Runs `scripts/gates/stealth_default_off.py` |

### 5. Good / Base / Bad

- **Good**: Browser/CDP reads after user login.
- **Base**: Cookie parser still used by credentials.
- **Bad**: Re-adding MD5 `XHS_WEB` sign or default stealth injection.

### 6. Tests

- `tests/unit/services/test_xhs_signature.py` — cookie-only
- `tests/unit/services/test_stealth_default_off.py`
- `scripts/gates/stealth_default_off.py` in CI

### 7. Wrong vs Correct

#### Wrong

```python
headers = XHSSignature.add_sign_to_headers(params, headers)
return []  # swallow failure
```

#### Correct

```python
raise XHSSignatureUnavailableError(...)  # error_code=signature_unavailable
```

---

## Scenario: Engagement quotas & inbound-only DM

### 1. Scope / Trigger

- Changing `send_dm`, `xhs_risk_gate` engagement pause/quotas, Settings risk-gates UI.

### 2. Signatures (conceptual)

```python
# backend/services/xhs_risk_gate.py
def get_engagement_pause_status(account_id: str) -> dict: ...
# Daily caps via env (account-level API optional / P1):
# XHS_DM_DAILY_LIMIT (default 20), XHS_COMMENT_REPLY_DAILY_LIMIT (default 50)
# Risk pause default ~6h after _RISK_MARKERS
```

### 3. Contracts

| Rule | Behavior |
|------|----------|
| Inbound whitelist | `send_dm` allowed only if target in unread/inbound peer cache |
| Cold DM | Blocked unless explicit outbound flag + per-message human confirm |
| Risk markers | Pause engagement; expose via `GET /api/system/risk-gates` → `engagement_pause` |
| Frontend tests | Must mock `getRiskGates` — panel fetches on mount |

### 4. Validation & Error Matrix

| Condition | Error / result |
|-----------|----------------|
| Over daily DM/comment cap | Explicit error code; no send |
| Target not inbound | Reject cold start |
| Risk pause active | Blocked; Settings shows reason + remaining |

### 5–7. Cases / Tests / Wrong-Correct

- Tests: `tests/unit/services/test_engagement_quotas.py`,
  `frontend/tests/components/XhsAccountsPanel.spec.ts` (mock `getRiskGates`).
- **Wrong**: Unmocked Settings panel fetch → toast.error in vitest.
- **Correct**: `vi.mock('@/api/system', … getRiskGates: vi.fn().mockResolvedValue(…))`.

---

## Scenario: Deterministic lexicon before LLM

### 1. Scope / Trigger

- Evaluator node, `backend/config/compliance/*.yaml`, Review highlight chips.

### 2. Signatures

```python
# backend/services/compliance/lexicon.py
def scan_text(text: str, *, niche: str = "") -> LexiconScanResult: ...
def scan_state_content(state: dict) -> LexiconScanResult: ...
```

Niche overlays: `医疗/保健/药品` → `niche_medical.yaml`; `金融/投资` → `niche_finance.yaml`.

### 3. Contracts

- Scan runs **before** LLM judge; results in `evaluation_result.lexicon_scan`
  (`is_blocking`, `hits`, `highlight_terms`, `lexicons_loaded`).
- Corpus: `tests/fixtures/compliance/lexicon_corpus.json` (≥50 positive / ≥50 negative).

### 4–7

- Hit ⇒ blocking regardless of LLM score.
- Extend niches by adding YAML + `_NICHE_OVERLAYS` map — do not hardcode terms in the evaluator prompt alone.
- Tests: `tests/unit/services/compliance/test_lexicon.py`.

---

## Common Mistakes

### Mistake: Strip `disclosure_confirmed` in Pydantic

**Symptom**: Commercial dry-run always fails closed even when Review checkbox is set.  
**Cause**: `PublishOptions` missing the field → Pydantic drops unknown keys.  
**Fix**: Keep field on API model, OpenAPI, generated models, and frontend `review.ts`.

### Mistake: Stale `docs/execution-plane.md` line anchors

**Symptom**: `test_docs_anchors` fails after editing `xhs_risk_gate.py`.  
**Fix**: Update the `file:line` token in the anchor table to the new line of `_persist_task = loop.create_task(_run())`.

### Mistake: Read `workflow_mode` with bare `state.get`

**Symptom**: Registry / mode invariant tests fail.  
**Fix**: Use `mode_spec(state)` (as `state_is_commercial` does).
