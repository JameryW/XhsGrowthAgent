"""Node latency report — the P2 gate: is there a bottleneck to parallelize?

Usage::

    # from an exported performance log (list of entries) or {"events": [...]}
    python scripts/benchmarks/node_latency_report.py --events run.json

    # from the configured event store (Postgres or the in-memory fallback)
    python scripts/benchmarks/node_latency_report.py --thread <thread_id>

Exit code is 0 for every data outcome ("no data" is a finding, not a failure);
it is non-zero only for unusable arguments, so CI can run it safely.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.services.node_latency import aggregate  # noqa: E402


def _load_events(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for key in ("events", "performance_log", "entries"):
            if isinstance(raw.get(key), list):
                return [e for e in raw[key] if isinstance(e, dict)]
        raise SystemExit(f"{path}: expected a list or a dict with an 'events' list")
    if isinstance(raw, list):
        return [e for e in raw if isinstance(e, dict)]
    raise SystemExit(f"{path}: expected a JSON array of event entries")


async def _load_thread(thread_id: str) -> list[dict]:
    from backend.state.events import load_perf_log

    return await load_perf_log(thread_id, None)


def _print_report(report, source: str) -> None:
    print(f"source: {source}")
    if not report.has_data:
        print('\nNo node telemetry (kind:"node" with duration_seconds).')
        print("Verdict: cannot decide on parallelism — collect a real run first.")
        if report.skipped_entries:
            print(f"({report.skipped_entries} node entries had no numeric duration)")
        return

    print(f"node entries: {report.node_entries} | skipped: {report.skipped_entries}")
    print(
        f"total node time: {report.total_node_seconds:.1f}s | "
        f"wall clock: {report.wall_clock_seconds:.1f}s | "
        f"serial ratio: {report.serial_ratio:.2f}"
    )
    print(
        f"\n{'AGENT':<24} {'CALLS':>5} {'TOTAL':>9} {'MEAN':>8} {'P95':>8} {'SHARE':>7} {'ERR':>4}"
    )
    print("-" * 72)
    for a in report.agents:
        print(
            f"{a.agent:<24} {a.calls:>5} {a.total_seconds:>8.1f}s "
            f"{a.mean_seconds:>7.1f}s {a.p95_seconds:>7.1f}s "
            f"{a.share:>6.0%} {a.errors:>4}"
        )
    print(f"\nVerdict: {report.verdict}")
    for reason in report.reasons:
        print(f"  - {reason}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--events", type=Path, help="JSON export of performance-log entries")
    group.add_argument("--thread", help="thread id to read from the configured event store")
    args = parser.parse_args(argv)

    if args.events:
        report = aggregate(_load_events(args.events))
        _print_report(report, str(args.events))
    else:
        report = aggregate(asyncio.run(_load_thread(args.thread)), threads=1)
        _print_report(report, f"thread {args.thread}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
