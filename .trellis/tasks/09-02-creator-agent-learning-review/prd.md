# Creator Agent Learning Signal Review Loop

## Problem

The first Creator Agent slice records User Feedback and returns
`pending_creator_review`, but the learning signal is implicit and disappears
behind a status string. Creators cannot inspect which feedback is asking for a
change, decide whether it is trustworthy, or explicitly publish the next model
revision that incorporates it.

## Goal

Make the feedback loop durable and creator-controlled:

1. persist a first-class Learning Signal whenever feedback contains a
   correction or has a dissatisfied outcome;
2. expose pending signals for the account's creator;
3. support an explicit Creator Review that dismisses a signal or applies a
   complete next Creator Model revision with optimistic concurrency;
4. retain the signal's disposition and applied revision as an auditable link;
5. keep repeated feedback and repeated reviews idempotent.

## Domain contract

Canonical terms are defined in `CONTEXT.md`.

`LearningSignal` contains:

- a stable signal ID, account/Creator ID, Audience Member, Decision Record,
  and source feedback ID;
- a concise summary plus the correction text, if supplied;
- the Decision Record Evidence IDs observed at the time of feedback;
- `pending_creator_review`, `approved`, or `dismissed` status;
- review note, reviewed timestamp, and the applied model revision when
  approved.

`Creator Review` is explicit. Approval requires the caller to send the complete
`CreatorModelDefinition` for the next revision and its `expected_revision`.
Dismissal never changes the model. The service must not infer structured model
changes from natural-language corrections in this increment.

## Deep module interface

Extend `CreatorAdvisor` with:

- `list_learning_signals(account_id, status=None) -> list[LearningSignal]`
- `review_learning_signal(account_id, signal_id, review) -> LearningSignalReviewResult`

`record_feedback` continues to be the only entry point that creates a signal.
The repository adapter owns atomic persistence and optimistic-concurrency
checks; routes only translate authentication, validation, and typed errors.

## Feedback semantics

- A correction or `dissatisfied` outcome creates exactly one signal per
  feedback ID.
- Retrying an existing feedback ID returns the original signal and original
  `learning_status`, even if the retry payload differs.
- Positive/neutral feedback does not create a signal.
- Signal evidence is a snapshot of the Decision Record evidence, not a live
  join to a later model revision.

## Review semantics

- `pending_creator_review` + `dismissed` stores the review and leaves the
  Creator Model revision/payload unchanged.
- `pending_creator_review` + `approved` requires `model` and
  `expected_revision`; it creates exactly one new revision and records that
  revision on the signal.
- A stale expected revision returns the existing typed 409 conflict and leaves
  both signal and model unchanged.
- Repeating the same review is idempotent; attempting a different disposition
  after review returns a typed conflict.

## HTTP adapter

All routes remain authenticated and account-scoped through the existing owner
check:

- `GET /api/creator-agent/learning-signals?account_id=...&status=...`
- `POST /api/creator-agent/learning-signals/{signal_id}/review`

The review request carries `account_id`, `disposition`, `review_note`,
`expected_revision`, and an optional complete `model` definition. Approved
reviews return the signal and the resulting Creator Model revision.

## Persistence

Add `creator_agent_learning_signals`, keyed by `(account_id,
learning_signal_id)`, with a unique `(account_id, feedback_id)` to enforce
idempotency. Review updates and an approved model write occur in one explicit
transaction in Postgres and under the memory adapter lock.

## Out of scope

- automatic extraction of a model patch from a correction;
- LLM-generated review decisions;
- public audience authentication, search, transactions, or UI;
- changing existing Creative Memory or workflow behavior.

## Acceptance criteria

- Dissatisfied/correction feedback returns and persists a Learning Signal;
- signal listing is account-scoped and can filter pending/approved/dismissed;
- dismissal is durable and model-neutral;
- approval requires a complete model definition, increments revision once, and
  links the signal to that revision;
- stale approval and conflicting re-review fail without partial writes;
- feedback and review retries are idempotent;
- static/dynamic OpenAPI, generated models, focused tests, Ruff, and mypy pass.
