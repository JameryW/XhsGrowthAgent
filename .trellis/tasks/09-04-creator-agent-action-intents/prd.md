# Creator Agent Action Intent and Confirmation Gate

## Problem

Creator Agent currently returns a recommendation and its provenance, but there
is no machine-readable hand-off for the next step. A future User Agent or
Merchant Agent would have to parse prose, and an accidental call could jump
straight from advice to an external transaction without a consent boundary.

## Goal

Introduce a safe first Action seam that turns a Decision Record into an
auditable, idempotent Action Intent:

1. accept a small set of non-transactional action capabilities;
2. validate the action against the account-scoped Decision Record and its
   candidate set;
3. persist the intent with a caller idempotency key and
   `pending_confirmation` status;
4. require an explicit `confirmed` or `cancelled` resolution before a future
   executor may act;
5. keep confirmation side-effect free in this increment while exposing a
   stable contract for a later Tool/Skill adapter.

## Domain contract

Canonical terms are defined in `CONTEXT.md`.

`Action Intent` is a durable, scoped request to perform one declared action
for an Audience Member using one Decision Record. It contains the action kind,
selected candidate IDs, account/Creator/Audience/Decision identity, and a
caller-supplied idempotency key.

`Action Resolution` is the explicit disposition of an intent. `confirmed`
means a future executor may accept the intent; `cancelled` means it must not
execute. Resolution itself never calls an external system.

The first safe capabilities are:

- `compare_options`: compare at least two candidates from a recommended
  Decision Record;
- `save_shortlist`: save one or more recommended candidates as a hand-off
  shortlist;
- `request_more_evidence`: ask the upstream caller for missing facts when a
  decision is insufficiently evidenced; it has no candidate targets.

## Deep module interface

Extend `CreatorAdvisor` with three small methods:

- `plan_action(request: ActionIntentRequest) -> ActionIntent`
- `list_actions(account_id, status=None) -> list[ActionIntent]`
- `resolve_action(account_id, action_id, resolution) -> ActionIntent`

The Repository adapter owns idempotent persistence and lifecycle conflict
checks. Candidate/status validation belongs to the Advisor seam; routes only
translate authentication, validation, and typed errors.

## Action semantics

- `compare_options` requires a recommended Decision Record and two or more
  unique candidate IDs, each present in its recommendations.
- `save_shortlist` requires a recommended Decision Record and one or more
  unique candidate IDs, each present in its recommendations.
- `request_more_evidence` is allowed for any Decision Record and requires an
  empty candidate ID list.
- Every request carries a non-empty `idempotency_key`. Retrying the same key
  returns the original intent, even if the retry payload differs; reusing a
  key for a different account remains isolated.
- New intents start at `pending_confirmation`. A matching resolution is
  idempotent. A different resolution after the intent is resolved returns a
  typed conflict and changes nothing.
- Listing is account-scoped, optionally filters by exact status, and orders by
  creation time then action ID descending.

## HTTP adapter

Authenticated, account-scoped routes:

- `POST /api/creator-agent/actions`
- `GET /api/creator-agent/actions?account_id=...&status=...`
- `POST /api/creator-agent/actions/{action_id}/resolve`

The resolve request carries `account_id` and `disposition` (`confirmed` or
`cancelled`). All responses use the existing `ApiResponse` envelope.

## Persistence and compatibility

Add an account-scoped `creator_agent_actions` table with a unique
`(account_id, idempotency_key)`. The Postgres adapter writes and resolves
under transactions; the memory adapter mirrors the same invariants under its
existing lock. No external action executor, merchant integration, purchase,
booking, message, or transaction is introduced.

## Out of scope

- calling search, price tracking, booking, purchase, or after-sales tools;
- executing confirmed intents;
- public audience authentication or cross-account action sharing;
- LLM-generated action selection or natural-language parsing;
- frontend UI.

## Acceptance criteria

- Valid action intents are persisted, listed, account-scoped, and idempotent.
- Candidate and decision status invariants reject invalid actions without
  writes.
- Resolution requires an explicit confirmation/cancellation and is
  idempotent with typed conflicting-resolution errors.
- Postgres and memory adapters expose equivalent lifecycle behavior.
- OpenAPI/static generated models, docs, and domain glossary are synchronized.
- Focused tests, Ruff, Mypy, and OpenAPI validation pass.
