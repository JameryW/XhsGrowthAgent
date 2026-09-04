# Evidence Graph codebase fit

## Existing seams

- `backend.creator_agent.models` owns Pydantic domain contracts and enum
  validation. `Evidence` already carries provenance fields and is embedded in
  model and decision snapshots.
- `CreatorAdvisor` is the behavioural seam used by routes and tests; evidence
  projection methods belong here instead of in HTTP handlers.
- `CreatorAgentRepository` and `backend.db.creator_agent.DurableCreatorAgentRepository`
  already provide the Postgres/process-memory adapter pair and account-scoped
  JSON snapshot readers.
- `backend.api.routes.creator_agent` owns authentication/account ownership and
  typed error translation. `api/spec/openapi.yaml` and
  `backend/api/generated/` must move together.

## Risks and decisions

1. Do not add a second Evidence write model in this increment. A read
   projection over current model + immutable decision + learning signal
   snapshots preserves provenance without introducing synchronization races.
2. A graph node is keyed by stable `evidence_id`. References carry model
   revision so a caller can distinguish which Creator Model snapshot cited the
   node. Evidence IDs should be changed when claim meaning changes.
3. Build the same pure projection helper for both adapters to keep ordering,
   deduplication, and filter semantics identical.
4. Candidate references must include the decision ID because candidate IDs are
   only unique inside one Decision Request.

## Verification targets

- memory projection with model item links, decision/candidate links, and a
  learning signal snapshot;
- source/reference filtering and deterministic ordering;
- account isolation and typed HTTP 404;
- static OpenAPI path/schema presence and generated model type sync;
- Ruff, Mypy, and focused Creator Agent/API/contract tests.
