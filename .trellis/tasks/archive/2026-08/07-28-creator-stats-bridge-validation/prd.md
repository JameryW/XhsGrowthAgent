# Creator Stats Python Bridge Validation

## Objective

Keep the Python OMP host-tool bridge behavior aligned with the TypeScript
Creator Stats extension and the backend route contract.

## Scope

- Mark `account_id` as non-empty and `limit` as an integer in `1..200` in the
  Python bridge's advertised host-tool schema.
- Validate and normalize those arguments before making the internal HTTP
  request, returning a structured tool error for invalid input.
- Add bridge tests for valid forwarding and invalid account/limit values.
- Document that both OMP implementations must enforce the same boundary.

## Non-goals

- No backend route, database, or scraping changes.
- No retries or fallback behavior changes.
- No changes to unrelated host tools.

## Acceptance Criteria

1. Empty/whitespace account IDs, booleans, non-integer limits, and limits
   outside `1..200` are rejected without opening an HTTP client.
2. Valid account IDs are trimmed and valid limits are forwarded unchanged as
   integer query parameters.
3. Existing OMP bridge tests and backend quality checks pass.
