# LLM Mock Blogger Candidates Fallback

## Goal

When XHS_COOKIE is not configured (dry-run mode), `blogger_scout` currently returns empty `blogger_candidates`, causing the UI to show "未找到候选博主" and blocking the blogger_gate selection flow. Add an LLM-based fallback that generates mock blogger candidates from trend_data/content_plan context, so the workflow can proceed meaningfully even without real platform access.

## What I already know

* `BloggerScoutAgent` (backend/agents/blogger_scout.py) returns `[]` when no XHS cookie or no XHS client
* It inherits `BaseAgent` which has `self.model` (LLM via `get_model(task_type)`) and `self.prompt_template`
* `task_type = TaskType.SCOUTING` routes to `deepseek-chat` per models/router.py
* The agent already extracts keywords from state via `_extract_keywords()`
* Trend_data and content_plan are already populated by earlier workflow phases
* The blogger_gate node reads `blogger_candidates` from state and renders selection UI
* Frontend BloggerSelection component handles "noCandidates" state with skip option

## Assumptions (temporary)

* Mock bloggers should have realistic but clearly fake user_ids (prefix `mock_`)
* LLM generates candidates based on existing trend_data keywords + niche
* Mock data quality is sufficient for dry-run testing and UI flow validation

## Open Questions

1. Should mock bloggers persist across workflow runs, or regenerate each time? (Preference — likely regenerate is fine for MVP)

## Requirements

* When XHS cookie is missing, blogger_scout falls back to LLM-generated candidates instead of returning `[]`
* LLM receives keywords + niche + trend_data summary as context
* Generated candidates follow the same schema as real candidates (user_id, nickname, follower_count, note_count, total_engagement, top_note_title)
* Mock user_ids are prefixed with `mock_` to distinguish from real data
* The fallback path logs a warning that mock data is being used
* Real XHS cookie path remains unchanged (priority over mock when available)

## Acceptance Criteria

* [ ] Without XHS_COOKIE, workflow completes blogger_scout with non-empty candidates
* [ ] Mock candidates contain realistic niche-appropriate nicknames and note titles
* [ ] Frontend blogger selection UI shows mock candidates correctly
* [ ] With XHS_COOKIE configured, real platform search still takes priority
* [ ] Unit test covers both paths (XHS available vs fallback)
* [ ] Mock candidates are clearly distinguishable from real ones (mock_ prefix)

## Definition of Done

* Unit tests added/updated
* Lint / typecheck green
* Frontend handles mock candidates the same as real ones
* Deployed and verified on dry-run workflow

## Out of Scope

* Persistence of mock bloggers across sessions
* Real third-party data sources (微博/抖音 APIs)
* Advanced mock quality (avatar URLs, real engagement distributions)

## Technical Notes

* Key files: backend/agents/blogger_scout.py, backend/config/prompts/blogger_scout.yaml
* BaseAgent._parse_json_response() handles JSON extraction from LLM output
* TaskType.SCOUTING → deepseek-chat model (cost-effective for mock generation)