# Creator Agent Evidence Graph Query Layer

## Problem

The Creator Agent already stores Evidence snapshots inside Creator Models,
Decision Records, and Learning Signals. Callers can see an evidence ID on a
single response, but cannot ask where that evidence came from, which model
rule or decision used it, or whether a later learning signal is grounded in
the same observation. The provenance moat is present in the data but not yet
queryable as a graph.

## Goal

Expose a creator-scoped, read-only Evidence Graph projection over the durable
Creator Agent snapshots:

1. return each unique Evidence node with typed references to the model,
   preference, knowledge claim, decision policy, decision record, candidate,
   and learning signal that use it;
2. support exact evidence lookup and source/reference filters;
3. preserve model revision and decision snapshot provenance without mutating
   Creator Models or Decision Records;
4. keep account isolation, Postgres durability, memory fallback, and stable
   deterministic ordering;
5. synchronize the HTTP contract, generated models, docs, and focused tests.

## Domain contract

Canonical terms are defined in `CONTEXT.md`.

`Evidence Reference` is a typed edge from one Evidence node to the durable
Creator Agent object that cites it. A reference carries the target ID and,
when applicable, the Creator Model revision used by that object.

`Evidence Graph Entry` contains one Evidence node and all deduplicated typed
references visible to one account. Evidence IDs are the stable logical node
identity; callers should create a new ID when a claim's meaning changes.

The projection is read-only. A model revision or decision snapshot remains the
source of truth; the graph must not infer claims, rewrite evidence, or update a
model while answering a query.

## Deep module interface

Extend `CreatorAdvisor` with two small methods:

- `list_evidence(account_id, source_kind=None, reference_type=None) -> list[EvidenceGraphEntry]`
- `get_evidence(account_id, evidence_id) -> EvidenceGraphEntry | None`

The repository adapter owns graph assembly from durable snapshots. Routes only
translate account ownership, filters, and not-found errors.

## Graph semantics

- Creator Model evidence is linked to the model's `creator_id` and revision;
  preference, knowledge claim, and decision policy evidence IDs create edges
  to their respective item IDs and the same revision.
- A Decision Record evidence snapshot links to its decision ID and stored model
  revision. Evidence IDs cited by a ranked candidate also link to a stable
  `decision_id:candidate_id` candidate reference.
- A Learning Signal evidence snapshot links to its signal ID. The graph uses
  the matching Decision Record snapshot for the Evidence payload, so a later
  model revision cannot rewrite the signal's provenance.
- References are deduplicated by type, target ID, and revision, and entries
  are ordered by `evidence_id` ascending with references ordered by type,
  target ID, then revision.
- Source and reference filters are exact enum filters. An unknown evidence ID
  returns not found within the account scope; another account never leaks a
  node or reference.

## HTTP adapter

Authenticated, account-scoped routes:

- `GET /api/creator-agent/evidence?account_id=...&source_kind=...&reference_type=...`
- `GET /api/creator-agent/evidence/{evidence_id}?account_id=...`

Both responses use the existing `ApiResponse` envelope. The list route
returns an empty list when no evidence matches; the detail route returns the
typed Creator Evidence not-found error.

## Persistence and compatibility

The graph is a read projection over existing durable Creator Model, Decision
Record, and Learning Signal JSON snapshots. Postgres reads all account-scoped
snapshots in one read transaction; the process-memory adapter snapshots its
maps under the existing lock. No migration or write-path change is required
in this increment, and existing decision/feedback semantics remain intact.

## Out of scope

- automatic evidence extraction from content or external sources;
- editing or deleting Evidence nodes;
- cross-account or public audience access;
- graph databases, full-text search, or ranking evidence by quality;
- action execution, transactions, or frontend UI.

## Acceptance criteria

- A model's Evidence, policy links, and decision snapshots appear as typed
  graph references with the correct revision.
- Learning Signal references use the original decision evidence snapshot.
- List/detail endpoints are account-scoped and support exact filters; missing
  detail returns a typed 404.
- Memory and Postgres adapters expose the same deterministic projection.
- OpenAPI/static generated models and contract tests are synchronized.
- Focused pytest, Ruff, Mypy, and OpenAPI validation pass.
