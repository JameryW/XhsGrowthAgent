# Research: semantic near-dupe cost (PRD §9 Q3)

- **Query**: Memory Promotion semantic near-duplicate cost — repo embedding surfaces; call-site policies A/B/C; unavailable-index → REVIEW/REFUSE/skip-hint; MVP recommendation under `decide_promotion` purity + optional BaseStore
- **Scope**: mixed (internal primary; parent PRD + docs as authority)
- **Date**: 2026-10-31

## Findings

### Files Found

| File Path | Description |
|---|---|
| `backend/memory/index.py` | `IndexConfig` builder; `get_store_index` / `get_prod_store_index` → `None` when credentials/provider/embed construction fail; `semantic_index_status()` env-only readiness |
| `backend/memory/store.py` | `MemoryManager.recall_*` → `store.asearch(...)`; empty list = empty recall only; read failures raise (票 5m) |
| `backend/memory/creative.py` | Optional `BaseStore`; durable DB primary; store `asearch` best-effort (warn + continue); deposits work when `store is None` |
| `backend/memory/promotion.py` | Pure `decide_promotion` / `_dedupe`; key+`source_ref` only; docstring: semantic near-dupes are reviewer hints, not settled here |
| `backend/memory/promotion_observations.py` | Observe call-site: builds `existing` from ledger, calls `decide_promotion`, optional `ledger.append` |
| `backend/memory/promotion_ledger.py` | Append-only ledger; `store is None` → `NO_STORE` / `available=False`; `detail` field for operator context; list via `asearch` (no query) |
| `backend/memory/promotion_hy.py` | hy batches: `DEGRADED` → single `REFUSE(source_degraded)`; healthy empty ≠ degraded |
| `backend/graph/builder.py` | Compiles store with `get_store_index()` / `get_prod_store_index()` (`index=` may be `None`) |
| `backend/api/routes/system.py` | Health: store present + semantic off → `memory_store.status=degraded` |
| `backend/context/retrieval.py` | `store is None` / `asearch` exception → `RetrievalMode.DEGRADED` (not EMPTY) |
| `backend/context/models.py` | `RetrievalMode`: HIT / EMPTY / DEGRADED |
| `docs/memory-promotion.md` | Protocol does not judge semantic dupes; hint-only (PRD §3) |
| `.trellis/tasks/archive/2026-10/10-21-memory-promotion-pipeline/prd.md` | §3 / §5.2 / §9 Q3 authority for near-dupe + open cost question |

### Code Patterns

#### 1) Embedding / semantic search surfaces in THIS repo

**Index construction (`backend/memory/index.py`)**

- Without an index, LangGraph `store.asearch()` is documented as **namespace recency only**; with an index it is true semantic similarity.
- `get_store_index() -> IndexConfig | None`:
  - Builds langchain `Embeddings` (`openai` / `openai_compatible` / `local`).
  - Returns **`None`** when: required API key missing; provider cannot be parsed; embed object construction throws (construction failure is **not** permanently cached so a later download can succeed).
  - Env: `XHS_EMBED_MODEL`, `XHS_EMBED_DIMS`, `XHS_EMBED_BASE_URL`, `OPENAI_API_KEY` (for openai*).
- `get_prod_store_index()`: same base + `distance_type: "cosine"`; also `None` if base is `None`.
- `semantic_index_status()`: env-only readiness for `/system/health` (no Embeddings load). Reasons: `ok` / `missing_api_key` / `invalid_provider` / `unsupported_provider`.

**Who calls `asearch`**

| Caller | Query? | Failure / degraded behavior |
|---|---|---|
| `MemoryManager.recall_*` | yes (`query=`) | **raises** (票 5m — empty list ≠ failure) |
| `CreativeMemory.recall_*` | yes when store present | try/except → warn; durable DB still used |
| `PromotionLedger.records` | no (list page) | store raises → raise; `store is None` → `available=False` |
| `context.retrieval._recall_one` | yes | `store is None` or exception → **`DEGRADED`**, not EMPTY |
| Graph compile | N/A | `InMemoryStore(index=store_index)` / Postgres `index=prod_index` — index may be `None` |

**Health mapping (`system.py::_check_memory_store`)**

- Store unavailable → `warning`
- Store available, semantic index not enabled → **`degraded`**
- Store + semantic enabled → `ok`

**hy embedder (separate surface)**

- `backend/memory/hy/settings.py` + `hy/bridge.py` can pass an SDK `embedder` config. That is **hy-memory SDK** retrieval, not the LangGraph store index used for promotion target namespaces. Do not conflate the two for Q3.

