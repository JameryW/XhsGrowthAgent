# Research: topic_scorer NaN% Display Issue

- **Query**: Investigate why topic_scorer shows "热度分 92, NaN%" in the UI
- **Scope**: internal
- **Date**: 2026-06-01

## Findings

### Root Cause Analysis

The NaN% appears because **`topic_scorer` does NOT return `growth_rate`**, but the frontend expects it in `HotTopicItem`.

### Data Pipeline Trace

#### 1. Backend: `topic_scorer` Return Structure

**File**: `/test/xhs/backend/tools/analysis/topic_scorer.py:141-163`

```python
return {
    "topic": topic,
    "heat_score": round(final_score, 1),
    "score_breakdown": {...},
    "data_metrics": {...},
    "growth_trend": growth_trend,        # <-- String like "爆发期", "上升期"
    "competition_level": competition_level,
    "recommendation": recommendation,
    "suggested_action": action,
    "related_keywords": keywords[:5] if keywords else [f"#{topic}"],
    "best_posting_window": best_posting_window,
    "reference_posts": reference_posts,
}
```

**Key observation**: `topic_scorer` returns `growth_trend` (a string), NOT `growth_rate` (a number).

#### 2. Backend: Expected `HotTopicItem` Schema

**File**: `/test/xhs/backend/state/substates.py:8-14`

```python
class HotTopicItem(TypedDict, total=False):
    topic: str
    heat_score: float
    growth_rate: float              # <-- Expected as float (e.g., 0.23 for 23%)
    related_keywords: list[str]
```

**File**: `/test/xhs/backend/api/generated/models.py:279-289`

```python
class HotTopicItem(BaseModel):
    topic: StrictStr
    heat_score: conint(ge=0, le=100, strict=True)
    growth_rate: StrictFloat        # <-- Required field, expected as float
    related_keywords: list[StrictStr]
```

#### 3. Frontend: Display Logic

**File**: `/test/xhs/frontend/src/components/dashboard/ContentCards.vue:133-135`

```vue
<div v-if="topic.growth_rate !== undefined" class="text-xs">
  {{ topic.growth_rate > 0 ? '+' : '' }}{{ (topic.growth_rate * 100).toFixed(0) }}%
</div>
```

The frontend checks `topic.growth_rate !== undefined`, but if `growth_rate` is `NaN` or a non-numeric string, the multiplication `topic.growth_rate * 100` produces `NaN`.

#### 4. LLM Prompt for `trend_scout`

**File**: `/test/xhs/backend/config/prompts/trend_scout.yaml:19`

```yaml
"hot_topics": [{"topic": "...", "heat_score": 0-100, "growth_rate": "...", "related_keywords": [...]}]
```

The prompt shows `growth_rate: "..."` as a placeholder, but doesn't specify the format (string vs float, percentage vs decimal).

### Where NaN is Introduced

The NaN can be introduced at multiple points:

1. **LLM generates string for `growth_rate`**: The LLM might output `"上升"` or `"23%"` instead of `0.23`
2. **Missing `growth_rate` field**: If the LLM omits `growth_rate`, it becomes `undefined` in JS, but `undefined * 100 = NaN`
3. **`xhs_trending` tool returns `growth_rate: 0.0`**: This is valid but shows "0%" not NaN

**Most likely cause**: The LLM generates `growth_rate` as a string (e.g., `"上升期"`) or omits it entirely, and the frontend's `topic.growth_rate * 100` produces NaN.

### Files Found

| File Path | Description |
|---|---|
| `backend/tools/analysis/topic_scorer.py` | Returns `growth_trend` (string), NOT `growth_rate` (float) |
| `backend/state/substates.py:8-14` | `HotTopicItem` expects `growth_rate: float` |
| `backend/api/generated/models.py:279-289` | Pydantic model expects `growth_rate: StrictFloat` |
| `backend/config/prompts/trend_scout.yaml:19` | Prompt placeholder `growth_rate: "..."` is ambiguous |
| `frontend/src/components/dashboard/ContentCards.vue:133-135` | Display logic: `(topic.growth_rate * 100).toFixed(0)` |
| `frontend/src/types/workflow.ts:97-98` | TypeScript interface: `growth_rate: number` |
| `backend/agents/trend_scout.py` | Agent that generates `trend_data` via LLM |
| `backend/tools/xhs/trending.py:49-50` | `xhs_trending` returns `growth_rate` from `XHSTrendingTopic` |
| `backend/services/xhs_client.py:104-105` | `XHSTrendingTopic` has `growth_rate: float = 0.0` |

### Code Patterns

1. **`topic_scorer`** returns a different structure than `HotTopicItem` expects:
   - Has `growth_trend` (string: "爆发期", "上升期", "平稳期", "衰退期")
   - Missing `growth_rate` (float)

2. **`xhs_trending`** returns correct structure with `growth_rate: 0.0` default

3. **Frontend** assumes `growth_rate` is always a number:
   - Check `!== undefined` is insufficient for NaN prevention
   - Should also check `typeof topic.growth_rate === 'number' && !isNaN(topic.growth_rate)`

### External References

None needed - this is an internal data contract issue.

### Related Specs

None found in `.trellis/spec/`.

## Caveats / Not Found

1. **No explicit test for `growth_rate` NaN handling** in the test files searched
2. **The exact LLM output format** for `growth_rate` is not validated anywhere
3. **The `topic_scorer` tool is NOT used by `trend_scout`** - `trend_scout` uses `xhs_trending`, `keyword_monitor`, `competitor_analyzer` instead (see `backend/agents/trend_scout.py:34`)

## Recommended Fix

1. **Backend**: Update `topic_scorer` to return `growth_rate` as a float (0.0-1.0) instead of `growth_trend` string, OR add a `growth_rate` field calculated from the trend data

2. **Backend**: Update `trend_scout` prompt to specify `growth_rate` format: `"growth_rate": 0.23` (decimal, not percentage)

3. **Frontend**: Add NaN guard in `ContentCards.vue`:
   ```vue
   <div v-if="typeof topic.growth_rate === 'number' && !isNaN(topic.growth_rate)" class="text-xs">
     {{ topic.growth_rate > 0 ? '+' : '' }}{{ (topic.growth_rate * 100).toFixed(0) }}%
   </div>
   ```

4. **Backend**: Add validation in `trend_scout.py` to ensure `growth_rate` is a float before returning
