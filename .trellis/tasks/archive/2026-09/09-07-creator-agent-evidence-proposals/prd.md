# Creator Agent Evidence Proposals from Creative Memory

## Problem

A Creator Model can currently only be populated by hand. `PUT /model` accepts a
complete `CreatorModelDefinition`, and the only automatic path in
`CONTEXT.md`/ADR-0002 is a feedback-derived Learning Signal that a creator
reviews. Meanwhile the account already holds durable, measured observations from
content production — Style DNA with historical `engagement_rate` and
`sample_count`, Conversion Plays with `avg_engagement_rate`, `avg_save_rate` and
`proven_count`, and Materials with `source_post_id`, `source_engagement_rate` and
`effectiveness`.

That is exactly the material `CONTEXT.md` says may contribute Evidence to a
Creator Model without being one, yet nothing turns it into inspectable,
traceable Evidence candidates. A creator who wants their judgement grounded in
their own measured history must retype it into JSON, and any evidence they add
has no link back to the observation it came from.

## Goal

Add a read-only Evidence Proposal surface: project durable Creative Memory
observations into traceable Evidence candidates (plus an optional draft
Preference the creator may adopt), deduplicated against what the account
already cites.

1. every proposal names a real source: `source_kind=creator_content` and a
   `source_ref` that points at the specific durable row it came from;
2. claims are deterministic renderings of measured values — no invented narrative,
   no inferred intent beyond the numbers;
3. confidence is computed from the measured rate and its sample size and is
   **reported**, never applied;
4. observations already represented in the account's Evidence Graph are not
   re-proposed;
5. ordering and proposal identity are stable across repeated calls;
6. nothing on this path can mutate a Creator Model, a revision, a Learning
   Signal, or Creative Memory itself;
7. degraded or empty Creative Memory yields an empty list, never an error;
8. memory and Postgres adapters remain behaviorally equivalent, and
   HTTP/OpenAPI/generated models/docs/ADR/CONTEXT/backend specs stay synchronized.

## Domain contract

Canonical terms are defined in `CONTEXT.md`.

`Evidence Proposal` is a traceable, read-only suggestion of one Evidence node —
optionally with a draft Preference citing it — derived from a durable Creative
Memory observation. It is a proposal, not a model change: the only way it can
become part of a Creator Model is the creator approving a new Model Revision
through the existing `PUT /model` path, which then produces the immutable
revision snapshot added in the previous increment.

The seam deliberately lives outside both subsystems. `backend/creator_agent/`
declares a narrow observation Protocol and must not import `backend/memory/` or
`backend/db/creative_memory.py`; the adapter that reads Creative Memory lives on
the memory side and is injected. This keeps the Creator Model core independent
of how content production stores its history.

## Required substrate (and two rejected ones)

Read the durable enumeration in `backend/db/creative_memory.py`:
`list_styles(account_id)`, `list_plays(account_id)`, `list_materials(account_id)`.

- **Rejected: `CreativeMemory.recall_style/_plays/_materials`.** They are
  relevance APIs: they apply semantic query ranking and small default limits,
  and `recall_style` returns synthetic `_default_styles()` (`default_warm`, …)
  when the account has no real styles. Cold-start fiction must never become
  creator evidence.
- **Rejected: `creator_stats` `CreativeSuggestion`.** Its `evidence` field is a
  free-text render string with no stable source identity, and suggestions are
  advice derived from analysis, not an observation of what the creator did.

Rows whose `style_id`/`play_id`/`material_id` is missing, or that start with
`default_`, are skipped. Any field needed for a claim that is absent or
non-numeric makes that row produce no proposal rather than a weaker one.

## Model

```python
class ContentObservationKind(StrEnum):
    STYLE = "style"
    PLAY = "play"
    MATERIAL = "material"

class ContentObservation(BaseModel):
    """One durable Creative Memory observation, already account-scoped."""
    kind: ContentObservationKind
    source_id: str
    description: str          # tone/visual_style, trigger_condition, or tags
    measured_rate: float      # engagement/save rate or effectiveness, 0..1
    sample_count: int = 0
    observed_at: str = ""

class EvidenceProposal(BaseModel):
    proposal_id: str          # stable: "prop_" + sha256(kind|source_id)[:16]
    evidence: Evidence        # source_kind creator_content,
                              # source_ref "creative-memory://{kind}/{source_id}"
    draft_preference: Preference | None
```

`evidence.evidence_id` is derived from the same stable identity
(`ev_{kind}_{source_id}`) so approving a proposal creates an Evidence node that
a later dedupe pass recognizes and never re-proposes.

Source references are `content_memory`-namespaced and stable:
`creative-memory://style/{style_id}`, `creative-memory://play/{play_id}`,
`creative-memory://material/{material_id}`.

### Claim text

