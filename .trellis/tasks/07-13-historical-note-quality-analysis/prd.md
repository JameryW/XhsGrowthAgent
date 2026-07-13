# Historical Note Creative-Quality Analysis

## Problem

The product can import durable Creator Center account and note statistics, and it can
already derive high-performing style patterns. It does not yet give a creator a
single, evidence-backed account-level answer to these questions:

- What is the overall quality signal across my historical imported notes?
- Which creative capabilities are currently strong?
- Which capabilities are holding performance back?
- What should I change in the next few posts to close those gaps?

Individual RQGM evaluations are intentionally not reused for this feature: they
evaluate a workflow draft, while this feature evaluates the account's durable
historical Creator Center snapshot.

## Product outcome

On the Analytics page, an account with imported Creator Center notes can view a
historical creative-quality report. The same report is available to omp so an
agent can use it during a conversation. The report is generated locally from
the account's full persisted note history, never from sample data or a remote
LLM call.

## Data flow

```text
Bound browser Creator Center responses
  -> durable creator_note_stats rows (title/body snippet + metrics + tags)
  -> pure historical-quality analyzer (all persisted notes for the account)
  -> GET /api/analytics/creator-stats/{account_id}/quality
  -> Analytics UI and xhs_creator_quality omp tool
```

The analysis is read-only. It must not re-sync the browser, write Creative
Memory, alter imported rows, or expose cookies / non-allowlisted profile data.

## Report contract

The API response's `data` object must include:

- `account_id`, `total_notes`, `notes_analyzed`, and `scope`
- `overall_score` (0–100 when the sample is adequate), stable `grade`, and
  `confidence` (`low`, `medium`, or `high`)
- a concise, evidence-backed `summary`
- four explainable quality dimensions:
  `engagement`, `save_value`, `title_craft`, and `consistency`
- separate `strengths`, `weaknesses`, and prioritized `recommendations`, each
  with a concrete metric-based evidence string and related note IDs where
  applicable
- a defined low-data response (`insufficient_data` / `cold_start`) instead of
  a misleading zero-quality judgement

Quality is a performance-and-title-signal assessment, not a claim to judge
visual aesthetics or body-copy quality when those signals were not imported.
The summary and UI must communicate that limit through confidence/scope rather
than inventing unsupported findings.

## Scoring principles

The evaluator is deterministic and pure so reports are repeatable and testable.
It normalizes historical engagement rates with the existing creator-stats
helper, aggregates account-level rates from all analyzed notes, and derives a
transparent weighted score from:

1. interaction signal (engagement rate),
2. save value (collects per view),
3. title craft (non-empty, readable-length, and recognized hook coverage), and
4. consistency (performance spread together with non-zero engagement).

Thresholds are product heuristics, not an external platform benchmark. Every
weakness and recommendation must point to the account's own observed metric.
Do not penalize a missing optional body snippet as poor copywriting.

## Historical scope

The quality endpoint must analyze the full persisted note history for the
account rather than inheriting the existing display/API page limit. It must
return both `total_notes` and `notes_analyzed` so any future cap is visible to
the client. A regression test must prove that more than the normal 100-note
reader limit is included.

## UX

Add a dedicated, compact `CreatorQualityPanel` below the creator import panel
on the Analytics data view.

- It loads the account-level report for the active account without triggering
  a browser import.
- It shows a score/grade, sample confidence, summary, dimension cards,
  strengths, weaknesses, and the top actionable recommendations.
- Loading, empty/low-data, and failure states are explicit and non-blocking.
- It remains readable on a 390px viewport with no page-level horizontal
  overflow.
- All user-visible strings use both Chinese and English locale files.

## omp

Register `xhs_creator_quality` in `xhsagent-ext`.

- Input: `account_id` only.
- It calls the quality endpoint and renders a concise multi-line overview with
  score/grade/confidence, strengths, gaps, and up to three priority actions.
- It preserves the full structured report in `details` for downstream use.
- Empty history returns a helpful import-first message, not an exception.

## Acceptance criteria

1. Imported historical notes produce a deterministic report with all required
   sections, metric evidence, and actionable shortfall suggestions.
2. Empty and 1–2 note histories return an honest low-confidence response and
   never claim a zero quality score as fact.
3. The report reads all persisted account notes, including a test fixture with
   more than 100 rows.
4. The endpoint, omp tool, and Analytics UI use one compatible response
   contract.
5. Existing creator import, style analysis, and mode-specific suggestions keep
   working unchanged.
6. Unit/API tests, Ruff, Mypy, frontend type-check, and production build pass;
   the page is visually checked at desktop and 390px widths with mocked APIs.

## Non-goals

- Running a new LLM or evaluating visual assets that are not part of the
  imported historical data.
- Replacing workflow-level RQGM draft evaluation.
- Changing the browser-only import contract or exposing fixture imports in the
  product UI.
