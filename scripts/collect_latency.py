#!/usr/bin/env python3
"""Collect + aggregate HTTP request latency from backend container logs.

Requires the latency instrumentation (backend/api/latency.py) enabled via
XHS_LATENCY_LOG=1 in the backend container env. Emits one JSON line per
sampled request to the xhs_growth.api.latency logger:

    {"event":"http_latency","endpoint":"/status","thread_id":"...",
     "phase":"completed","total_ms":12.3,"aget_state_ms":4.1,
     "db_ms":1.2,"serialize_ms":3.0}

Usage:
    scripts/collect_latency.py                         # tail backend-xhs live
    scripts/collect_latency.py --since 1h              # last 1h of logs
    scripts/collect_latency.py --container other       # different container
    scripts/collect_latency.py --file logs.txt        # aggregate a saved file
    scripts/collect_latency.py --file -                # read stdin

Output: per-endpoint p50/p95/avg/count table + per-segment p50 + phase
breakdown. Pure stdlib — no jq dependency (the project is Python-first).

Exit 1 if no latency lines found, 2 on bad args.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

# backend/api/latency.py emits via json.dumps(..., ensure_ascii=False), which
# puts a space after the colon (``"event": "http_latency"``). Older log lines
# may be compact (``"event":"http_latency"``). Tolerate any whitespace around
# the colon so the filter matches real prod output.
_EVENT_MARKER = re.compile(r'"event"\s*:\s*"http_latency"')


def _fetch_lines(args: argparse.Namespace) -> Iterable[str]:
    """Yield raw log lines containing a latency JSON payload."""
    if args.file == "-":
        for line in sys.stdin:
            if _EVENT_MARKER.search(line):
                yield line
        return
    if args.file:
        with open(args.file, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if _EVENT_MARKER.search(line):
                    yield line
        return

    cmd = ["podman", "logs"]
    if args.since:
        cmd += ["--since", args.since]
    cmd.append(args.container)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    # podman logs writes to stderr too; merge both streams.
    for line in (proc.stdout + proc.stderr).splitlines():
        if _EVENT_MARKER.search(line):
            yield line


def _extract_json(line: str) -> dict[str, Any] | None:
    """Pull the JSON object out of a log line (strip leading timestamp/logger)."""
    idx = line.find("{")
    if idx < 0:
        return None
    try:
        obj = json.loads(line[idx:])
    except json.JSONDecodeError:
        return None
    return obj if obj.get("event") == "http_latency" else None


def _pct(values: list[float], pct: float) -> float:
    """Percentile (0-100) of a list; 0.0 when empty."""
    if not values:
        return 0.0
    s = sorted(values)
    # nearest-rank method (matches the rough p50/p95 used for triage)
    k = max(0, min(len(s) - 1, int(round((pct / 100.0) * (len(s) - 1)))))
    return s[k]


_SEGMENTS = ("aget_state", "db", "count", "serialize")


def aggregate(records: list[dict[str, Any]]) -> None:
    by_ep: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_ep[r.get("endpoint", "?")].append(r)

    print(f"{'endpoint':<22} {'n':>5} {'p50_ms':>8} {'p95_ms':>8} {'avg_ms':>8}   segment p50 (ms)")
    print("-" * 80)
    for ep in sorted(by_ep):
        rows = by_ep[ep]
        totals = [float(r.get("total_ms", 0) or 0) for r in rows]
        seg_p50 = {
            seg: _pct([float(r.get(f"{seg}_ms", 0) or 0) for r in rows], 50) for seg in _SEGMENTS
        }
        seg_str = "  ".join(f"{s}={seg_p50[s]:.1f}" for s in _SEGMENTS if seg_p50[s] > 0)
        print(
            f"{ep:<22} {len(rows):>5} "
            f"{_pct(totals, 50):>8.1f} {_pct(totals, 95):>8.1f} "
            f"{statistics.mean(totals):>8.1f}   {seg_str}"
        )

    print()
    print("Phase breakdown (total_ms p50 by endpoint | phase):")
    by_ep_phase: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in records:
        ep = r.get("endpoint", "?")
        phase = r.get("phase", "") or "(none)"
        by_ep_phase[(ep, phase)].append(float(r.get("total_ms", 0) or 0))
    for (ep, phase), totals in sorted(by_ep_phase.items()):
        print(f"  {ep} [{phase}] n={len(totals):<4} p50={_pct(totals, 50):.1f}ms")


def main() -> int:
    p = argparse.ArgumentParser(description="Aggregate HTTP latency from backend logs.")
    p.add_argument("--container", default="backend-xhs", help="podman container name")
    p.add_argument("--since", default="", help="podman --since value (e.g. 1h, 30m)")
    p.add_argument("--file", default="", help="read from file (- for stdin) instead of podman")
    args = p.parse_args()

    records: list[dict[str, Any]] = []
    for line in _fetch_lines(args):
        obj = _extract_json(line)
        if obj is not None:
            records.append(obj)

    if not records:
        print("No http_latency lines found.", file=sys.stderr)
        print(
            "Ensure XHS_LATENCY_LOG=1 is set on the backend container env and that "
            "traffic hit an instrumented endpoint (/status /list /account-totals "
            "/evaluation/result).",
            file=sys.stderr,
        )
        return 1

    aggregate(records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