Deterministic and numeric, e.g. for a style
`风格「{tone}/{visual_style}」历史互动率 {rate:.3f}（样本 {n}）`; for a play
`打法「{trigger_condition}」平均互动率 {rate:.3f}、收藏率 {save:.3f}（验证 {n} 次）`;
for a material `素材「{category}」复用效果 {effectiveness:.3f}，来源笔记 {source_post_id}`.
No adjectives that the data does not support.

### Confidence

`confidence = measured_rate * shrinkage`, where
`shrinkage = sample_count / (sample_count + 5)`. The adapter maps an absent or
non-numeric sample count to `0`, so an observation with no proven samples earns
`0` confidence: it stays traceable and visible, but never looks convincing.
Materials use `effectiveness` as the rate and `reuse_count` as the sample count.
The result is clamped to `[0, 1]` and rounded to 3 decimals. The prior of 5 is a
named module constant so a future change is auditable; it is an implementation
detail and is not exposed in the proposal payload.

### Draft preference

Only propose a Preference when the observation is strong enough to be worth the
creator's attention: `confidence >= 0.3` and `sample_count >= 3`. It cites the
proposal's own `evidence_id`, carries `strength = confidence`, `stance = prefer`,
`label` derived from the same description used in the claim, and a `rationale`
that repeats the measured sentence. `applies_when` is left empty — deciding when a
preference applies is the creator's judgement, not the projection's. Stance is
never `avoid`: a low measured rate is not evidence of an aversion.

## Advisor seam

`CreatorAdvisor` gains one read method and an optional constructor dependency:

```python
CreatorAdvisor(repository, content_observations=None)

async def list_evidence_proposals(
    account_id, *, limit: int = 50, min_confidence: float | None = None
) -> list[EvidenceProposal]
```

Behavior when no observation source is wired: return `[]` (no HTTP 500, no
silent import). The account is normalized before any read. `limit` is validated
`1..100` and `min_confidence`, when provided, is validated `0..1`; both raise
`ValueError` at the seam so the route renders `ERROR_VALIDATION`.

Dedupe is against the existing Evidence Graph projection: drop any proposal whose
`source_ref` already appears on an Evidence node for that account. It must not
consult the current model revision — the current model cannot un-cite history.

## HTTP adapter

One authenticated, account-scoped read:

```text
GET /api/creator-agent/model/evidence-proposals?account_id=...&limit=50&min_confidence=0.3
```

Returns the existing `ApiResponse` envelope with a JSON list, calls
`require_owned_account` before any read, and is strictly side-effect free.
`limit`/`min_confidence` out of range or blank `account_id` → `ERROR_VALIDATION`.
No POST/PUT/DELETE variant exists on this path by design.

## Persistence

None. This increment adds no table and no write. Creative Memory is read through
its existing durable enumeration, which already falls back to process memory when
no pool is ready, so adapter parity is inherited rather than duplicated.

## Safety and compatibility

- Read-only: `CreatorAdvisor.decide`, `PUT /model`, Learning Signal review,
  Evidence Graph, Decision Dataset, Action and revision-history contracts are
  unchanged, and existing Creator Agent tests must stay green.
- A creator with no Creative Memory sees an empty list, not an error and not
  defaults.
- Nothing here writes Evidence; adoption remains an explicit, creator-approved
  Model Revision, preserving ADR-0002.

## Acceptance criteria

- Style/play/material rows each produce a proposal with the documented
  `source_ref`, `evidence_id`, deterministic claim, and clamped confidence.
- A cold-start account with only `default_*` styles, or with no rows, produces no
  proposals; a row with a missing/non-numeric measured field produces none.
- Confidence math matches the formula for zero, small, and large sample counts,
  and is monotonically increasing in both rate and sample count.
- Draft preferences appear only above both thresholds, always with `stance=prefer`,
  empty `applies_when`, `strength == confidence`, and an `evidence_ids` list
  containing exactly the proposal's own evidence id.
- Calling twice returns identical ids, order, and payload; adding an equivalent
  Evidence node to the model removes that proposal from the list.
- Cross-account reads return nothing about another account's observations.
- The `backend/creator_agent` package imports neither `backend.memory` nor
  `backend.db.creative_memory`.
- OpenAPI (static + dynamic), generated models, docs, ADR, CONTEXT, and backend
  specs are synchronized.
- Focused tests, Ruff, Mypy, contract checks, and `git diff --check` pass.

## Out of scope

- Writing Evidence, Preferences, or Policies; any auto-apply or "accept all"
  mutation endpoint.
- Ranking or re-deciding existing suggestions; changes to
  `creator_stats`/`CreativeMemory` recall behavior.
- Niche benchmarks and `NicheBenchmark` data (niche-scoped, not account-owned,
  so not creator evidence).
- Semantic similarity dedupe, claim wording changes by LLM, or any model call on
  this path.
- Frontend UI for reviewing or adopting proposals.