**Promotion protocol today**

```342:351:backend/memory/promotion.py
def _dedupe(
    candidate: PromotionCandidate, existing: Sequence[ExistingEntry]
) -> tuple[DedupeVerdict, tuple[str, ...], bool]:
    """Compare against the target namespace's current records.

    Returns ``(verdict, superseded promotion ids, candidate_is_older)``. Only
    exact key/source identity is compared here: semantic near-duplicates are a
    reviewer hint (needs an embedding and a judgement), not something this pure
    function can settle.
    """
```

Key-level `NEEDS_REVIEW` already covers: same key / different `source_ref`; same `source_ref` under another key. There is **no** semantic similarity input on `PromotionDecision` / `ExistingEntry`.

#### 2) Call-site policies (semantic is REVIEW **hint only**, never auto-merge)

Parent ADR (`prd.md` §3 / §5.2):

- Dedupe order: (1) `(namespace, key)` → (2) `source_ref` → (3) semantic near-neighbor **hint only** (`NEEDS_REVIEW`, never auto-merge).
- “语义 index 只用于给 `NEEDS_REVIEW` 附‘疑似重复’提示，**不改变 disposition**.”

Constraint that dominates all three policies: **`decide_promotion` must stay pure** (no I/O, no store, no embeddings). Any semantic work lives **outside** the protocol — observe / apply / review enrichment — same pattern as TTL (`ttl_expired` computed by caller) and ledger `detail`.

| Policy | When embedding/`asearch` runs | Cost | Interaction with purity | Fit to parent text |
|---|---|---|---|---|
| **A** — only when key-level dedupe already yields `NEEDS_REVIEW` / ambiguous | After `_dedupe` path that returns `needs_review` (typically disposition `REVIEW` + reason `needs_human_review`) | Lowest: rare competing-key / cross-key-same-source cases | Safe if enrichment is post-decide and does not feed back into `decide_promotion` | Matches §5.2 wording literally |
| **B** — on every observe/apply candidate before decide | Once per candidate before/around each `decide_promotion` | Highest: every style observe + every hy row; pays even for clear `DUPLICATE`/`NEW`/`SUPERSEDES` | Risk: tempting to expand `existing` or change inputs before decide; still cannot legally change disposition if kept hint-only, but burns index on refuse/promote paths | Answers Q3’s “每次去重都做” option; fights optional-index reality |
| **C** — post-decision enrichment on REVIEW ledger rows | After decide, only for rows with `disposition=REVIEW` (async/observe-time append into `detail` or parallel hint field) | Medium: all REVIEW rows (includes hy `MEMORY` with dedupe often `NEW`, plus stale / ambiguous) | Best purity: decide finishes first; hint is ledger/operator metadata via existing `PromotionLedger.append(..., detail=)` | Broader than §5.2’s “NEEDS_REVIEW” but still never auto-merge |

**Observe call-site today** (`observe_style_promotions`): read ledger → `decide_promotion` → optional append. No semantic step. Ledger already has `detail: str` for “operator-facing context the decision vocabulary cannot spell out” — natural attachment point for a near-dupe hint without mutating `PromotionDecision` shape.

**Important coverage gap if A is literal-only:** hy Slice D forces `REVIEW` via `trust_class=MEMORY` even when dedupe is `NEW`. Reviewers of those rows would **not** get near-dupe hints under strict A. Policy C covers them; a narrow “A∪ disposition=REVIEW” variant also would.

#### 3) Semantic index unavailable → REVIEW vs REFUSE vs skip-hint

Map to repo “failure is not data” / hy `DEGRADED` patterns:

| Pattern | What it means | Analog for missing semantic index |
|---|---|---|
| Reader / hy `DEGRADED` → `REFUSE(source_degraded)` | **Source read** itself failed; candidate content was not judged; still a closed disposition + ledger row | **Not** analogous: promotion source/reader can be healthy while embeddings are off |
| `RetrievalResult.DEGRADED` vs `EMPTY` | Absent store / `asearch` throw ≠ “no memories” | Must not treat “no semantic hits” as “no near-dupes” when index is off or search failed |
| Health `memory_store` `degraded` | Store up, semantic index disabled — system still runs | Infra signal; does not rewrite promotion dispositions |
| Ledger `NO_STORE` / `ledger_available=False` | Config fact; decisions still computed; writes skipped | Decisions without enrichment are OK; do not invent refusals |
| Closed dispositions | Only `PROMOTE` / `REVIEW` / `REFUSE` — **no silent skip of the decision** | “Skip” applies to the **hint**, not to the promotion decision |

