# Creator Stats Cross-Layer API Contract

## Objective

Make Creator Stats consumers enforce the same input and response contract as
the backend. Invalid note limits should be rejected before a network request,
and risk/cooldown metadata returned by the backend should remain visible to
typed clients.

## Scope

- Add integer and `1..200` bounds to the OMP `xhs_creator_stats` tool's `limit`
  schema, matching the backend query contract.
- Add optional batch-sync metadata fields (`risk_code`, `force_light`) to the
  frontend API type, without changing runtime behavior or response shape.
- Add focused client-side/extension tests or static contract assertions where
  the existing test setup supports them.
- Document the shared limit and cooldown metadata contract in the appropriate
  project spec.

## Non-goals

- No changes to backend persistence, scraping, scheduling, or risk decisions.
- No new network retries or broader API permissions.
- No UI redesign; consumers only gain accurate validation/types.

## Acceptance Criteria

1. OMP rejects empty, fractional, below-minimum, and above-maximum limits at
   schema validation time; valid integer limits remain accepted.
2. Frontend `CreatorStatsBatchSyncResult` types include optional risk metadata
   returned by backend cooldown/scheduled responses.
3. Existing frontend and OMP tests/build checks pass; backend unit tests remain
   green.
4. The shared contract is documented so future clients do not rely on a prose
   description alone.
