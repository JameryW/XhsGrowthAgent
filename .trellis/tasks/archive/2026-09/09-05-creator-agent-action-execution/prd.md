# Creator Agent Action Execution Receipts

## Problem

Action Intent now provides a durable, explicit confirmation gate, but a
confirmed intent still has no machine-readable execution result. Callers would
have to treat confirmation as success or invent their own side effects, which
breaks the distinction between Creator Agent judgement and an executor.

## Goal

Add a narrow execution seam for the three existing non-transactional
capabilities. The first executor is deliberately local and deterministic: it
reads the immutable Decision Record, produces an auditable execution receipt,
and never calls search, merchant, purchase, booking, messaging, or platform
automation tools.

1. only `confirmed` Action Intents may execute;
2. each action can produce exactly one account-scoped, idempotent receipt;
3. receipts preserve the source action/decision identity and executor version;
4. the three safe capabilities return explicit, capability-specific results;
5. pending/cancelled intents fail with typed conflicts and leave no receipt;
6. memory and Postgres adapters remain behaviorally equivalent;
7. HTTP/OpenAPI/generated models/docs/specs stay synchronized.

## Domain contract

`Action Execution` is the local, side-effect-free hand-off from a confirmed
Action Intent to a deterministic executor. It is not a purchase, booking, or
external transaction. `Action Execution Receipt` is the durable result of that
execution and records the exact action, Decision Record, Creator Model revision,
executor version, status, result payload, and timestamps.

`ActionExecutionStatus` has `succeeded` and `failed`. This increment only emits
`succeeded` receipts because all built-in operations are deterministic and
local; the failed status is reserved for a future executor adapter that can
report a recoverable failure without changing the Action Intent lifecycle.

Capability results:

- `compare_options`: returns the selected recommended candidate snapshots and
  their existing scores/rationales/evidence IDs;
- `save_shortlist`: records the selected recommended candidate IDs as a
  durable shortlist receipt, without contacting a merchant or mutating an
  external list;
- `request_more_evidence`: returns a structured request containing the source
  decision ID, status, evidence coverage, and confidence for an upstream caller
  to satisfy.

## Deep module interface

Extend `CreatorAdvisor` with two methods:

```text
execute_action(account_id, action_id) -> ActionExecution
get_action_execution(account_id, action_id) -> ActionExecution | None
```

The repository owns receipt idempotency and account isolation. The Advisor
owns confirmation checks and deterministic result construction. A private
executor registry may vary by capability, but it is not part of the HTTP
contract until an external adapter is introduced.

## Execution semantics

- Missing or cross-account actions return the existing typed action not-found
  error.
- `pending_confirmation` and `cancelled` actions cannot execute and return a
  typed `ActionExecutionNotAllowed` conflict; no receipt is written.
- A confirmed action is evaluated against its original Decision Record
  snapshot. A missing source decision is a typed not-found error and leaves no
  partial receipt.
- Repeating execution for the same `(account_id, action_id)` returns the
  original receipt byte-for-byte (including result and timestamps).
- Concurrent Postgres execution uses a row lock and unique primary key; the
  memory adapter uses the existing shared lock.
- Execution receipts are immutable. There is no retry mutation, deletion, or
  execution of a cancelled intent.

## HTTP adapter

Add authenticated, account-scoped routes:

```text
POST /api/creator-agent/actions/{action_id}/execute
GET  /api/creator-agent/actions/{action_id}/execution?account_id=...
```

The POST request carries only `account_id`; confirmation is read from the
stored Action Intent and cannot be smuggled in the execution request. Both
routes return the existing `ApiResponse` envelope. Not-allowed and duplicate
state errors are typed 409 responses; a missing receipt on GET is a typed 404.

## Persistence

Add an account-scoped `creator_agent_action_executions` table keyed by
`(account_id, action_id)` with a unique receipt ID. Store the complete receipt
payload as JSON plus indexed status/timestamps. `ensure_tables` creates it
idempotently. Postgres execution must lock the action row, read the source
decision in the same transaction, and insert the receipt with `ON CONFLICT DO
NOTHING` before returning the durable row. The memory adapter mirrors this
under `_mem_lock`.

## Safety and compatibility

- No new external credentials, tools, network calls, purchases, bookings,
  messages, or platform writes are introduced.
- Confirmation remains a consent gate; execution is a separate explicit call.
- Existing action planning/resolution and Decision Dataset contracts remain
  unchanged.
- The receipt's `executor_version` makes future executor behavior auditable
  without rewriting historical results.

## Acceptance criteria

- Confirmed `compare_options`, `save_shortlist`, and `request_more_evidence`
  actions each produce the documented deterministic receipt.
- Pending/cancelled/missing actions return the correct typed errors and do not
  create rows.
- Repeated and concurrent execution is idempotent and account-scoped.
- Receipt GET returns the same immutable payload as POST; foreign accounts are
  indistinguishable from missing receipts.
- Memory and Postgres adapters share the same lifecycle and result semantics.
- Static/dynamic OpenAPI, generated models, docs, ADR, CONTEXT, and backend
  specs are synchronized.
- Focused tests, Ruff, Mypy, OpenAPI checks, and `git diff --check` pass.

## Out of scope

- Search, ranking new candidates, price tracking, merchant or brand contact.
- Purchase, booking, after-sales, social publishing, or any external side
  effect.
- Background execution queues, retries, webhooks, or user-facing UI.
