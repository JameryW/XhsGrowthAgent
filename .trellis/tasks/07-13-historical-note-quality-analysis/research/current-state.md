# Current-State Research

## Existing source of truth

- Browser-backed import persists `NoteStats` in `creator_note_stats` through
  `backend/services/creator_stats/pipeline.py` and `backend/db/creator_stats.py`.
- A note has title, optional body snippet, view/like/comment/collect/share
  metrics, publication time, content type, tags, and a normalized engagement
  rate.
- `backend/db/creator_stats.py:list_note_stats` defaults to 100 rows and caps
  supplied limits at 500. The new report must explicitly escape the display
  reader's normal 100-row limit and disclose its scope.

## Existing analysis that must remain intact

- `analyze_notes` derives high-performing tone/topic/format/title patterns and
  feeds style-memory deposits.
- `suggestions_from_analysis` supplies mode-specific advice for trend, brief,
  and free creation.
- `GET /creator-stats/{account_id}/analysis` is an immediate style-pattern
  read, while workflow RQGM evaluation scores a single draft. Neither is an
  account-wide historical quality report.

## Design decisions

1. Introduce a pure `quality.py` service rather than overloading style-DNA
   findings or RQGM draft evaluation.
2. Use durable imported history only; no live browser action, database mutation,
   fixture fallback, or external LLM request.
3. Return stable machine-readable keys for grade, confidence, dimensions, and
   report scope; format Chinese/English display labels in the frontend.
4. Include metric evidence on every insight so the report explains why a
   strength, weakness, or recommendation exists.
5. Treat 0–2 notes as low confidence and omit an absolute score. Never convert
   missing title/body data into a negative content-quality judgement.
6. Expose the same report via REST, `xhs_creator_quality`, and a focused
   Analytics-page component; preserve compatibility of existing creator tools.

## Verification focus

- pure scorer: normal/powerful/weak/low-data inputs, percent- and
  fraction-scale rates, no divide-by-zero, stable priority order;
- DB/API: all history (including >100 rows) reaches the report and endpoint
  remains read-only;
- omp: structured result and human-readable multi-line content;
- frontend: typed contract, i18n, empty/error states, mobile overflow check.
