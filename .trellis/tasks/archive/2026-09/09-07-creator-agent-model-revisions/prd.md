# Creator Agent Model Revision History

## Problem

Every durable Creator Agent object already promises immutability: a Decision
Record stores the `model_revision` it was evaluated against, an Action
Execution Receipt stores the revision it was hand-offed from, and a Creator
Review records the `applied_model_revision` that embodied the creator's
decision. But `creator_agent_models` stores exactly one row per account and
overwrites it on every save. As soon as the creator edits the model, the
revision a historical decision cites can no longer be resolved — the evidence
chain that the whole design is built on terminates at a number that points at
nothing.

This also breaks the learning loop's audit story: after a Creator Review is
approved, nobody can show *what changed* because of that signal, and the
Decision Dataset cannot explain its own snapshots.

## Goal

Make every Creator Model revision a durable, append-only snapshot, and expose
read-only resolution of the exact revision a decision or receipt cited.

1. every Creator Model write appends one immutable `ModelRevision` snapshot
   inside the same transaction as the current-model update;
2. snapshot provenance records whether the revision came from a creator edit,
   an approved Creator Review, or pre-existing history;
3. revision content is never mutated or deleted by any later write;
4. account-scoped read APIs: list revision history (keyset cursor pagination,
   newest first) and fetch one revision by number;
5. a Decision Record can be resolved to the exact model snapshot it used;
6. accounts that existed before this change get a one-time idempotent backfill
   so current-model history is never empty;
7. memory and Postgres adapters remain behaviorally equivalent;
8. HTTP/OpenAPI/generated models/docs/ADR/CONTEXT/backend specs stay synchronized.

## Domain contract

Canonical terms are defined in `CONTEXT.md`. `Model Revision` already means
"one complete, creator-approved version of a Creator Model"; this increment
makes that phrase durable instead of implied.

`Model Revision History` is the append-only, account-scoped sequence of
immutable Model Revision snapshots. `Model Revision Provenance` names what
caused a revision: `creator_edit`, `learning_review`, or `imported_history`
(a snapshot reconstructed from a model row written before this feature
existed).

There is deliberately no public "append a revision" operation. A snapshot only
exists as a side effect of a Creator Model write, so a revision cannot be
recorded without also becoming the current model. This keeps the current-model
row and the history permanently consistent.

## Model

```python
class ModelRevisionSource(StrEnum):
    CREATOR_EDIT = "creator_edit"
    LEARNING_REVIEW = "learning_review"
    IMPORTED_HISTORY = "imported_history"

class ModelRevision(BaseModel):
    account_id: str
    revision: int            # ge=1, equals model.revision
    recorded_at: str
    source: ModelRevisionSource
    source_signal_id: str | None   # set only for learning_review
    model: CreatorModel            # complete snapshot, verbatim

class ModelRevisionPage(BaseModel):
    items: list[ModelRevision]     # max 100
    total: int                     # complete history size before the cursor
    limit: int                     # 1..100
    next_cursor: str | None        # None means exhausted
```

`ModelRevision` validates that `model.account_id == account_id` and
`model.revision == revision`, so a mismatched payload can never be persisted
or returned.

The cursor is a versioned opaque token encoding only the keyset key
`{"v": 1, "revision": N}` (same construction style as
`encode_decision_dataset_cursor`). A malformed or unknown-version token raises
`ValueError` at the adapter boundary and becomes `ERROR_VALIDATION`; it never
silently restarts at the first page.

## Repository seam

Add two reads to `CreatorAgentRepository`:

```python
async def list_model_revisions(
    self, account_id: str, *, cursor: str | None = None, limit: int = 20
) -> ModelRevisionPage: ...

async def get_model_revision(
    self, account_id: str, revision: int
) -> ModelRevision | None: ...
```

Writes stay internal. Both existing write paths — `save_model` and the approved
branch of `review_learning_signal` — append through one shared private helper
after the new `CreatorModel` has been computed, within the same
transaction/lock that already serializes the current-model update. Rejected or
already-resolved reviews append nothing.

New typed error: `ModelRevisionMissingError(account_id, revision)` in
`backend/creator_agent/repository.py`, so the HTTP adapter can report the
account scope it searched without distinguishing absence from non-ownership.

## Advisor seam

`CreatorAdvisor` gains three read methods; it owns account normalization and
the not-found translation, and adds no write path:

