# Fix collect_latency.py marker space mismatch with json.dumps output

## Goal

`scripts/collect_latency.py` (PR #485) uses `_EVENT_MARKER = '"event":"http_latency"'` (no space) to filter log lines. But `backend/api/latency.py` emits via `json.dumps(payload, ensure_ascii=False)` which produces `"event": "http_latency"` (space after colon, JSON default). Marker never matches → collect script reports "No http_latency lines found" on real prod logs. Blocks the instrumentation AC data-collection step.

## Evidence (prod, 2026-08-06)

```
$ podman logs xhs-growth | grep http_latency | tail -5 > /tmp/s.txt
$ python scripts/collect_latency.py --file /tmp/s.txt
No http_latency lines found.   # ← 5 real lines in file
```
Line format: `{"event": "http_latency", "endpoint": "/list", ...}` (space after colon).
Marker: `"event":"http_latency"` (no space). Mismatch.

## Requirements

- Make line filtering space-tolerant so it matches both `"event":"http_latency"` and `"event": "http_latency"` (and any spacing).
- Minimal: normalize by stripping spaces around `:` for the marker check, OR use a regex tolerant of optional whitespace.
- Keep _extract_json working (it finds first `{` and json.loads — already space-tolerant).

## Acceptance Criteria

- [ ] collect script finds lines from real prod logs (the 5-line sample)
- [ ] test added covering both spaced and unspaced markers
- [ ] aggregate output sane (per-endpoint p50/p95/avg + per-segment p50)
- [ ] ruff check + format --check + mypy green
- [ ] full pytest green

## Out of Scope

- latency.py emit format (don't change emit to compact JSON — keep readable)
- other collect script features

## Technical Notes

- `_EVENT_MARKER` line 36; used in `_fetch_lines` 3 places (stdin, file, podman logs)
- `_extract_json` already tolerant (finds `{`)
- Simplest: replace substring check with regex `r'"event"\s*:\s*"http_latency"'` search, or strip all spaces from line before marker check
