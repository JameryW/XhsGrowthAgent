# Creator Agent Decision Dataset Query Layer

## Problem

Creator Agent now stores immutable Decision Records, User Feedback, and
feedback-derived Learning Signals, but callers can only fetch one decision at a
time. That makes the most valuable long-term asset—the creator's decision
dataset—difficult to inspect, export, or feed into a review/training pipeline.
Consumers need a stable, account-scoped read stream that preserves the exact
decision snapshot and exposes its feedback labels without recomputing against a
newer Creator Model.

## Goal

Expose a deterministic Decision Dataset projection with:

1. cursor pagination over immutable Decision Record snapshots;
2. optional filters for audience, decision status, feedback outcome, and
   whether feedback exists;
3. linked Learning Signal IDs so correction/dissatisfaction labels can be
   joined without leaking signal payloads;
4. stable ordering, complete filtered totals, and an opaque cursor;
5. identical account isolation and behavior in Postgres and memory fallback;
6. synchronized HTTP/OpenAPI/generated-model/docs/spec contracts.

## Domain contract

Canonical terms are defined in `CONTEXT.md`.

`Decision Dataset Entry` is a read-only projection containing the original
`DecisionRecord` snapshot plus the Learning Signal IDs derived from that
decision's feedback. The nested Decision Record is returned verbatim: its model
revision, evidence, ranking, exclusions, confidence, and append-only feedback
are never recomputed from the current Creator Model.

`Decision Dataset Page` contains `items`, the complete `total` for the active
filters (before the cursor), the requested `limit`, and an opaque
`next_cursor`. A missing cursor means the first page; a null next cursor means
there are no more rows.

## Query semantics

The repository exposes:

```text
list_decision_dataset(
  account_id,
  *, audience_id=None, status=None, feedback_outcome=None,
  has_feedback=None, cursor=None, limit=20
) -> DecisionDatasetPage
```

- rows are scoped by `account_id` and ordered by `created_at DESC,
  decision_id DESC`;
- `audience_id` is an exact match when supplied;
- `status` is an exact `DecisionStatus` match;
- `feedback_outcome` matches a row when any stored feedback has that outcome;
- `has_feedback=true/false` selects rows with/without at least one feedback;
- filters are applied before `total` and cursor traversal;
- cursors encode only the canonical sort key and are rejected when malformed;
- page limits are bounded to 1..100 by the HTTP adapter;
- missing/foreign accounts return an empty page, never another account's data.

Learning Signal IDs are resolved by the account-scoped `decision_id` relation
and returned in stable ascending order. A signal payload is not joined into the
dataset row; callers can opt into the existing Learning Signal endpoint.

## HTTP adapter

Add an authenticated, account-scoped route:

```text
GET /api/creator-agent/dataset/decisions
  ?account_id=...
  &audience_id=...
  &status=recommended
  &feedback_outcome=purchased
  &has_feedback=true
  &cursor=...
  &limit=20
```

The route returns the existing `ApiResponse` envelope. Invalid cursor or blank
optional identifiers return `ERROR_VALIDATION`; ownership is checked before
reading. The route is read-only and does not create feedback, learning
signals, actions, or model revisions.

## Persistence

The existing `creator_agent_decisions` and
`creator_agent_learning_signals` snapshots remain the source of truth; no new
table or migration is needed. Postgres reads both snapshot families in one
repeatable-read transaction before filtering and assembling the page. The
memory adapter copies both maps under `_mem_lock` and uses the same pure
projection helper. The SQL path must retain account and status predicates and
the canonical ordering; feedback-outcome filtering may be evaluated from the
validated JSON snapshot to keep historical labels exact.

## Safety and compatibility

- This increment adds no external search, transaction, purchase, booking,
  messaging, or model-learning side effect.
- Existing single-decision, feedback, learning-signal, evidence, and action
  endpoints keep their contracts.
- Dataset rows are account-scoped and preserve audience IDs only inside the
  already authenticated account boundary.
- Cursors are opaque, versioned, and invalidated naturally when their shape
  changes; they must never silently restart at page one.

## Acceptance criteria

- Dataset entries preserve Decision Record snapshots and linked signal IDs.
- Filters compose correctly; `total` counts the complete filtered stream even
  when the page is cursored.
- Ordering and cursor traversal are stable for tied timestamps.
- Memory and Postgres adapters expose equivalent results and account isolation.
- Invalid cursors and limits are returned as typed validation errors.
- The new route is authenticated, ownership-scoped, read-only, and represented
  in static/dynamic OpenAPI plus generated models.
- Focused tests cover empty pages, filters, pagination boundaries, feedback
  labels, learning-signal links, account isolation, and invalid cursors.
- Ruff, Mypy, focused pytest, OpenAPI validation, and `git diff --check` pass.

## Out of scope

- Automatic model updates or training jobs.
- Natural-language search over decisions.
- Public audience access or cross-account exports.
- Deleting/redacting historical decision snapshots.
