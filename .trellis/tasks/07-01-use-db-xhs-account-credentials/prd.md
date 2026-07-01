# Use DB XHS Account Credentials for Trend Tools

## Problem

The Settings UI stores XHS account credentials in the database, but the trend
scouting tools only read `XHS_COOKIE` / `XHS_USER_ID` from environment-backed
settings. Workflows started for a DB account therefore ignore that account's
saved cookie and may fall back to stale or malformed env credentials.

## Goal

Make trend scouting XHS API tools prefer the workflow account's database
credentials, falling back to the active account or environment settings when
database credentials are unavailable.

## Acceptance Criteria

- `TrendScoutAgent` passes the workflow `account_id` to XHS trend tools.
- `backend/tools/xhs/trending.py` resolves an `XHSClient` from DB credentials
  for that account before falling back to existing env settings.
- Missing DB/pool state degrades gracefully to current behavior.
- Cookie values are normalized enough to avoid newline/control-character header
  failures.
- Unit tests cover DB-preferred credentials and env fallback.
