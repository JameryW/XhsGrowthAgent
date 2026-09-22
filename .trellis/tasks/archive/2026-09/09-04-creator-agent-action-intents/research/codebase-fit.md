# Action Intent codebase fit

## Existing seams

- `backend.creator_agent.models` already owns Pydantic contracts and lifecycle
  enums for Decision Records and Learning Signals.
- `CreatorAdvisor` is the deep behavioral seam; it can validate action kinds
  against a persisted Decision Record before delegating storage.
- `CreatorAgentRepository` and `backend.db.creator_agent` provide the
  Postgres/process-memory adapter pair and shared account-scoped locking.
- `backend.api.routes.creator_agent` already owns account ownership,
  `ApiResponse`, and typed exception translation.
- `api/spec/openapi.yaml` is the checked-in HTTP contract and
  `backend/api/generated/` is regenerated from it.

## Design risks

1. Keep “confirmed” distinct from “executed”. A confirmation gate is useful
   now, while an executor needs separate tool authorization and idempotency in
   a later increment.
2. Candidate IDs are only unique within one Decision Record; validation must
   use that record's recommendation set and never accept arbitrary IDs.
3. Idempotency keys are account-scoped. The memory and Postgres adapters must
   return the original payload on retry and never overwrite it.
4. `request_more_evidence` must remain valid for insufficient-evidence
   decisions, while candidate-targeted actions require a recommendation.
5. Resolve operations must be serialized under the same account/action lock so
   two conflicting resolutions cannot both succeed.

## Verification targets

- successful compare/save/request-more-evidence planning;
- rejected candidate/status/target combinations with no persisted row;
- retry idempotency and account isolation;
- confirm/cancel lifecycle, repeated resolution, and conflicting resolution;
- API ownership, validation, not-found/conflict errors;
- static/dynamic OpenAPI, generated model sync, Ruff, Mypy, and focused tests.
