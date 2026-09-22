# Creative Memory substrate for evidence proposals

Findings from reading the actual code, recorded so the constraints survive
compaction.

## Durable enumeration (use this)

`backend/db/creative_memory.py` — account-scoped, no synthetic data:

- `list_styles(account_id, *, limit=20) -> list[dict]` (:322)
- `list_plays(account_id, *, niche="", limit=20) -> list[dict]` (:411)
- `list_materials(account_id, ...) -> list[dict]` (:515)
- `_upsert_style_on_conn` / `upsert_play` / `upsert_material` are the writers.
- Same adapter convention as the Creator Agent: Postgres when a pool is ready,
  process memory otherwise, reset by `_reset_memory_store()` (:71).

Fields available per row type are TypedDicts in `backend/memory/types.py`:

- `StyleDNA` (:11): `style_id`, `tone`, `visual_style`, `voice_patterns`,
  `engagement_rate`, `sample_count`, `last_used`.
- `ConversionPlay` (:27): `play_id`, `trigger_condition`, `title_formula`,
  `avg_engagement_rate`, `avg_save_rate`, `content_type`, `niche`,
  `proven_count`, `last_proven`.
- `MaterialEntry` (:44): `material_id`, `category`, `content`,
  `source_post_id`, `source_engagement_rate`, `tags`, `reuse_count`,
  `effectiveness`, `weight`, `created_at`.
- `NicheBenchmark` (:59) is keyed by `niche`, **not** by account → excluded from
  creator evidence because it is not account-owned observation.

## Rejected surfaces

`CreativeMemory.recall_style` (`backend/memory/creative.py:74`) is a relevance
API, not an enumeration:

- default `limit=3`, semantic `store.asearch` ranking;
- dedupes by `style_id` keeping the higher `sample_count`;
- drops `default_` rows **only when real styles exist**, then
  `return chosen if chosen else self._default_styles()` (:144);
- `_default_styles()` (:567) fabricates cold-start styles (`default_warm`, …)
  with template voice patterns.

So `recall_*` can hand the proposal layer invented rows. `recall_plays` (:146)
and `recall_materials` (:204) share the same small-limit ranking shape.

`backend/services/creator_stats/types.py:267` `CreativeSuggestion.evidence` is a
rendered free-text string (e.g. `notes=5;avg_er=0.12`) with no stable id, and
`suggestions_from_analysis` (`suggestions.py:85`) derives advice from analysis
rather than recording one observation. Not usable as traceable Evidence.

## How the live chain already does optional enrichment

`build_mode_creative_context` / `CreativeMemory` are consumed inside bare
best-effort blocks that degrade to unchanged behavior:
`backend/agents/content_strategist.py:68-75`, `backend/agents/copywriter.py:91-102`,
`backend/api/routes/free.py:309-330`. Routes obtain the store as
`store = getattr(graph, "store", None)` (`free.py:236,264,360,…`) and construct
`CreativeMemory(account_id, store=store)`.

## Creator Model contract being reused

- `Evidence` (`backend/creator_agent/models.py`): `evidence_id`, `source_kind`,
  `source_ref` (max 500), `claim` (max 2000), `observed_at`, `confidence` 0..1.
- `EvidenceSource.CREATOR_CONTENT` already exists — no enum change needed.
- `Preference` requires `evidence_ids` with `min_length=1`, so a draft
  Preference must cite the proposal's own evidence id.
- Dedupe input: `CreatorAdvisor.list_evidence` → `EvidenceGraphEntry.evidence.source_ref`,
  which is the read projection added in increment #563 and must not be widened.
