"""Signal inventory CLI — what did this run's timeline actually record?

Usage::

    # from an exported performance log (list of entries) or {"events": [...]}
    python scripts/benchmarks/signal_inventory.py --events run.json

    # from the configured event store (Postgres or the in-memory fallback)
    python scripts/benchmarks/signal_inventory.py --thread <thread_id>

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

from backend.services.signal_inventory import inventory  # noqa: E402


def _load_events(path: Path) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        for key in ("events", "performance_log", "entries"):
            if isinstance(raw.get(key), list):
                return list(raw[key])
        raise SystemExit(f"{path}: expected a list or a dict with an 'events' list")
    if isinstance(raw, list):
        return list(raw)
    raise SystemExit(f"{path}: expected a JSON array of event entries")


async def _load_thread(thread_id: str) -> list[dict]:
    from backend.state.events import load_perf_log

    return await load_perf_log(thread_id, None)


def _print_report(report, source: str) -> None:
    print(f"source: {source}")
    if not report.has_data:
        print("\nNo events for this source.")
        print("Verdict: nothing recorded — collect a real run first.")
        if report.malformed_entries:
            print(f"({report.malformed_entries} malformed entries skipped)")
        return

    kinds = ", ".join(f"{name} {count}" for name, count in report.by_kind)
    print(f"entries: {report.total_entries} | kinds: {kinds}")
    if report.kindless_node_entries:
        print(f"  (of which {report.kindless_node_entries} node entries carry no kind — pre-S2)")
    if report.unknown_kinds:
        print(f"  unknown kinds: {', '.join(report.unknown_kinds)}  <-- declaration drift")
    if report.malformed_entries:
        print(f"  malformed entries: {report.malformed_entries}")

    progress = report.progress
    if progress.emitted:
        reasons = ", ".join(f"{name} {count}" for name, count in progress.by_reason)
        print(f"\nprogress signals: {progress.emitted} ({reasons})")
        if progress.windows:
            print(f"  windows: {', '.join(str(w) for w in progress.windows)}")
        for sample in progress.samples:
            print(f"  - {sample['reason']} window={sample['window']} evidence={sample['evidence']}")
    else:
        print("\nprogress signals: none recorded")

    verification = report.verification
    if verification.recorded:
        tiers = ", ".join(f"{name} {count}" for name, count in verification.by_tier)
        reasons = ", ".join(f"{name} {count}" for name, count in verification.by_reason)
        print(
            f"\nverification decisions: {verification.recorded} (required {verification.required})"
        )
        print(f"  tiers: {tiers}")
        print(f"  reasons: {reasons}")
    else:
        print("\nverification decisions: none recorded")

    if report.action.refusals:
        names = ", ".join(f"{name} {count}" for name, count in report.action.by_action)
        print(f"\naction refusals: {report.action.refusals} ({names})")
    else:
        print("\naction refusals: none recorded")


async def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--events", type=Path, help="JSON export of a performance log")
    group.add_argument("--thread", help="thread id to read from the event store")
    args = parser.parse_args()

    if args.events is not None:
        entries = _load_events(args.events)
        source = str(args.events)
    else:
        entries = await _load_thread(args.thread)
        source = f"thread {args.thread}"

    _print_report(inventory(entries), source)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
