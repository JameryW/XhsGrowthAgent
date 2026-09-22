# Creator Agent decision core: codebase fit

## Existing assets

- `backend.memory.creative.CreativeMemory` is account-scoped and persists Style DNA, conversion plays, materials, and niche benchmarks through `backend.db.creative_memory`.
- `backend.services.creator_stats.analyze` derives those content-production assets from imported Creator Center notes.
- `backend.services.creator_stats.suggestions` turns the derived analysis into mode-specific prompt context for trend, brief, and free creation.
- `backend.memory.store.MemoryManager` has an account-scoped `audience_preferences` namespace, but it is not scoped to an individual audience member, is not a durable source of truth without LangGraph Store, and is not linked to decisions or feedback.
- `backend.api.account_scope.require_owned_account` is the canonical private-route ownership gate. Cross-owner access deliberately returns not found.
- `backend.db.creative_memory` establishes the repository convention for Postgres persistence with a process-local memory fallback and an explicit test reset helper.
- `backend.api.responses` and `backend.api.middleware` provide the response envelope and typed `APIError` handling used by private routes.

## Gap against the product thesis

The current memory stack optimizes content generation. It has no platform-independent Creator ID, revisioned statement of creator judgement, evidence registry, deterministic candidate decision, per-audience relationship, immutable decision record, or feedback-to-review loop. Treating Style DNA as the Creator Model would collapse descriptive content patterns into normative judgement and would allow engagement performance to redefine the creator implicitly.

## Recommended module shape

Create a new `backend.creator_agent` package with a narrow external interface:

- `CreatorModelStore` owns model creation/revision and retrieval.
- `CreatorAdvisor` owns `decide` and `record_feedback`.
- typed domain models live beside those interfaces and serialize cleanly to the existing API envelope.
- deterministic scoring is an implementation detail tested through `CreatorAdvisor.decide`, not a public helper collection.

Create `backend.db.creator_agent` as the persistence adapter following the existing Postgres/memory fallback convention. Keep SQL and fallback storage out of the domain package.

Create `backend.api.routes.creator_agent` as an authenticated adapter. It should resolve concrete owned account IDs before invoking either module and should not reimplement scoring or feedback semantics.

## Integration points

- Include the new database `ensure_tables` call in `backend.api.app.lifespan` beside accounts, creator stats, and creative memory.
- Include the route at `/api/creator-agent` in `backend.api.app`.
- Add typed revision-conflict and decision-not-found errors to `backend.api.errors`.
- Keep current graph nodes and creator-stats suggestion generation unchanged in this increment.
- Extend OpenAPI/contract coverage so the new route schemas are captured by the existing FastAPI application import.

## Risks to test explicitly

- A stale model write must not overwrite a newer model.
- A decision must store the exact model revision used even if the model is revised afterward.
- Candidate-provided unknown evidence IDs must not be treated as creator evidence.
- No matched policy or no supporting evidence must yield `insufficient_evidence`.
- Hard constraints and excluded tags must not leak excluded candidates into ranking.
- Repeating a feedback request with the same feedback ID must be idempotent.
- Feedback for a decision under another account must look not found.
- Relationship memory must be keyed by both account and audience member.
- Feedback must not mutate or increment the Creator Model.