**Verdict mapping for Q3’s “index 不可用时是 REVIEW 还是 REFUSE？”**

| Option | Compatible with repo? | Why |
|---|---|---|
| Flip disposition to **REFUSE** when index missing | **No** (for hint feature) | Would invent a new refusal axis (“infra incomplete”) and block measured `internal_fact` promotes whenever embeddings are off; contradicts optional index + BaseStore |
| Flip disposition to **REVIEW** when index missing | **No** for machine-promotable paths | Would make PROMOTE rate depend on embedding availability (non-deterministic across deploys); protocol would no longer be pure facts about candidate/source/key |
| **Skip-hint** (omit near-dupe enrichment; keep key-level decision) | **Yes** | Matches optional index; same family as “ledger unavailable → still decide, record=0”; must not claim “searched, found none” |

If a search is **attempted** and throws: surface as enrichment failure (omit hint or set an explicit `detail` token like `semantic_near_dupe:unavailable`), **do not** rewrite `dedupe` / `disposition`. That preserves “failure is not data.”

#### 4) MVP recommendation (one approach)

**Recommend policy A, implemented with C’s attachment site: post-decision, hint-only enrichment when key-level `dedupe == NEEDS_REVIEW`; when index/`asearch` unavailable → skip-hint.**

Concrete shape consistent with current code:

1. Keep `decide_promotion` / `_dedupe` unchanged (protocol purity).
2. In observe/apply (or a thin helper called after decide): **if** `decision.dedupe is NEEDS_REVIEW` **and** store present **and** `semantic_index_status().enabled` (or a successful prior index), `asearch` the **target** namespace with `candidate.body` (or claim text), collect top-k keys/ids as strings.
3. Pass that string into `ledger.append(..., detail=...)` (or append-only side channel). Never change `disposition` / `reason` / `dedupe` from the hint.
4. If index `None`, store `None`, or `asearch` raises → **skip-hint** (optionally `detail` notes unavailability). Decision stands.
5. Out of MVP: auto-merge, feeding neighbors into `ExistingEntry`, running embeddings on every candidate (B), forcing REVIEW/REFUSE on missing index.

**Trade-offs under XhsGrowthAgent constraints**

| | |
|---|---|
| Pros | Aligns with parent §5.2; minimal embedding spend; preserves pure `decide_promotion`; works when BaseStore/index absent; uses existing `detail` without new disposition vocabulary |
| Cons | hy `MEMORY` REVIEW rows with `dedupe=NEW` get no hint (Slice D reviewers less helped); near-dupes that share meaning but not key/`source_ref` on an otherwise `PROMOTE` path stay unflagged (by design — hint must not block promote) |
| vs B | Avoids N embeddings per observe pass and avoids pressure to pollute decide inputs |
| vs pure C | Lower cost than enriching every REVIEW; slightly worse hy coverage — product can widen later to “all REVIEW dispositions” without touching the protocol |

**Non-goals confirmed by docs:** `docs/memory-promotion.md` §11 — “不判语义重复…只作为审核提示，不在本函数内.”

### External References

- None required for the cost adjudication; LangGraph store index behavior is already documented in-repo (`index.py` module docstring + graph builder). External embedding pricing is irrelevant to the protocol choice (A vs B vs C) once hint-only + skip-on-unavailable is fixed.

### Related Specs

- `.trellis/spec/backend/directory-structure.md` — `promotion.py` pure protocol; `promotion_review.py` human close without re-running `decide_promotion`
- `.trellis/spec/backend/error-handling.md` — promotion human-review / TTL / policy_version scenarios; degraded patterns elsewhere (RQGM) as “explicit non-consumable,” analogous to skip-hint
- `.trellis/spec/backend/free-creation.md` — `asearch` without index may throw; callers degrade gracefully for listing (different domain; promotion should not treat throw as EMPTY near-dupe set)
- `.trellis/spec/backend/database-guidelines.md` — semantic ranking / cold-start caveats for relevance APIs

## Caveats / Not Found

- **No implementation** of semantic near-dupe hints exists yet in promotion observe/apply/review — only protocol comments + parent PRD open Q3.
- No dedicated research file under prior promotion tasks for this topic (research dir was empty before this write).
- Exact similarity threshold / top-k / which text field to embed (`body` vs structured style fields) is **not** decided in parent PRD; out of scope for the cost question but needed at implement time.
- Whether to widen MVP from strict A to “all `disposition=REVIEW`” (hy coverage) is a product delta on top of this recommendation; not contradicted by “never auto-merge,” only by §5.2’s narrower “NEEDS_REVIEW” wording.
