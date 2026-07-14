# Real Browser Creator-Data Import

## Problem

The Creator Center panel currently starts with `dry_run=true`, which imports a bundled fixture instead of the bound account's actual Creator Center data. The same HTTP endpoint can fall back to a caller-supplied cookie when no bound browser/CDP session is available. This makes a user-facing import ambiguous and can leave the account's data and inferred niche disconnected from its real notes.

The affected account has imported real note titles but no body/tags. Its topic is AI-model and coding commentary, while the existing `数码` keyword vocabulary does not include those terms. As a result, niche resolution returns `cold_start` with `notes_present_but_no_keyword_match`.

## Goal

Make the product-facing Creator Center import browser-backed and explicitly real-data-only, then make the panel communicate that contract clearly. Ensure the existing note-based niche inference recognizes AI/software content as `数码`. While doing so, make the Analytics page's information hierarchy and responsive layout coherent rather than visually crowded.

## Requirements

1. `POST /api/analytics/creator-stats/sync` must use the selected account's bound, running CDP browser session for product imports.
   - It must never silently import the bundled fixture.
   - It must not fall back to a manually supplied cookie on the product route.
   - When the account has no reachable CDP binding, return a structured, actionable result and leave existing imported data unchanged.
2. Keep fixture support only in the internal service/CLI test path so automated tests can continue to exercise normalization and persistence without a live browser.
3. Update `CreatorStatsPanel` and its API contract:
   - Remove the dry-run toggle and cookie-entry fallback from the user-facing import UI.
   - Default the request to a real browser sync and label the action/hint as such.
   - Surface a clear prerequisite/error when the bound browser is unavailable; preserve loading, analysis, period selection, refresh, and success feedback.
   - Update both English and Chinese translations.
4. Extend `数码` niche keywords for AI-model/software-development terms so the imported real note titles infer a non-cold-start niche.
5. Improve the Analytics page layout without changing its data behavior:
   - Keep the import panel, page heading/controls, metrics, charts, insights, costs, and table in a clear visual order.
   - Correct responsive wrapping, density, and spacing for small and wide screens.
   - Avoid duplicate or competing visual headers and preserve all current actions.
6. Add regression coverage for the browser-only API route, unavailable-browser behavior, fixture isolation, and AI/software note inference. Preserve existing service-level fixture coverage.

## Acceptance Criteria

- A panel click results in `source="creator_statistics"`, never `source="fixture"`.
- A missing CDP binding returns an actionable failure and performs no fixture import.
- The UI contains no sample/dry-run import control or cookie fallback field.
- Real imported AI/software note titles resolve the account niche to `数码` with source `inferred`.
- The Analytics page remains legible at narrow and desktop widths, with controls and data modules following one consistent layout hierarchy.
- Backend lint/type checks/tests and frontend type-check/build pass.

## Non-goals

- Removing fixture support from lower-level service or CLI test tooling.
- Changing workflow/publishing dry-run behavior outside Creator Center statistics import.
- Adding LLM-based niche classification; this change remains deterministic and explainable.
