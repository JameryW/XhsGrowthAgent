# Support Brief-Based Workflow Mode

## Goal

Add a second workflow mode — "brief-based" — alongside the existing trend-discovery mode. In brief mode, the user provides a commercial brief (text or document attachment like PDF), and the system generates a shooting plan and copy based on that brief, referencing viral posts from similar-style creators for inspiration.

## What I already know

* Current workflow: START → orchestrator → trend_scout → content_strategist → copywriter → draft_gate → viral_matcher → ... → review_gate → publisher → analyst
* Orchestrator always routes to trend_scout by default (orchestrator_router maps IDLE/SCOUTING → trend_scout)
* State has `execution_mode` (single/continuous) but no "workflow mode" concept
- WorkflowStartRequest has `topic` and `niche` fields but no brief/document support
* ViralMatcherAgent already searches for viral posts by keywords — can be reused for brief-based reference search
* Frontend WorkflowStartForm currently supports: accountId, phase, dryRun, autoPublish, niche, topic
* The shooting plan template is a specific format used by brands for KOL/content creator collaborations

## Assumptions (temporary)

* Brief mode skips trend_scout entirely — the brief IS the input (no need to discover trends)
* Brief mode flow: brief_input → brief_analyzer → viral_matcher (style-based) → shooting_planner → copywriter → visual_designer → Ripple analysis → optimization → END
* Brief mode does NOT go through review_gate, publisher, or analyst — endpoint is "optimization plan"
* The shooting plan format is largely fixed (creator info, content direction, draft requirements, outline with titles/copy/hashtags, outfit suggestions, shooting angles) — LLM fills in the values based on parsed brief content
* Different briefs produce different content within the same structural template
* The "reference viral posts by style" step can reuse/extend ViralMatcherAgent
* Ripple analysis in brief mode works the same as in trend mode (predict spread + PMF validation)
* Optimization in brief mode produces improvement suggestions based on Ripple results

## Open Questions

* (None remaining — all key decisions resolved)

## Requirements (evolving)

* Add `workflow_mode` field to state: "trend" (existing) or "brief" (new)
* Add `brief_content` sub-state to hold parsed brief data (design as single brief now, but structure allows future briefs list)
* Add `shooting_plan` sub-state for the generated shooting plan output
* New `brief_analyzer` agent/node: parses brief text/document into structured data; PDF parsing uses pdfplumber first, falls back to multimodal LLM for scanned documents
* New `shooting_planner` agent/node that generates shooting plan from brief + viral references
* Modify orchestrator_router to route based on workflow_mode (brief → brief_analyzer, trend → trend_scout)
* Modify content_strategist to accept brief data as input (in addition to trend data)
* Extend viral_matcher to search by style/category from brief (not just keywords)
* Brief mode flow: brief_input → brief_analyzer → viral_matcher (style-based) → shooting_planner → copywriter → visual_designer → Ripple analysis → optimization → END
* Brief mode does NOT go through review_gate, publisher, or analyst
* Vague brief handling: LLM infers missing fields, then presents choices/supplement prompts to user via interrupt mechanism (similar to draft_gate/choice_gate pattern)
* Shooting plan and final content export: support copy-to-clipboard and PDF download
* Frontend: add mode selector to WorkflowStartForm on Home page
* Frontend: when brief mode selected, show text area + file upload in the same form
* Frontend: add shooting plan display component with export buttons
* Frontend: add brief clarification UI (when LLM flags ambiguous fields, show choices for user)
* CLI: add `--mode brief` option and `--brief-file` option
* API: extend WorkflowStartRequest with mode, brief_text, brief_file fields
* API: add brief upload endpoint for file handling

## Acceptance Criteria (evolving)

* [ ] User can select "brief mode" from the frontend start form
* [ ] User can input brief as text or upload a PDF document
* [ ] Brief is parsed into structured data (product name, selling points, required keywords, etc.)
* [ ] System generates shooting plan with LLM-adaptive format based on parsed brief content
* [ ] Shooting plan includes: creator info, content direction, draft images, outline with titles/copy/hashtags, outfit suggestions, shooting angles
* [ ] Viral post references are found based on brief's style/category
* [ ] Copy and visual design are generated based on shooting plan
* [ ] Ripple analysis runs on the generated content
* [ ] Optimization suggestions are produced based on Ripple results
* [ ] Existing trend-based workflow continues to work unchanged

## Definition of Done

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes
* Both workflow modes tested end-to-end

## Out of Scope (explicit)

* Batch brief processing (single brief only in MVP, but state design预留列表结构)
* Brief version history / comparison

## Technical Notes

* Key files: backend/graph/builder.py, backend/state/schema.py, backend/graph/routers.py, backend/agents/orchestrator.py, backend/api/routes/workflow.py, frontend/src/stores/workflow.ts, frontend/src/views/Home.vue
* Existing ViralMatcherAgent (backend/agents/viral_matcher.py) can be extended for style-based search
* PDF parsing: need to evaluate libraries (PyPDF2, pdfplumber, or LLM-based extraction)
* The shooting plan template is brand-specific (几素 brand example provided) — should be configurable
