"""Node latency aggregation — the evidence P2 needs before anyone builds parallelism.

The architecture note's rule is "do not build sub-agent parallelism without a
bottleneck". This module turns a run's telemetry into that evidence:

- **Where the time goes:** per-agent call count, mean / p95 / share of total.
- **How serial the run was:** summed node time vs wall-clock. A run that
  spends 95% of its wall-clock inside nodes has no parallel window left to
  exploit; one that spends 60% is already waiting on something, and more
  agents would not fix *that* wait.

It reads the ``kind:"node"`` performance-log entries produced by
``backend.agents.nodes._base.node_perf_entry`` (agent / started_at /
completed_at / duration_seconds / status). Entries with a missing or
non-numeric duration are counted, not silently dropped — a report that hides
its input gaps is worse than no report.

No data is a first-class outcome: :func:`aggregate` returns an empty report
with ``has_data=False`` instead of inventing zeros that look like measurements.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

__all__ = [
    "AgentLatency",
    "LatencyReport",
    "aggregate",
]

#: A single agent taking this share of node time is a hotspot worth a look.
HOTSPOT_SHARE = 0.40
#: Node time / wall-clock at or above this: the run lives inside nodes.
SERIAL_BOUND_RATIO = 0.90
#: Above this the node intervals already overlap — some parallelism exists.
PARALLEL_OVERLAP_RATIO = 1.05


@dataclass(frozen=True)
class AgentLatency:
    agent: str
    calls: int
    total_seconds: float
    mean_seconds: float
    p95_seconds: float
    max_seconds: float
    share: float
    """Fraction of all node time attributed to this agent (0-1)."""
    errors: int = 0


@dataclass(frozen=True)
class LatencyReport:
    has_data: bool
    threads: int = 0
    node_entries: int = 0
    skipped_entries: int = 0
    total_node_seconds: float = 0.0
    wall_clock_seconds: float = 0.0
    serial_ratio: float = 0.0
    """Summed node time / wall-clock. >1 means overlapping (parallel) time."""
    agents: tuple[AgentLatency, ...] = ()
    verdict: str = "no_data"
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _percentile(sorted_values: list[float], pct: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    # Nearest-rank percentile: simple, explainable, and stable for small n.
    rank = max(1, min(len(sorted_values), round(pct / 100.0 * len(sorted_values))))
    return sorted_values[rank - 1]


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def aggregate(
    events: Iterable[Mapping[str, Any]],
    *,
    threads: int = 1,
) -> LatencyReport:
    """Aggregate ``kind:"node"`` entries into a latency report.

    ``threads`` is the number of distinct runs the events came from; it only
    affects the walls-clock average, so a caller passing one run's export can
    leave the default.
    """
    durations: dict[str, list[float]] = {}
    errors: dict[str, int] = {}
    skipped = 0
    entries = 0
    starts: list[datetime] = []
    ends: list[datetime] = []

    for event in events:
        if str(event.get("kind") or "node") != "node":
            continue
        entries += 1
        raw = event.get("duration_seconds")
        try:
            duration = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            skipped += 1
            continue
        if duration < 0:
            skipped += 1
            continue
        agent = str(event.get("agent") or "unknown")
        durations.setdefault(agent, []).append(duration)
        if event.get("error"):
            errors[agent] = errors.get(agent, 0) + 1
        start = _parse_ts(event.get("started_at"))
        end = _parse_ts(event.get("completed_at"))
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)

    if not durations:
        return LatencyReport(has_data=False, node_entries=entries, skipped_entries=skipped)

    total = sum(sum(values) for values in durations.values())
    agents = []
    for agent, values in sorted(durations.items(), key=lambda kv: -sum(kv[1])):
        ordered = sorted(values)
        agents.append(
            AgentLatency(
                agent=agent,
                calls=len(values),
                total_seconds=round(sum(values), 3),
                mean_seconds=round(sum(values) / len(values), 3),
                p95_seconds=round(_percentile(ordered, 95), 3),
                max_seconds=round(ordered[-1], 3),
                share=round(sum(values) / total, 4) if total else 0.0,
                errors=errors.get(agent, 0),
            )
        )

    wall = 0.0
    if starts and ends:
        wall = max((max(ends) - min(starts)).total_seconds(), 0.0)
    serial_ratio = (total / wall) if wall > 0 else 0.0

    reasons: list[str] = []
    verdict = "insufficient_evidence"
    if wall <= 0:
        reasons.append("no timestamps: serial ratio unavailable")
    elif serial_ratio > PARALLEL_OVERLAP_RATIO:
        # Node intervals already overlap: the run is doing things in parallel.
        verdict = "parallel_time_present"
        reasons.append(
            f"serial ratio {serial_ratio:.2f} > {PARALLEL_OVERLAP_RATIO}: "
            "node intervals overlap — measure whether more concurrency helps"
        )
    elif serial_ratio >= SERIAL_BOUND_RATIO:
        # Wall-clock is node time: adding agents cannot shorten it.
        verdict = "node_bound"
        reasons.append(
            f"serial ratio {serial_ratio:.2f} in [{SERIAL_BOUND_RATIO}, "
            f"{PARALLEL_OVERLAP_RATIO}]: wall-clock is node time, "
            "parallelism has no window"
        )
    else:
        verdict = "waiting_not_parallel"
        reasons.append(
            f"serial ratio {serial_ratio:.2f} < {SERIAL_BOUND_RATIO}: "
            "time is spent outside nodes (waits/approvals), not in work to parallelize"
        )
    hotspots = [a for a in agents if a.share >= HOTSPOT_SHARE]
    if hotspots:
        reasons.append("hotspot: " + ", ".join(f"{a.agent} {a.share:.0%}" for a in hotspots))
    if skipped:
        reasons.append(f"{skipped} node entries lacked a numeric duration")

    return LatencyReport(
        has_data=True,
        threads=threads,
        node_entries=entries,
        skipped_entries=skipped,
        total_node_seconds=round(total, 3),
        wall_clock_seconds=round(wall, 3),
        serial_ratio=round(serial_ratio, 4),
        agents=tuple(agents),
        verdict=verdict,
        reasons=tuple(reasons),
    )
