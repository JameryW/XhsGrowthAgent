# ADR-0006: Creative Memory contributes Evidence through a read-only proposal seam

## Status

Accepted

## Context

A Creator Model is meant to hold a creator's judgement, and `CONTEXT.md` already
says Creative Memory — derived Style DNA, conversion plays, reusable materials —
"may contribute Evidence to a Creator Model but is not itself the Creator Model."
Two facts made that sentence unusable:

- bootstrapping a model meant hand-authoring every `evidence_id`, `source_ref`,
  and claim in JSON, so in practice accounts carried an ungrounded model or none;
- the account already stores measured, row-level history — per-style
  `engagement_rate` and `sample_count`, per-play `avg_engagement_rate` and
  `proven_count`, per-material `effectiveness`, `reuse_count`, and
  `source_post_id`.

The tempting shortcut was to let the Creator Agent read Creative Memory directly,
or to auto-import observations into the model. Both break an existing invariant:
ADR-0002 established that feedback-derived learning stays pending until the
creator explicitly disposes of it, and the model only changes through a
creator-approved revision. Automatic import would have made measured popularity
silently become normative judgement.

There was also a concrete data hazard. `CreativeMemory.recall_style` is a
relevance API: small default limits, semantic ranking, and — decisively — a
fallback that fabricates cold-start styles (`default_warm`, …) when an account
has none. Projected as evidence, that fiction would have read as something the
creator measurably did.

## Decision

Introduce an append-free Evidence Proposal seam.

- **Direction of dependency is fixed.** `backend/creator_agent/` declares a
  narrow `CreatorContentObservationSource` protocol and never imports
  `backend/memory` or `backend/db/creative_memory`; the adapter lives on the
  content-production side and is injected at the HTTP boundary. A test asserts the
  import direction so the rule cannot rot.
- **Enumeration, not recall.** The adapter reads durable account-scoped rows
  (`list_styles` / `list_plays` / `list_materials`) and drops `default_*`,
  rows without a usable numeric measurement, and rows without a description.
- **Claims are renderings, not narratives.** Each claim states the measured rate
  and its sample count. No wording is added that the row does not support.
- **Confidence is shrunk by sample size** and is a reported property, never an
  applied one. An observation with no proven samples earns zero confidence.
- **Draft preferences are optional, conservative, and always `prefer`.** A draft
  appears only above confidence and sample thresholds, cites exactly its own
  evidence id, and leaves `applies_when` empty — deciding when a preference
  applies is the creator's judgement.
- **The scan budget is never the page size.** Each family is windowed by its own
  storage order — materials by soft-demotion `weight`, styles and plays by raw
  measured rate — while proposals rank by sample-shrunk confidence. Reusing one
  `limit` for both made a `limit=3` page return three confidence-0.178 rows and
  drop a confidence-0.711 observation that had never entered the window. The
  advisor now scans `max(60, limit * 4)` per family, clamped by the enumeration's
  100-row ceiling, and the page reports `total` plus a `truncated` flag so a
  bounded scan is never read as "the account has nothing else".
- **Nothing on this path writes.** No table, no endpoint that accepts a
  proposal, no "adopt all". The only way a proposal becomes model content is the
  creator submitting a new `CreatorModelDefinition` through `PUT /model`, which
  produces an approved revision and its immutable history snapshot.

## Consequences

Bootstrapping becomes an informed, human-paced act instead of JSON authoring, and
proposals dedupe against the Evidence Graph so an adopted item stops recurring.
Adoption is not one click: a creator still has to restate the definition they want,
which is the point — the friction is the consent boundary. Because evidence ids and
source refs are derived deterministically, a proposal, its adopted Evidence node,
and a later dedupe pass always agree, which also means a corrected claim wording
would read as a different evidence item rather than an update; wording changes are
therefore a contract change, not a cosmetic one. Keeping `NicheBenchmark` out is
deliberate: it is niche-scoped rather than account-owned, so it describes a market,
not this creator's history.
