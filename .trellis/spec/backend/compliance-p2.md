# Compliance P2 (Growth Cleanup)

Executable contracts from `10-16-compliance-p2-growth-cleanup`. Extends
[Compliance Baseline (P0)](./compliance-baseline.md) and
[Compliance P1](./compliance-p1.md); do not regress those invariants.

## Scenario: Learning recommendations on Start (P2-1)

### 1. Scope / Trigger

- Start Creating (`/start`), analytics learning-recommendations route,
  outcome-learning / creator_note_stats consumers.

### 2. Signatures

```python
# backend/services/learning_recommendations.py
DEFAULT_RECOMMENDATION_LIMIT = 5
def build_topic_recommendations(notes, *, account_id="", limit=5) -> dict: ...
async def get_learning_recommendations(account_id, *, limit=5) -> dict: ...
```

API: `GET /api/analytics/creator-stats/{account_id}/learning-recommendations?limit=5`

### 3. Contracts

| Field | Notes |
|-------|--------|
| `recommendations[]` | From imported notes with real engagement only |
| `empty` / `empty_reason` | Explicit when insufficient samples — never invent topics |
| `evidence_href` / `evidence_doc` | Trace to Analytics + `docs/outcome-learning.md` |
| `limit` default | **N=5** |

### 4. Validation & Error Matrix

| Condition | Behavior |
|-----------|----------|
| No performing notes | `empty=true`, `recommendations=[]` |
| Performing notes exist | Rank by engagement_rate; topic from tag or title |
| Topic without title/tags | Note skipped (not fabricated) |

### 5–7

- Tests: `tests/unit/services/test_learning_recommendations.py`
- **Wrong**: Fabricate trending topics when cold-start.
- **Correct**: Empty state + sync Creator Center first.

---

## Scenario: Niche compliance tiers (P2-2)

### 1. Scope / Trigger

- `HIGH_RISK_NICHES`, lexicon `_NICHE_OVERLAYS`, Start niche chips, Settings.

### 2. Signatures

```python
# backend/services/compliance_policy.py
HIGH_RISK_NICHES  # includes 医美
NICHE_QUALIFICATION_HINTS: dict[str, str]
def get_niche_compliance_tier(niche: str | None) -> dict: ...
def niche_qualification_hint(niche: str | None) -> str | None: ...
```

API: `GET /api/system/niche-compliance?niche=`

Lexicon: `医美` → `niche_aesthetic.yaml`

### 3. Contracts

| Niche | Overlay | Qualification hint |
|-------|---------|-------------------|
| 医疗/保健/药品 | niche_medical.yaml | required |
| 医美 | niche_aesthetic.yaml | required |
| 金融/投资 | niche_finance.yaml | required |

UI: selecting high-risk niche on Start shows stricter-lexicon + qualification notice.

### 4–7

- Tests: `tests/unit/services/test_niche_compliance_tier.py`
- review_gate must use `is_high_risk_niche` / shared `HIGH_RISK_NICHES` (no local duplicate set).
- **Wrong**: Hardcode high-risk only in the evaluator prompt.
- **Correct**: Extend YAML + `HIGH_RISK_NICHES` + `_NICHE_OVERLAYS` together.

---

## Scenario: Acceptance signoff board (P2-3)

### 1. Scope / Trigger

- `docs/acceptance/signoff-board.json`, signoff-request markdown, Settings Acceptance tab.
- Chase checklist: `docs/acceptance/signoff-chase-checklist.md`.

### 2. Signatures

```python
# backend/services/acceptance_signoff.py
def load_signoff_board(*, path=None) -> dict: ...
def is_gate_passed(status: str | None) -> bool: ...
def is_gate_waived(status: str | None) -> bool: ...
```

API: `GET /api/system/acceptance-signoff` (read-only)

### 3. Contracts

| Field | Notes |
|-------|--------|
| `gates[]` | G1–G5 required; G6+ listed when present |
| `status` / `owner_role` / `conclusion` | Placeholders allowed |
| `status=waived_risk_accepted` | Risk acceptance (2026-09-22 waiver) — **not** a pass; UI must not use success/passed styling |
| `next_review_at` / `chase_action` | Per-gate chase tracking; default review ~90 days from board update |
| `waiver.next_global_review_at` | Top-level re-review date; `replaces_signoff` always false |
| `replaces_human_signoff` | Always `false` |
| `disclaimer` | Explicit: does not replace warehouse-external signoff; waiver ≠ pass; CI green ≠ signoff |

### 4–7

- Tests: `tests/unit/services/test_acceptance_signoff.py`
- **Wrong**: Mark gate passed because CI is green; display `waived_risk_accepted` as passed/success.
- **Correct**: Mirror docs status only; empty conclusion until human signs; waived stays waived with `next_review_at`.

---

## Scenario: Cleanup (P2-4)

- Remove duplicate high-risk niche tuples; keep P0/P1 defaults.
- No reintroduction of `fake-useragent` / `XHSSignature` / default stealth.

---

## Common Mistakes

### Mistake: Invent recommendations on cold start

**Symptom**: Start shows “hot topics” with no imported notes.  
**Fix**: Return `empty=true` until performing samples exist.

### Mistake: Add 医美 only to UI chips

**Symptom**: UI warns but lexicon/auto-approve still treat 医美 as standard.  
**Fix**: Update `HIGH_RISK_NICHES`, overlay YAML (`NICHE_OVERLAYS`), and qualification hints together.

### Mistake: Unmocked `getNicheCompliance` in Start form vitest

**Symptom**: `ECONNREFUSED :3000` noise (or flakes) when mounting `WorkflowStartForm`.  
**Fix**: `vi.mock('@/api/system', () => ({ getNicheCompliance: vi.fn().mockResolvedValue(...) }))`
  — same discipline as P1 `getRiskGates` on Settings.
