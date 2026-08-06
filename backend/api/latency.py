"""Env-gated HTTP request latency instrumentation.

When ``XHS_LATENCY_LOG=1`` is set, emits one structured JSON line per sampled
request to the ``xhs_growth.api.latency`` logger. Default off — zero overhead
when the flag is unset (the gate is read once at import).

Schema (stable field names — forward-compatible for a future persistent sink):

    {"event": "http_latency", "endpoint": "/status", "thread_id": "...",
     "phase": "completed", "total_ms": 12.3, "aget_state_ms": 4.1,
     "db_ms": 1.2, "serialize_ms": 3.0, "ripple_progress_ms": 0.5}

Design (ponytail):
- stdlib logging + one JSON line — no metrics framework, no new table.
- sampling: high-frequency endpoints (/status) sample 1/N to bound log volume.
- failure-isolation: ``log_latency`` never raises; a broken timer must not
  affect the request it was measuring.
- no contextvars — thread_id is passed explicitly to avoid asyncio task-reuse
  leaks across requests.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("xhs_growth.api.latency")

# Read once at import; flipping the env var requires a process restart.
_ENABLED: bool = os.environ.get("XHS_LATENCY_LOG", "").strip() in ("1", "true", "yes")

# ponytail: 1-in-N sampling for the hottest poll endpoint. Other endpoints
# are low-frequency enough to log every call. Bump if log volume is a problem.
_STATUS_SAMPLE_RATE = 10

_SAMPLE_DENOMINATOR: dict[str, int] = {"/status": _STATUS_SAMPLE_RATE}


class LatencyTimer:
    """Accumulate named timing segments for one request.

    Usage::

        timer = LatencyTimer("/status", thread_id) if LatencyTimer.enabled else None
        if timer:
            with timer.segment("aget_state"):
                state = await graph.aget_state(config)
        ...
        if timer:
            timer.emit(phase="completed")

    Each ``segment`` measures wall-clock ms between enter/exit. ``emit`` writes
    one JSON line with total + all recorded segments. Best-effort: every method
    swallows its own errors so instrumentation can never break the request.
    """

    __slots__ = ("_endpoint", "_thread_id", "_segments", "_start")

    def __init__(self, endpoint: str, thread_id: str | None) -> None:
        self._endpoint = endpoint
        self._thread_id = thread_id or ""
        self._segments: dict[str, float] = {}
        self._start = time.perf_counter()

    @staticmethod
    def enabled() -> bool:
        return _ENABLED

    @staticmethod
    def should_sample(endpoint: str) -> bool:
        """True if this request should be instrumented (env gate + sampling)."""
        if not _ENABLED:
            return False
        denom = _SAMPLE_DENOMINATOR.get(endpoint)
        if denom and denom > 1:
            # ponytail: deterministic-ish sampling without Math.random (unavailable
            # in some sandboxed contexts) — use perf_counter low bits. Good enough
            # to bound volume; not a uniform RNG but that's fine for bottleneck
            # discovery, not statistical rigor.
            return int(time.perf_counter() * 1_000_000) % denom == 0
        return True

    def segment(self, name: str) -> _Segment:
        return _Segment(self, name)

    def _record(self, name: str, ms: float) -> None:
        self._segments[name] = ms

    def emit(self, phase: str = "") -> None:
        try:
            total_ms = (time.perf_counter() - self._start) * 1000.0
            payload: dict[str, Any] = {
                "event": "http_latency",
                "endpoint": self._endpoint,
                "thread_id": self._thread_id,
                "phase": phase,
                "total_ms": round(total_ms, 3),
            }
            for seg_name, seg_ms in self._segments.items():
                payload[f"{seg_name}_ms"] = round(seg_ms, 3)
            logger.info(json.dumps(payload, ensure_ascii=False))
        except Exception:
            # Instrumentation must never affect the request it measured.
            logger.debug("latency emit failed", exc_info=True)


class _Segment:
    """Context manager recording one named segment's wall-clock ms."""

    __slots__ = ("_timer", "_name", "_start")

    def __init__(self, timer: LatencyTimer, name: str) -> None:
        self._timer = timer
        self._name = name
        self._start = 0.0

    def __enter__(self) -> _Segment:
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: object) -> None:
        try:
            self._timer._record(self._name, (time.perf_counter() - self._start) * 1000.0)
        except Exception:
            logger.debug("latency segment record failed", exc_info=True)
        # Returning None (not True) so request exceptions are never suppressed.
