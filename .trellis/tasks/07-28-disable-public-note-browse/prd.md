# Disable public note body browsing

## Problem

Creator Center statistics imports are intended to stay on the bound Creator
Center surface. The public-note caption enrichment path can still navigate to
`www.xiaohongshu.com/explore/<note>` when the legacy
`CREATOR_STATS_MAX_BODY_VISITS` setting is positive. A stale deployment
environment can therefore re-enable the highest-risk main-site browsing path.

## Goal

Make public note pages unreachable from the Creator Center sync transport while
preserving overview/list imports and Creator Center note-detail metrics.

## Scope

- Remove the public explore body-scrape execution path and its page navigation.
- Keep `body_filter`/legacy configuration inputs accepted where needed for
  compatibility, but make them no-ops and document that public note bodies are
  permanently disabled.
- Keep `body_text` values already supplied by Creator Center payloads intact.
- Update tests, environment/configuration docs, and the browser-safety spec.
- Do not change explicit manual publishing, login, or Creator Center detail
  navigation behavior in this task.

## Acceptance criteria

1. No Creator Center sync execution can call the public-note body scraper or
   navigate to `www.xiaohongshu.com/explore/<note>`.
2. Positive legacy body-visit settings do not re-enable public browsing.
3. Creator Center overview/list/detail metric capture remains unchanged.
4. Existing compatibility call signatures do not fail solely because a
   `body_filter` or legacy setting is present.
5. Focused creator-stats tests, Ruff, mypy, formatting, and diff checks pass.
