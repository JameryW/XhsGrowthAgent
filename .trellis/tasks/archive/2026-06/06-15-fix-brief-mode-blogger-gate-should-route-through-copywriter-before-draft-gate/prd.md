# fix: brief-mode blogger_gate should route through copywriter + optimization before draft_gate

## Goal

In brief mode, after blogger_gate selects a blogger, the workflow should route through `copywriter` to generate AI copy, then through the optimization pipeline (`content_analyzer → version_generator → choice_gate`) to produce multiple versions for user selection — instead of going directly to `draft_gate` where the user must write from scratch.

## What I already know

* **Current brief path**: `orchestrator → brief_analyzer → brief_gate → viral_matcher → blogger_scout → blogger_gate → draft_gate`
* **Problem**: `blogger_gate_router` always returns `"draft_gate"`, bypassing `copywriter` and the entire optimization pipeline
* **`draft_gate_node` fallback** (line 84-96 of draft_gate.py): when no `copy_content`, it uses first `blogger_notes[0].body` as default — low quality, not AI-generated
* **`CopywriterAgent.execute`** reads `content_plan` from state — but brief mode also skips `content_strategist`, so `content_plan` is `{}`
* **Trend mode optimization path** (after copywriter): `copywriter → draft_gate → viral_matcher → blogger_scout → blogger_gate → draft_gate → shooting_planner → content_analyzer → version_generator → choice_gate`
* **Brief mode already has optimization path**: `shooting_planner → content_analyzer → version_generator → choice_gate` (via `shooting_planner_router`)
* **`draft_gate_router`** already routes brief mode to `shooting_planner` (skipping viral_matcher/blogger loop)

## Root cause (two layers)

1. **Routing**: `blogger_gate_router` unconditionally routes to `draft_gate` — should route to `copywriter` in brief mode
2. **Missing content_plan**: Even if we route to `copywriter`, it needs `content_plan` which brief mode doesn't have (brief_analyzer produces `brief_content` + `shooting_plan`, not `content_plan`)

## Requirements

* `blogger_gate_router` must route to `copywriter` in brief mode
* `CopywriterAgent` must work without `content_plan` when `brief_content` is available — use `brief_content` as the planning context
* Graph topology must add `blogger_gate → copywriter` edge
* After copywriter, brief mode follows the standard path: `copywriter → draft_gate` (user reviews AI draft) → `draft_gate_router` → `shooting_planner` → `content_analyzer → version_generator → choice_gate` (optimization + multi-version selection)

## Target brief-mode flow

```
blogger_gate → copywriter → draft_gate → shooting_planner → content_analyzer → version_generator → choice_gate
```

User sees: AI-generated copy in draft_gate (edit if needed), then multiple optimized versions in choice_gate.

## Acceptance Criteria

* [ ] Brief mode: `blogger_gate → copywriter → draft_gate` (AI generates initial copy)
* [ ] After draft_gate, brief mode continues to `shooting_planner → content_analyzer → version_generator → choice_gate` (optimization + multi-version)
* [ ] Trend mode: `blogger_gate → draft_gate` unchanged (user writes draft manually)
* [ ] `CopywriterAgent.execute` works when `content_plan` is empty but `brief_content` is present
* [ ] Existing tests pass
* [ ] `npm -C frontend run type-check` passes

## Definition of Done

* Tests added/updated for the new routing path
* Lint / typecheck green
* Deploy and verify with a new brief workflow

## Technical Approach

### 1. Update `blogger_gate_router` (backend/graph/routers.py)

In brief mode, route to `copywriter` instead of `draft_gate`:

```python
def blogger_gate_router(state) -> Literal["copywriter", "draft_gate", "visual_designer"]:
    if _check_terminal(state):
        return "visual_designer"
    mode = state.get("workflow_mode", "trend")
    if mode == "brief":
        return "copywriter"
    return "draft_gate"
```

### 2. Add graph edge `blogger_gate → copywriter` (backend/graph/builder.py)

Update the `blogger_gate` conditional edges mapping to include `"copywriter": "copywriter"`.

### 3. Update `CopywriterAgent.execute` (backend/agents/copywriter.py)

When `content_plan` is empty but `brief_content` is present, build the user message from `brief_content` + `selected_blogger` + `blogger_notes` instead of `content_plan` fields. The existing `copywriter_router` → `draft_gate` → `draft_gate_router` → `shooting_planner` chain handles the rest automatically.

### 4. No changes to `copywriter_router` or `draft_gate_router`

The existing routing chain already works:
- `copywriter_router` → `draft_gate` (user reviews AI draft)
- `draft_gate_router` → `shooting_planner` (brief mode / selected_blogger present)
- `shooting_planner_router` → `content_analyzer` → `version_generator` → `choice_gate`

## Decision (ADR-lite)

**Context**: Brief mode workflow reaches draft_gate without AI-generated copy, forcing users to write from scratch. Even after draft, there's no optimization/multi-version generation.
**Decision**: Route blogger_gate → copywriter in brief mode, then follow the existing optimization pipeline through shooting_planner → content_analyzer → version_generator → choice_gate.
**Consequences**: Brief mode gets AI-generated copy + optimization + multi-version selection. Trend mode behavior unchanged.

## Out of Scope

* Changing the trend mode blogger_gate → draft_gate path
* Making copywriter generate `content_plan` (that's content_strategist's job)
* Modifying the draft_gate_node fallback logic (no longer hit for brief mode)

## Technical Notes

* Key files: `backend/graph/routers.py`, `backend/graph/builder.py`, `backend/agents/copywriter.py`
* `CopywriterAgent` inherits from `BaseAgent` which provides `_build_system_prompt(state)` — the system prompt already has brief-aware context via the prompt YAML
* `blogger_notes` and `selected_blogger` are available in state when entering from blogger_gate
* The optimization pipeline (`content_analyzer → version_generator → choice_gate`) is already wired and works for both modes
