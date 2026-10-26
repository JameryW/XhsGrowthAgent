# Compliance Baseline (P0 Account Safety)

Executable contracts for platform-rule / account-safety gates landed in
PR #657 (`10-15-compliance-risk-baseline`). Future changes to publish
automation, engagement DMs, fake-sign HTTP, or content compliance MUST
keep these invariants.

P1 extensions (health panel, scrape budget, privacy, AI declaration, Redis
auth) live in [Compliance P1](./compliance-p1.md) (PR #659).

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

## Scenario: Fake signature removal & stealth hard-delete

### 1. Scope / Trigger

- Editing `xhs_signature.py`, `xhs_client._request`, `xhs_login` launch args,
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
| `playwright-stealth` / `fake-useragent` | absent | Not in main or `[browser]` extras |
| `XHS_BROWSER_STEALTH` / `_apply_stealth` | absent | Hard-deleted — no opt-in path |
| AutomationControlled / webdriver hide | absent | No fingerprint camouflage args/scripts |

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| HTTP path that previously fake-signed | Raise `signature_unavailable` — never empty success |
| Login launch / CI | No stealth helpers, no camouflage init scripts |
| CI job Compliance Baseline Gate | Runs `scripts/gates/stealth_default_off.py` (absence check) |

### 5. Good / Base / Bad

- **Good**: Browser/CDP reads after user login on a real headed profile.
- **Base**: Cookie parser still used by credentials.
- **Bad**: Re-adding MD5 `XHS_WEB` sign, stealth deps, or webdriver-hide scripts.

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

## Scenario: Deterministic publish judgers (per failure mode)

### 1. Scope / Trigger

- Changing publish routing (`evaluator_outcome` / `evaluator_requires_human`),
  `evaluation_result.publish_eligibility`,
  `backend/services/compliance/judgers.py`,
  `backend/services/compliance/projection.py`, or
  creator-agent Action plan/execute (`policy.py` / `advisor._execute_publish`).

### 2. Signatures

```python
# backend/services/compliance/judgers.py
class JudgerId(StrEnum): ...  # lexicon | commercial_disclosure | ...
def decide_publish_eligibility(state, *, thresholds=None) -> PublishEligibility: ...

# backend/services/compliance/projection.py — thin Action/artifact → state mapping
def project_action_plan_state(...) -> dict: ...
def project_artifact_body_for_judgers(...) -> dict: ...

# Plan-time subset (no body) — same decide_publish_eligibility, judgers=
PLAN_TIME_JUDGERS  # dual_auto | high_risk_auto

# backend/creator_agent/policy.py
PolicyId.PUBLISH_ELIGIBILITY_DENIED = "policy.action.publish_eligibility_denied"
PolicyId.ELIGIBILITY_CONTEXT_UNAVAILABLE = "policy.action.eligibility_context_unavailable"

# backend/creator_agent/policy_context.py — plan auto-load (no artifact)
async def load_action_policy_context_from_thread(thread_id, account_id="", *, graph) -> ActionPolicyContext: ...
```

### 3. Contracts

| Field | Meaning |
|-------|---------|
| `evaluation_result.publish_eligibility` | Audited conjunction of per-mode verdicts |
| `publish_eligibility.allowed` | Sole machine authority for "may proceed toward publish" |
| LLM `decision` / overall_score | UI scores/hints only — must not alone grant publish **or** auto-enter `revise_content` (heavy residual) |
| Thresholds | Env `XHS_JUDGER_*_BLOCKING` (default True) — business-cost knobs |
| Action **plan** | Auto-loads stamped eligibility from thread checkpoint when `thread_id` is set (`load_action_policy_context_from_thread`); explicit `policy_context=` overrides; + account-level judgers (`PLAN_TIME_JUDGERS`); **no** artifact read; deny → no intent |
| Action **execute** | After hash match, before Gateway: full judgers on artifact body; deny → no receipt |

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| Any blocking judger fails + quality `approved` | Fail-closed human channel (`__end__` / pause) |
| Quality `needs_revision` / `rejected` (any revision count, including cap) | Fail-closed human channel — **no** auto `revise_content`, **no** force-publish |
| All judgers pass + quality approved | Route to `publish_gate` |
| `POST /resume` `human_decision=revise` | Stamp `human_revision_requested` + fresh budget → one-shot `revise_content` |
| `POST /resume` `human_decision=approve` | Patch approved → continue toward publish (eligibility still enforced on next pass / gate) |
| Action plan: stamped `allowed=False` / dual_auto | `ActionPolicyDeniedError` (`policy.action.publish_eligibility_denied`); no intent |
| Action plan: checkpoint/graph unreadable | `ActionPolicyDeniedError` (`policy.action.eligibility_context_unavailable`); no intent |
| Action plan: stamp missing | Continue (eligibility stamp check allows); execute still judges body |
| Action execute: lexicon/disclosure hit on body | `ActionPublishEligibilityDeniedError` before Gateway; no receipt |

### 5–7. Cases / Tests / Wrong-Correct

- Tests: `tests/unit/services/compliance/test_judgers.py`, router suites under
  `tests/unit/graph/test_routers.py` / `tests/integration/test_evaluator_gate.py`,
  Action plan/execute deny suites under `tests/unit/creator_agent/`
  (incl. `test_policy_context_loader.py` for stamp auto-load).
- **Wrong**: `if evaluation["decision"] == "approved": return "publisher"` without
  consulting `publish_eligibility`.
- **Wrong**: Auto-routing LLM `needs_revision`/`rejected` to `revise_content`, or
  force-publishing quality reject at `max_revision_count`.
- **Wrong**: Action execute calling Tool Gateway before `decide_publish_eligibility`.
- **Wrong**: Action plan calling full `decide_publish_eligibility` on an empty body
  with `is_commercial=True` — disclosure judger false-denies before any artifact
  exists. Use `judgers=PLAN_TIME_JUDGERS` only at plan.
- **Wrong**: Relying on callers to inject stamped eligibility at plan — production
  must auto-load from the thread checkpoint (explicit `policy_context=` is
  override-only).
- **Correct**: eligibility audit first; LLM quality reject → human channel;
  only `/resume` revise enters `revise_content`.
- **Correct**: Action plan + execute + workflow share one `decide_publish_eligibility`.
- **Correct**: Plan = checkpoint stamp auto-load + `PLAN_TIME_JUDGERS`; execute =
  full conjunction after hash match.
- **Wrong**: Creator-agent API unit tests that call `POST /actions` publish without
  mocking `graph.aget_state` — production wires `thread_policy_context_loader`,
  so a missing/unreadable graph fail-closes as `eligibility_context_unavailable`.
- **Correct**: Mock a readable empty checkpoint (no stamp) when the test is not
  asserting load failure.

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

Niche overlays: `医疗/保健/药品` → `niche_medical.yaml`; `医美` → `niche_aesthetic.yaml`;
`金融/投资` → `niche_finance.yaml`. High-risk set also includes `医美` (see
[Compliance P2](./compliance-p2.md)).

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
