# Research: Empty Potential Score in UI

- **Query**: Why is "潜力分" (potential score) empty/blank in the UI while heat score shows 92?
- **Scope**: internal
- **Date**: 2026-06-01

## Findings

### Root Cause

**The LLM prompt schema and the frontend type definition have a field name mismatch.**

The prompt in `trend_scout.yaml` asks the LLM to return `potential` (a string description), but the frontend expects `potential_score` (a numeric score 0-100).

### Files Found

| File Path | Description |
|---|---|
| `backend/config/prompts/trend_scout.yaml:22` | LLM prompt schema - uses `potential` field |
| `backend/state/substates.py:21` | NicheOpportunity TypedDict - defines `potential_score: float` |
| `backend/api/generated/models.py:311` | API model - defines `potential_score: conint(ge=0, le=100)` |
| `frontend/src/types/workflow.ts:116` | TypeScript interface - expects `potential_score: number` |
| `frontend/src/components/dashboard/ContentCards.vue:158` | UI display - reads `opp.potential_score` |

### Code Patterns

**1. Prompt Schema (backend/config/prompts/trend_scout.yaml:22)**

```yaml
"niche_opportunities": [{"topic": "...", "competition": "low/medium/high", "potential": "..."}],
```

The prompt asks for:
- `topic` (string)
- `competition` (string: low/medium/high)
- `potential` (string description)

**2. Frontend Type (frontend/src/types/workflow.ts:114-119)**

```typescript
interface NicheOpportunity {
  topic: string
  potential_score: number  // <-- expects numeric score
  audience_match: string
  entry_barrier: EntryBarrier
}
```

**3. Backend State Type (backend/state/substates.py:17-23)**

```python
class NicheOpportunity(TypedDict, total=False):
    topic: str
    potential_score: float  # <-- expects numeric score
    audience_match: str
    entry_barrier: str
```

**4. UI Display (frontend/src/components/dashboard/ContentCards.vue:158)**

```vue
<span class="text-violet-600 font-medium">
  {{ t('dashboard.scouting.potentialScore') }} {{ opp.potential_score?.toFixed(0) || '—' }}
</span>
```

### The Mismatch

| Layer | Field Name | Type |
|-------|------------|------|
| LLM Prompt | `potential` | string (description) |
| Backend State | `potential_score` | float (0-100) |
| API Model | `potential_score` | int (0-100) |
| Frontend Type | `potential_score` | number |
| UI Display | `opp.potential_score` | number |

The LLM returns `{"potential": "high growth opportunity"}` but the frontend looks for `potential_score` which doesn't exist, so it shows the fallback `—`.

### Additional Mismatches

The prompt also has:
- `competition` (string) vs `entry_barrier` (string) - different field names
- Missing `audience_match` field entirely in prompt

### Related Specs

None found.

## Caveats / Not Found

1. The `_parse_json_response` method in `backend/agents/base.py:86` does not perform any field mapping or normalization - it just parses the JSON as-is.

2. The `topic_scorer` tool in `backend/tools/analysis/topic_scorer.py` returns `heat_score` but does not generate `niche_opportunities` with `potential_score`.

3. No validation or transformation layer exists between the LLM response and the state update.

## Recommended Fix

Update `backend/config/prompts/trend_scout.yaml:22` to match the expected schema:

```yaml
"niche_opportunities": [
  {
    "topic": "...",
    "potential_score": 0-100,
    "audience_match": "...",
    "entry_barrier": "low/medium/high"
  }
],
```

This ensures the LLM returns data in the exact format the frontend expects.
