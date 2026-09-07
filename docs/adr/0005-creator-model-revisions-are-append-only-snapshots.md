# ADR-0005: Creator Model revisions are append-only snapshots

## Status

Accepted

## Context

The Creator Agent contract is built on provenance. A Decision Record stores the
`model_revision` it was evaluated against, an Action Execution Receipt stores
the revision it was hand-offed from, and a Creator Review stores the
`applied_model_revision` that embodied the creator's decision. `CONTEXT.md`
already defined a Model Revision as "one complete, creator-approved version of a
Creator Model".

The storage layer did not honour that definition. `creator_agent_models` kept
exactly one row per account and overwrote it on every save, so a revision number
cited by any historical record pointed at nothing once the creator edited the
model again. Three consequences were unavoidable:

- the Decision Dataset could return an immutable decision snapshot whose stated
  inputs could no longer be read;
- an accepted Creator Review could not show what it changed once a later edit
  landed;
- replacing the executor or auditing a past recommendation had no model to
  audit against.

A repeat-review path already exposed the same flaw: resolving the revision an
earlier approval produced required the current row to still match it, and the
memory and Postgres adapters disagreed about that case.

## Decision

Store every revision as an immutable snapshot in a new
`creator_agent_model_revisions` table keyed by `(account_id, revision)`, written
in the same transaction as the current-model update.

- **No public append operation.** A snapshot exists only as a side effect of a
  Creator Model write, so history and the current model can never disagree.
- **Provenance is recorded, not inferred.** Each snapshot names its source:
  `creator_edit`, `learning_review` (naming the reviewed signal), or
  `imported_history` for models that predate this change.
- **Insert-only.** Writes use `ON CONFLICT (account_id, revision) DO NOTHING`;
  a replayed transaction cannot overwrite a historical revision.
- **Reads never fall back.** Resolving an absent revision is a typed error.
  Neither the dataset nor the decision-to-revision lookup substitutes the
  current model, and neither recomputes a decision.
- **History is a read projection with the same cursor discipline as the
  Decision Dataset**, so the memory fallback and Postgres share one pure
  `build_model_revision_page` and cannot drift.
- **Existing rows are backfilled idempotently** in `ensure_tables`, so accounts
  created before this change resolve their current revision to themselves
  rather than to an empty history.

Completed Creator Review lookups now read from history, which also closed the
memory/Postgres disagreement described above.

## Consequences

Creator judgement becomes auditable for the lifetime of the account, and
`executor_version` on a receipt now has a model to interpret it against.
Storage grows monotonically: a full snapshot per revision is intentionally
denormalized so a snapshot never depends on the current row, which costs space
and makes the history non-deletable by contract. Revert, revision diffing, and
any UI are explicitly excluded; a future "roll back to revision N" must still be
expressed as a new creator-approved revision N+1, never as a rewrite of history.
Pre-existing decisions made before the backfill window still cite revisions that
may have no snapshot, and those lookups fail loudly by design.
