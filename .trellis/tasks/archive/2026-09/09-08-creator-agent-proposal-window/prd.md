# Creator Agent Evidence Proposal Window Correctness

## Problem

`list_evidence_proposals(account_id, limit=N)` uses one number for two different
jobs: the per-family fetch window *and* the returned page size. Each Creative
Memory family then selects its own rows with an ordering that is not the
proposal ordering:

- `list_materials` — `ORDER BY weight DESC` (a soft-demotion weight, unrelated to
  evidence strength);
- `list_styles` / `list_plays` — raw measured rate descending, which ignores
  sample size entirely.

The projection ranks by sample-shrunk confidence. Because truncation happens
first in storage order and only later by confidence, a small page can silently
omit the strongest available evidence while presenting a page that looks like a
correct top-N.

Reproduced against the current implementation with 13 materials (3 noise at
`weight=1.0, effectiveness=0.2, reuse=40`; 9 at `weight=0.5, effectiveness=0.99,
reuse=0`; 1 decisive at `weight=0.2, effectiveness=0.8, reuse=40`):

| limit | page returned | decisive observation present |
|:---|:---|:---|
| 3 | 3 proposals, all confidence 0.178 | **no** |
| 13 | confidence 0.711 first | yes |

The caller cannot tell these two apart, and an empty or short page is read as
"the account has nothing else", which is exactly the wrong inference for a
surface whose purpose is to inform a creator-approved Model Revision.

## Goal

Separate the scan budget from the page size, and make a bounded scan visible in
the response contract.

1. one `limit` means exactly one thing: how many proposals to return;
2. the observation scan gets its own, wider candidate window;
3. the response states how many proposals matched overall, and whether the scan
   was bounded, so a short page is never silently incomplete;
4. ranking stays deterministic and remains a pure, storage-independent projection;
5. memory and Postgres behavior stay equivalent, and HTTP/OpenAPI/generated
   models/docs/specs stay synchronized.

## Contract change

The endpoint is hours old and has no consumers, so the response shape changes
rather than growing a compatibility shim.

```python
class EvidenceProposalPage(BaseModel):
    items: list[EvidenceProposal]   # max 100, confidence DESC then source_ref ASC
    total: int                      # proposals matching the filters, before paging
    limit: int                      # 1..100
    truncated: bool                 # the bounded scan may have missed observations
```

`truncated` is `True` when any family returned a full candidate window, meaning
storage may hold more rows than were examined. When `truncated` is `False`,
`total` is exhaustive: the caller has seen every matching proposal.

The observation seam therefore reports saturation instead of returning a bare
list:

```python
class ContentObservationScan(BaseModel):
    observations: list[ContentObservation]
    saturated: bool

class CreatorContentObservationSource(Protocol):
    async def observations(self, account_id: str, *, window: int) -> ContentObservationScan: ...
```

`window` is the per-family candidate budget, not the page size. The advisor
derives it as `max(60, limit * 4)`, clamped to the storage ceiling of 100 rows
per family. The clamp is a documented limit of this increment, not an
exhaustive scan.

## Semantics

- `total` counts proposals that survived filtering, source-ref dedupe against the
  Evidence Graph, and in-batch dedupe — everything except the page cut.
- `min_confidence` and dedupe are applied before `total`, matching how
  `build_decision_dataset_page` and `build_model_revision_page` treat filters.
- `truncated` reflects only scan boundedness. Returning fewer items than
  requested because few exist is not truncation.
- Empty account, blank account, or no wired source →
  `{items: [], total: 0, limit, truncated: false}`.
- Adapter saturation detection stays honest in both storages: Postgres families
  all `LIMIT` their query, and the memory fallback slices to the same bound, so
  "returned exactly `window` rows" carries the same meaning on both paths.

## Files and layering

Unchanged: `backend/creator_agent/` still must not import `backend/memory` or
`backend/db/creative_memory`; the existing AST import-direction test continues to
guard it. `ContentObservationScan` lives with the other domain models, and the
pure projection keeps all ranking/filtering so both adapters stay equivalent.

## HTTP

`GET /api/creator-agent/model/evidence-proposals` keeps its parameters and
validation, now returning `ApiResponse[EvidenceProposalPage]`. Still strictly
read-only.

## Acceptance criteria

- The reproduction above returns the decisive proposal at `limit=3` with
  `total=13`, `truncated=false`.
- A family whose rows exceed the window sets `truncated=true`, and `total` is
  documented and tested as the scanned-matching count rather than an exhaustive
  one.
- Page size never changes which proposals are considered, except through the
  documented window formula.
- `items` remain ordered confidence DESC / `source_ref` ASC, byte-identical
  across calls, and already-cited sources stay excluded.
- No-source, blank-account, and empty-history cases return the explicit empty
  page with `truncated=false`.
- Static and dynamic OpenAPI, generated models, docs, ADR-0006 note, backend
  spec, and CONTEXT wording are synchronized.
- Focused tests, Ruff, Mypy, contract checks pass, and the full-suite failure set
  stays identical to baseline.

## Out of scope

- Exhaustive full-history scans, cursors, or background materialization of
  proposals.
- Changing Creative Memory storage, its indexes, or the `recall_*` relevance APIs.
- Any write or adoption endpoint.

## Follow-up executed: real-Postgres parity

Run after the window fix. `tests/integration/test_creator_agent_backend_parity.py`
drives one behavioral scenario against both backends and compares masked traces.
First execution of the Postgres branches anywhere, locally or in CI.

Two findings:

1. **Windows cannot run the async Postgres path at all** under asyncio's default
   `ProactorEventLoop`; psycopg3 requires a selector loop. The parity module owns
   its loop instead of using `pytest.mark.asyncio`, which is also why the memory
   fallback has always been the only tested path.
2. **A real divergence, then fixed:** the Postgres branch validated "approval
   requires a model" before reading the signal, so replaying an already-approved
   disposition raised where memory returned the original result. The contract says
   repeating a disposition is idempotent, so memory was right; the check moved
   inside the pending-approval branch. Pinned by a memory-only regression test so
   it stays caught without a database.

The run also proves against a live server that `ensure_tables` is idempotent, the
revision backfill yields a parseable `ModelRevision` tagged `imported_history`,
and the history table's `(account_id, revision)` key exists.