```python
list_model_revisions(account_id, *, cursor=None, limit=20) -> ModelRevisionPage
get_model_revision(account_id, revision) -> ModelRevision          # raises ModelRevisionMissingError
get_decision_model_revision(account_id, decision_id) -> ModelRevision
```

`get_decision_model_revision` composes the existing `get_decision` with
`get_model_revision` using the decision's stored `model_revision`. If the
decision's revision is not in history (only possible for rows predating the
backfill window, or a revision pruned by an operator), it raises
`ModelRevisionMissingError` — it never falls back to the current model, and
never recomputes the decision.

## HTTP adapter

Authenticated, account-scoped routes under the existing `creator-agent` tag,
all returning the `ApiResponse` envelope, all calling `require_owned_account`
before any read:

```text
GET /api/creator-agent/model/revisions?account_id=...&cursor=...&limit=20
GET /api/creator-agent/model/revisions/{revision}?account_id=...
GET /api/creator-agent/decisions/{decision_id}/model-revision?account_id=...
```

Unknown revision or unresolvable decision revision → typed 404
`ERROR_CREATOR_MODEL_REVISION_NOT_FOUND`. Foreign accounts are indistinguishable
from missing revisions. `limit` outside `1..100`, empty `account_id`, or an
invalid cursor → `ERROR_VALIDATION`. These are read-only: no route creates,
mutates, or deletes a revision.

## Persistence

Postgres gains `creator_agent_model_revisions`:

```text
PRIMARY KEY (account_id, revision)
columns: account_id, creator_id, revision, source, source_signal_id,
         payload_json, recorded_at
INDEX  (account_id, revision DESC)
```

`ensure_tables` creates it idempotently and then backfills once: for every row
already in `creator_agent_models` it builds a snapshot with the same
`_model_revision_snapshot` constructor and the same column-parameter helper the
live write paths use, and inserts it with `source = 'imported_history'`. There
is deliberately no second, SQL-shaped payload construction — one writer owns the
row shape, so imported and recorded history cannot become differently readable.
Existing rows never resolve to an empty history without rewriting
`creator_agent_models`.

Inserts use `ON CONFLICT (account_id, revision) DO NOTHING` so a retried
transaction can never overwrite a historical snapshot, and the memory adapter is
keep-first for the same reason: an already stored revision is never replaced.

The memory fallback mirrors this with a `_mem_model_revisions` dict keyed by
`(account_id, revision)` under the existing `_mem_lock`, deep-copied on both
write and read, and cleared by `_reset_memory_store()`.

## Safety and compatibility

- No new external calls, credentials, tools, or side effects.
- `GET /model`, `PUT /model`, `decide()`, Decision Dataset, Action, and
  Learning Signal contracts are unchanged; existing tests must stay green.
- `creator_agent_models` keeps its optimistic-concurrency role; history is
  purely additive.
- Revision snapshots are complete `CreatorModel` payloads, so a snapshot never
  depends on the current row to be interpretable.

## Acceptance criteria

- First save produces revision 1 with `source = creator_edit`; each accepted
  save appends exactly one new snapshot and never touches earlier rows.
- An approved Creator Review appends a snapshot with
  `source = learning_review` and the reviewed `signal_id`; a dismissed review
  appends none.
- Deciding at revision N, then saving revision N+1, still returns the verbatim
  revision N content, including the preferences/policies/evidence of that
  revision.
- `GET /decisions/{id}/model-revision` returns the snapshot the decision
  actually used, not the current model.
- History is ordered `revision DESC`, `total` is the complete count regardless
  of cursor, cursor traversal has no gaps or duplicates, and a corrupt cursor
  is a typed validation error.
- Cross-account reads return not-found, and unknown revisions never fall back
  to the current model.
- Postgres backfill resolves a pre-existing model row to `imported_history`
  exactly once and is idempotent on rerun.
- Memory and Postgres adapters share identical lifecycle and read semantics.
- Static/dynamic OpenAPI, generated models, docs, ADR, CONTEXT, and backend
  specs are synchronized.
- Focused tests, Ruff, Mypy, OpenAPI/contract checks, and `git diff --check`
  pass.

## Out of scope

- Revert/rollback endpoints, revision diffs, or any write derived from history.
- Deleting, editing, expiring, or archiving revisions.
- Recomputing historical decisions against a newer revision.
- Frontend console UI for revision history.
- Storing the review note or the reviewer's identity on the snapshot.
