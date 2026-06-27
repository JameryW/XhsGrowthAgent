# Fix Blank Page After Leaving Review

## Problem

After opening the content review page and then navigating to another page, the frontend can render a blank page.

## Scope

- Reproduce and identify the frontend failure path around `/review` navigation.
- Fix the review page/store/router behavior that causes blank rendering after leaving review.
- Keep changes scoped to frontend navigation/review behavior.

## Acceptance Criteria

- Navigating to `/review` and then to dashboard, analytics, history, or home does not blank the app.
- The fix does not break review queue loading or review submission behavior.
- Frontend type-check/build passes, or any remaining verification gap is documented.
