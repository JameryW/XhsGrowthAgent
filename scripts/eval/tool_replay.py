"""L2 tool/gateway replay (P3/E3): replay recorded ``ToolResult`` sequences.

``docs/adaptive-harness-eval-plan.md`` §3 defines L2 as: replay recorded
``ToolResult`` sequences (success / retry-then-success / timeout / domain
outcome / exception / unknown) through the **real** tool gateway and assert that
the classification, the receipt (``attempts`` / ``degraded``) and the
effect-ledger state match the recorded baseline.  §4 makes that a hard line —
100% identical, no statistical compromise — because this is the safety layer:
"statistically better" cannot excuse a receipt that disagrees with the
baseline.

Why replay instead of diffing golden dicts: the rules L2 defends live in
``ToolGateway``/``EffectLedger`` — the retry budget *is* ``attempts``, a
``DomainOutcome`` is an answer and is never retried, and a timeout is UNKNOWN
(blocks a retry) while FAILED does not.  A golden-file comparison would stay
green while that code rotted.  Replay drives the production path with a
scripted tool, checks the receipt the gateway actually produces, and then drives
the ledger through the classifier the runtime itself uses
(:func:`map_ledger_status`).

Corpus layout (written by ``scripts/eval/record_tool_results.py``)::

    <corpus>/manifest.json                 # {"schema_version": 1, "cases": [...]}
    <corpus>/tool-case-00-eval-echo.json   # one case, sha256-pinned in the manifest

Every case declares the capability, the tool spec (side effect / retry policy /
timeout), the input payload, a scripted sequence of tool outcomes, the expected
receipt and the expected ledger state.  A replay runs each case **twice** and
requires the two observations to agree after removing wall-clock timings — a
receipt that cannot be reproduced is not a baseline.

Status vocabulary is the gate's own (``pass`` / ``red`` / ``skip``), so
``run_gate.py`` can hand :attr:`L2Report.status` straight to ``CheckResult``:
a missing corpus is a *skip* (a gap is not a pass), an untrustworthy corpus or
any mismatch is a *red*.

Seeded corpus (deterministic, no workflow/network needed)::

    python scripts/eval/record_tool_results.py --seed --out .eval-tool-corpus
    python scripts/eval/tool_replay.py --corpus .eval-tool-corpus   # optional CLI

Recorded corpus from a real checkpoint store (read-only sqlite)::

    python scripts/eval/record_tool_results.py --sqlite-path checkpoints.sqlite \
        --out .eval-tool-corpus --limit 50
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from collections.abc import Coroutine, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from backend.state.effects import BLOCKING_STATUSES, EffectLedger, EffectStatus
from backend.tools.runtime.gateway import ToolGateway
from backend.tools.runtime.models import (
    DomainOutcome,
    ErrorKind,
    RetryPolicy,
    SideEffect,
    ToolFn,
    ToolResult,
    ToolSpec,
)
from backend.tools.runtime.registry import ToolRegistry

__all__ = [
    "CASE_SCHEMA_VERSION",
    "MANIFEST_SCHEMA_VERSION",
    "L2Report",
    "ReplayMismatch",
    "ToolCorpusError",
    "ToolCorpusGap",
    "ToolReplayCase",
    "load_tool_cases",
    "map_ledger_status",
    "replay_case",
    "run_l2_replay",
]

MANIFEST_SCHEMA_VERSION = 1
CASE_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
CASE_FILE_PREFIX = "tool-case-"
#: Namespace of the throwaway per-replay ledger (the store is in-memory).
REPLAY_LEDGER_NS: tuple[str, ...] = ("eval", "tool-replay")


class ToolCorpusGap(Exception):  # noqa: N818 - a gap is not an error; the gate reports SKIP
    """No replayable corpus exists yet (missing directory/manifest, empty corpus)."""


class ToolCorpusError(ValueError):
    """The corpus exists but cannot be trusted as recorded (bad manifest/case)."""


@dataclass(frozen=True)
class ReplayMismatch:
    """One place where a replay disagreed with the recorded baseline."""

    case: str
    field: str
    expected: Any
    actual: Any

    def __str__(self) -> str:
        return f"{self.case}: {self.field}: expected {self.expected!r}, got {self.actual!r}"


@dataclass(frozen=True)
class ToolReplayCase:
    """One recorded tool invocation, script and baseline expectations."""

    file: str
    capability: str
    spec: Mapping[str, Any]
    payload: Mapping[str, Any]
    script: tuple[Mapping[str, Any], ...]
    expected: Mapping[str, Any]
    ledger: Mapping[str, Any] | None = None
    schema_version: int = CASE_SCHEMA_VERSION

    @classmethod
    def from_dict(cls, file: str, data: Mapping[str, Any]) -> ToolReplayCase:
        """Validate one case record (raises :class:`ToolCorpusError`)."""
        return _parse_case(str(file), data)


_L2Status = Literal["pass", "red", "skip"]


@dataclass(frozen=True)
class L2Report:
    """Outcome of one L2 run, in the gate's own status vocabulary."""

    status: _L2Status
    detail: str
    cases: int = 0
    mismatches: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return self.status == "red"

    def summary(self) -> str:
        counts = f" [{self.cases} case(s)]" if self.cases else ""
        return f"l2 {self.status}: {self.detail}{counts}"


# --------------------------------------------------------------------------- #
# Corpus parsing
# --------------------------------------------------------------------------- #

_SIDE_EFFECTS: Mapping[str, SideEffect] = {
    "pure": SideEffect.PURE,
    "read": SideEffect.READ_ONLY,
    "read_only": SideEffect.READ_ONLY,
    "side_effecting": SideEffect.SIDE_EFFECTING,
}
_SCRIPT_OUTCOMES = frozenset({"value", "timeout", "exception", "domain"})
_EXPECTED_KINDS = frozenset({"timeout", "exception", "domain"})
_LEDGER_INITIAL = frozenset({"prepared", "in_flight"})
_LEDGER_FINAL = frozenset({"confirmed", "failed", "unknown"})


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ToolCorpusError(message)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_sha256(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _parse_spec(file: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    side_effect = raw.get("side_effect", "read")
    _require(
        isinstance(side_effect, str) and side_effect.strip().lower() in _SIDE_EFFECTS,
        f"{file}: spec.side_effect {side_effect!r} is not one of "
        "pure|read|read_only|side_effecting",
    )
    max_attempts = raw.get("max_attempts", 1)
    _require(
        _is_int(max_attempts) and max_attempts >= 1,
        f"{file}: spec.max_attempts must be an int >= 1",
    )
    requires_key = raw.get("requires_idempotency_key", False)
    _require(
        isinstance(requires_key, bool),
        f"{file}: spec.requires_idempotency_key must be a bool",
    )
    timeout_s = raw.get("timeout_s", 1.0)
    _require(
        isinstance(timeout_s, (int, float)) and not isinstance(timeout_s, bool) and timeout_s > 0,
        f"{file}: spec.timeout_s must be a number > 0",
    )
    max_concurrency = raw.get("max_concurrency")
    _require(
        max_concurrency is None or (_is_int(max_concurrency) and max_concurrency >= 1),
        f"{file}: spec.max_concurrency must be None or an int >= 1",
    )
    auth_scope = raw.get("auth_scope", [])
    _require(
        isinstance(auth_scope, (list, tuple))
        and all(isinstance(scope, str) for scope in auth_scope),
        f"{file}: spec.auth_scope must be a list of strings",
    )
    return {
        "side_effect": side_effect.strip().lower(),
        "max_attempts": max_attempts,
        "requires_idempotency_key": requires_key,
        "timeout_s": float(timeout_s),
        "max_concurrency": max_concurrency,
        "auth_scope": [str(scope) for scope in auth_scope],
    }


def _parse_script(file: str, raw: Any) -> tuple[dict[str, Any], ...]:
    _require(
        isinstance(raw, (list, tuple)) and bool(raw),
        f"{file}: script must be a non-empty list",
    )
    steps: list[dict[str, Any]] = []
    for index, entry in enumerate(raw):
        _require(isinstance(entry, Mapping), f"{file}: script[{index}] must be an object")
        outcome = entry.get("outcome")
        _require(
            isinstance(outcome, str) and outcome in _SCRIPT_OUTCOMES,
            f"{file}: script[{index}].outcome {outcome!r} is not one of "
            "value|timeout|exception|domain",
        )
        step: dict[str, Any] = {"outcome": outcome}
        if outcome == "value":
            step["value"] = entry.get("value")
        elif outcome == "exception":
            message = entry.get("message", "")
            _require(
                isinstance(message, str),
                f"{file}: script[{index}].message must be a string",
            )
            step["message"] = message
        elif outcome == "domain":
            reason = entry.get("reason")
            _require(
                isinstance(reason, str) and bool(reason.strip()),
                f"{file}: script[{index}].domain needs a non-empty reason",
            )
            step["reason"] = reason.strip()
            payload = entry.get("payload")
            if payload is None and isinstance(entry.get("value"), Mapping):
                payload = entry["value"]
            if payload is not None:
                _require(
                    isinstance(payload, Mapping),
                    f"{file}: script[{index}].payload must be an object",
                )
                step["payload"] = {
                    str(key): value for key, value in payload.items() if key != "reason"
                }
        steps.append(step)
    return tuple(steps)


def _attempt_budget(spec: Mapping[str, Any], payload: Mapping[str, Any]) -> int:
    """How many script steps the gateway can consume for this case.

    A write that needs an idempotency key is not retried without one, so the
    gateway stops after the first failure even though ``max_attempts`` is
    higher; the script may not promise steps the loop cannot reach.
    """
    budget = int(spec["max_attempts"])
    if spec["requires_idempotency_key"] and not payload.get("idempotency_key"):
        return 1
    return budget


def _check_script_budget(
    file: str,
    spec: Mapping[str, Any],
    payload: Mapping[str, Any],
    script: Sequence[Mapping[str, Any]],
) -> None:
    budget = _attempt_budget(spec, payload)
    _require(
        len(script) <= budget,
        f"{file}: script has {len(script)} steps but the gateway makes at most {budget} attempt(s)",
    )
    last = str(script[-1]["outcome"])
    _require(
        len(script) == budget or last in {"value", "domain"},
        f"{file}: script ends in {last!r} after {len(script)} of {budget} attempt(s)",
    )


def _parse_expected(file: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    ok = raw.get("ok")
    _require(isinstance(ok, bool), f"{file}: expected.ok must be a bool")
    kind = raw.get("error_kind")
    _require(
        kind is None or (isinstance(kind, str) and kind in _EXPECTED_KINDS),
        f"{file}: expected.error_kind {kind!r} is not one of timeout|exception|domain",
    )
    attempts = raw.get("attempts", 1)
    _require(
        _is_int(attempts) and attempts >= 1,
        f"{file}: expected.attempts must be an int >= 1",
    )
    degraded = raw.get("degraded", False)
    _require(isinstance(degraded, bool), f"{file}: expected.degraded must be a bool")
    domain_reason = raw.get("domain_reason", "")
    _require(isinstance(domain_reason, str), f"{file}: expected.domain_reason must be a string")
    error_contains = raw.get("error_contains", "")
    _require(isinstance(error_contains, str), f"{file}: expected.error_contains must be a string")
    if ok:
        _require(
            kind is None and not domain_reason and not error_contains,
            f"{file}: expected.ok=True must not carry an error_kind/domain_reason/error_contains",
        )
    else:
        _require(kind is not None, f"{file}: expected.ok=False must name an error_kind")
    return {
        "ok": ok,
        "error_kind": kind,
        "attempts": attempts,
        "degraded": degraded,
        "domain_reason": domain_reason,
        "error_contains": error_contains,
    }


def _parse_ledger(file: str, raw: Mapping[str, Any]) -> dict[str, Any]:
    _require(isinstance(raw, Mapping), f"{file}: ledger must be an object or null")
    initial = raw.get("initial")
    _require(
        initial is None or (isinstance(initial, str) and initial in _LEDGER_INITIAL),
        f"{file}: ledger.initial {initial!r} is not one of prepared|in_flight",
    )
    expected = raw.get("expected")
    _require(
        expected is None or (isinstance(expected, str) and expected in _LEDGER_FINAL),
        f"{file}: ledger.expected {expected!r} is not one of confirmed|failed|unknown",
    )
    return {"initial": initial, "expected": expected}


def _parse_case(file: str, data: Any) -> ToolReplayCase:
    _require(isinstance(data, Mapping), f"{file}: case must be a JSON object")
    version = data.get("schema_version")
    _require(
        _is_int(version) and version == CASE_SCHEMA_VERSION,
        f"{file}: unsupported schema_version {version!r} (expected {CASE_SCHEMA_VERSION})",
    )
    capability = data.get("capability")
    _require(
        isinstance(capability, str) and "." in capability.strip(),
        f"{file}: capability must be a dotted id, got {capability!r}",
    )
    raw_spec = data.get("spec")
    _require(isinstance(raw_spec, Mapping), f"{file}: spec must be an object")
    spec = _parse_spec(file, raw_spec)
    payload = data.get("payload", {})
    _require(isinstance(payload, Mapping), f"{file}: payload must be an object")
    script = _parse_script(file, data.get("script"))
    _check_script_budget(file, spec, payload, script)
    raw_expected = data.get("expected")
    _require(isinstance(raw_expected, Mapping), f"{file}: expected must be an object")
    expected = _parse_expected(file, raw_expected)
    raw_ledger = data.get("ledger")
    ledger = None if raw_ledger is None else _parse_ledger(file, raw_ledger)
    case = ToolReplayCase(
        file=file,
        capability=capability.strip(),
        spec=spec,
        payload=dict(payload),
        script=script,
        expected=expected,
        ledger=ledger,
    )
    try:
        _build_spec(case)
    except ValueError as exc:
        raise ToolCorpusError(f"{file}: spec is not accepted by ToolSpec: {exc}") from exc
    return case


def _build_spec(case: ToolReplayCase) -> ToolSpec:
    """Turn the recorded spec into the real ``ToolSpec`` the gateway consumes."""
    spec = case.spec
    return ToolSpec(
        capability=case.capability,
        summary=f"replayed tool case {case.file}",
        side_effect=_SIDE_EFFECTS[str(spec["side_effect"])],
        retry_policy=RetryPolicy(
            max_attempts=int(spec["max_attempts"]),
            requires_idempotency_key=bool(spec["requires_idempotency_key"]),
        ),
        auth_scope=tuple(str(scope) for scope in spec.get("auth_scope") or ()),
        timeout_s=float(spec["timeout_s"]),
        max_concurrency=(
            None if spec.get("max_concurrency") is None else int(spec["max_concurrency"])
        ),
    )


# --------------------------------------------------------------------------- #
# Replay: scripted tool → real gateway → ledger verdict
# --------------------------------------------------------------------------- #


def _scripted_fn(case: ToolReplayCase) -> ToolFn:
    """Build the tool whose behaviour is the recorded script, step by step."""
    calls = {"count": 0}

    async def _run(_payload: Mapping[str, Any]) -> Any:
        index = calls["count"]
        calls["count"] += 1
        _require(index < len(case.script), f"{case.file}: scripted tool ran out of steps")
        step = case.script[index]
        outcome = step["outcome"]
        if outcome == "value":
            return step.get("value")
        if outcome == "timeout":
            raise TimeoutError(f"scripted timeout on attempt {index + 1}")
        if outcome == "exception":
            raise RuntimeError(str(step.get("message") or "scripted exception"))
        if outcome == "domain":
            raise DomainOutcome(str(step["reason"]), **dict(step.get("payload") or {}))
        raise ToolCorpusError(f"{case.file}: unknown script outcome {outcome!r}")

    return _run


class _MemoryItem:
    """The shape ``EffectLedger.get`` reads: ``.value`` holds the record dict."""

    __slots__ = ("value",)

    def __init__(self, value: Mapping[str, Any]) -> None:
        self.value = dict(value)


class _MemoryStore:
    """In-memory stand-in exposing exactly the two methods the ledger uses."""

    def __init__(self) -> None:
        self._items: dict[tuple[tuple[str, ...], str], dict[str, Any]] = {}

    async def aget(self, namespace: Sequence[str], key: str) -> _MemoryItem | None:
        stored = self._items.get((tuple(namespace), str(key)))
        return None if stored is None else _MemoryItem(stored)

    async def aput(self, namespace: Sequence[str], key: str, value: Mapping[str, Any]) -> None:
        self._items[(tuple(namespace), str(key))] = dict(value)


def map_ledger_status(result: ToolResult) -> EffectStatus:
    """The ledger verdict implied by a gateway receipt.

    * success → CONFIRMED (the effect happened);
    * timeout → UNKNOWN (we do not know whether it happened; blocks a retry);
    * exception or domain outcome → FAILED (a deterministic "did not happen",
      so a retry is safe).
    """
    if result.ok:
        return EffectStatus.CONFIRMED
    if result.error_kind is ErrorKind.TIMEOUT:
        return EffectStatus.UNKNOWN
    return EffectStatus.FAILED


@dataclass(frozen=True)
class _Observation:
    receipt: dict[str, Any]
    trace: tuple[Mapping[str, Any], ...]
    ledger_status: str = ""
    ledger_blocks: bool | None = None

    def normalized(self) -> dict[str, Any]:
        """Everything except wall-clock timings — the part replay must reproduce."""
        return {
            "receipt": {key: value for key, value in self.receipt.items() if key != "elapsed_ms"},
            "trace": tuple(
                {key: value for key, value in event.items() if key != "elapsed_ms"}
                for event in self.trace
            ),
            "ledger_status": self.ledger_status,
            "ledger_blocks": self.ledger_blocks,
        }


async def _drive_ledger(case: ToolReplayCase, result: ToolResult) -> tuple[str, bool | None]:
    """Run the receipt through the effect ledger and return (status, blocks_retry)."""
    ledger_spec = case.ledger
    if ledger_spec is None or not ledger_spec.get("expected"):
        return "", None
    ledger = EffectLedger(_MemoryStore(), namespace=REPLAY_LEDGER_NS)
    effect_id = f"{case.capability}|{case.file}"
    initial = ledger_spec.get("initial")
    if initial:
        status = EffectStatus(str(initial))
        await ledger.mark(effect_id, status)
        if status is EffectStatus.PREPARED:
            # PREPARED is only an intent and PREPARED -> CONFIRMED/UNKNOWN is not
            # a legal transition, so claim the effect (IN_FLIGHT) exactly as a
            # real caller does before the verdict comes back.
            await ledger.begin(effect_id)
    record = await ledger.mark(effect_id, map_ledger_status(result))
    return record.status.value, record.blocks_retry


async def _observe(case: ToolReplayCase) -> _Observation:
    spec = _build_spec(case)
    registry = ToolRegistry()
    registry.register(spec, _scripted_fn(case))
    events: list[Mapping[str, Any]] = []

    async def _collect(event: Mapping[str, Any]) -> None:
        events.append(dict(event))

    async def _no_sleep(_seconds: float) -> None:
        return None

    gateway = ToolGateway(registry, trace=_collect, sleeper=_no_sleep)
    result = await gateway.invoke(
        case.capability,
        case.payload,
        granted_scopes=tuple(spec.auth_scope),
    )
    ledger_status, ledger_blocks = await _drive_ledger(case, result)
    return _Observation(
        receipt=result.to_dict(),
        trace=tuple(events),
        ledger_status=ledger_status,
        ledger_blocks=ledger_blocks,
    )


async def replay_case(case: ToolReplayCase) -> list[ReplayMismatch]:
    """Replay one case through the real gateway and list every disagreement."""
    return _compare(case, await _observe(case))


def _compare(case: ToolReplayCase, observed: _Observation) -> list[ReplayMismatch]:
    receipt = observed.receipt
    expected = case.expected
    mismatches: list[ReplayMismatch] = []

    def _note(field: str, wanted: Any, actual: Any) -> None:
        mismatches.append(
            ReplayMismatch(case=case.file, field=field, expected=wanted, actual=actual)
        )

    if bool(receipt.get("ok")) is not bool(expected["ok"]):
        _note("ok", expected["ok"], receipt.get("ok"))
    recorded_kind = str(receipt.get("error_kind") or "")
    expected_kind = str(expected["error_kind"] or "")
    if recorded_kind != expected_kind:
        _note("error_kind", expected_kind, recorded_kind)
    if int(receipt.get("attempts") or 0) != int(expected["attempts"]):
        _note("attempts", expected["attempts"], receipt.get("attempts"))
    if bool(receipt.get("degraded")) is not bool(expected["degraded"]):
        _note("degraded", expected["degraded"], receipt.get("degraded"))
    if str(receipt.get("domain_reason") or "") != str(expected["domain_reason"]):
        _note("domain_reason", expected["domain_reason"], receipt.get("domain_reason", ""))
    needle = str(expected["error_contains"])
    if needle and needle not in str(receipt.get("error") or ""):
        _note("error", f"contains {needle!r}", receipt.get("error", ""))
    mismatches.extend(_compare_trace(case, observed, receipt))
    mismatches.extend(_compare_ledger(case, observed))
    return mismatches


def _compare_trace(
    case: ToolReplayCase, observed: _Observation, receipt: Mapping[str, Any]
) -> list[ReplayMismatch]:
    if len(observed.trace) != 1 or observed.trace[0].get("event") != "invoke":
        return [
            ReplayMismatch(
                case=case.file,
                field="trace",
                expected="exactly one invoke event",
                actual=f"{len(observed.trace)} event(s)",
            )
        ]
    event = observed.trace[0]
    problems: list[ReplayMismatch] = []

    def _note(field: str, wanted: Any, actual: Any) -> None:
        problems.append(ReplayMismatch(case=case.file, field=field, expected=wanted, actual=actual))

    if str(event.get("capability") or "") != case.capability:
        _note("trace.capability", case.capability, event.get("capability"))
    if bool(event.get("ok")) is not bool(receipt.get("ok")):
        _note("trace.ok", receipt.get("ok"), event.get("ok"))
    if int(event.get("attempts") or 0) != int(receipt.get("attempts") or 0):
        _note("trace.attempts", receipt.get("attempts"), event.get("attempts"))
    if str(event.get("error_kind") or "") != str(receipt.get("error_kind") or ""):
        _note("trace.error_kind", receipt.get("error_kind", ""), event.get("error_kind"))
    return problems


def _compare_ledger(case: ToolReplayCase, observed: _Observation) -> list[ReplayMismatch]:
    ledger_spec = case.ledger
    if ledger_spec is None or not ledger_spec.get("expected"):
        return []
    expected_status = str(ledger_spec["expected"])
    problems: list[ReplayMismatch] = []
    if observed.ledger_status != expected_status:
        problems.append(
            ReplayMismatch(
                case=case.file,
                field="ledger.status",
                expected=expected_status,
                actual=observed.ledger_status,
            )
        )
    expected_blocks = EffectStatus(expected_status) in BLOCKING_STATUSES
    if observed.ledger_blocks is not expected_blocks:
        problems.append(
            ReplayMismatch(
                case=case.file,
                field="ledger.blocks_retry",
                expected=expected_blocks,
                actual=observed.ledger_blocks,
            )
        )
    return problems


# --------------------------------------------------------------------------- #
# Corpus loading + report
# --------------------------------------------------------------------------- #


def load_tool_cases(corpus_dir: Path | str) -> list[ToolReplayCase]:
    """Load and validate a recorded tool corpus.

    Raises :class:`ToolCorpusGap` when no corpus exists yet and
    :class:`ToolCorpusError` when one exists but cannot be trusted (bad
    manifest, sha256 mismatch, unlisted file, malformed case).
    """
    corpus = Path(corpus_dir)
    manifest_path = corpus / MANIFEST_NAME
    if not manifest_path.is_file():
        raise ToolCorpusGap(f"{manifest_path} not found")
    manifest_bytes = manifest_path.read_bytes()
    if not manifest_bytes.strip():
        raise ToolCorpusGap(f"{manifest_path} is empty")
    try:
        manifest = json.loads(manifest_bytes)
    except json.JSONDecodeError as exc:
        raise ToolCorpusError(f"{manifest_path} is not valid JSON: {exc}") from exc
    _require(isinstance(manifest, Mapping), f"{manifest_path}: manifest must be a JSON object")
    version = manifest.get("schema_version")
    _require(
        _is_int(version) and version == MANIFEST_SCHEMA_VERSION,
        f"{manifest_path}: unsupported schema_version {version!r} "
        f"(expected {MANIFEST_SCHEMA_VERSION})",
    )
    raw_cases = manifest.get("cases")
    _require(isinstance(raw_cases, list), f"{manifest_path}: cases must be a list")
    entries: list[tuple[str, str]] = []
    for index, entry in enumerate(raw_cases):
        _require(
            isinstance(entry, Mapping),
            f"{manifest_path}: cases[{index}] must be an object",
        )
        name = entry.get("file")
        _require(
            isinstance(name, str)
            and name.startswith(CASE_FILE_PREFIX)
            and name.endswith(".json")
            and Path(name).name == name,
            f"{manifest_path}: cases[{index}].file must be a {CASE_FILE_PREFIX}*.json name",
        )
        digest = entry.get("sha256")
        _require(
            isinstance(digest, str) and _is_sha256(digest),
            f"{manifest_path}: {name}: entry has no valid sha256 digest",
        )
        entries.append((name, digest.lower()))
    names = [name for name, _ in entries]
    _require(
        len(set(names)) == len(names),
        f"{manifest_path}: the manifest lists the same case file twice",
    )
    on_disk = {
        path.name for path in corpus.glob("*.json") if path.name != MANIFEST_NAME and path.is_file()
    }
    unlisted = sorted(on_disk - set(names))
    _require(
        not unlisted,
        f"{corpus}: unlisted json file(s) in the corpus: {', '.join(unlisted)}",
    )
    cases: list[ToolReplayCase] = []
    for name, digest in entries:
        case_path = corpus / name
        try:
            payload = case_path.read_bytes()
        except OSError as exc:
            raise ToolCorpusError(f"{name}: case file is unreadable: {exc}") from exc
        actual = hashlib.sha256(payload).hexdigest()
        _require(
            actual == digest,
            f"{name}: sha256 mismatch (manifest {digest[:12]}..., file {actual[:12]}...)",
        )
        try:
            data = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ToolCorpusError(f"{name}: not valid JSON: {exc}") from exc
        cases.append(_parse_case(name, data))
    return cases


async def _replay_all(cases: Sequence[ToolReplayCase]) -> list[ReplayMismatch]:
    mismatches: list[ReplayMismatch] = []
    for case in cases:
        first = await _observe(case)
        second = await _observe(case)
        if first.normalized() != second.normalized():
            mismatches.append(
                ReplayMismatch(
                    case=case.file,
                    field="determinism",
                    expected="identical replays",
                    actual="replay is not deterministic: two passes disagree",
                )
            )
            continue
        mismatches.extend(_compare(case, first))
    return mismatches


def _run_sync(coro: Coroutine[Any, Any, list[ReplayMismatch]]) -> list[ReplayMismatch]:
    """Drive the async replay from a sync call site (run_gate) or a live loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # run_gate is sync, but tests may call this from inside an event loop; a
    # private thread keeps the gate callable from both without a nested-loop hack.
    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except BaseException as exc:  # re-raised on the caller's thread
            box["error"] = exc

    thread = threading.Thread(target=_worker, name="l2-tool-replay", daemon=True)
    thread.start()
    thread.join()
    error = box.get("error")
    if error is not None:
        raise error
    return box["value"]


def run_l2_replay(corpus_dir: Path | str) -> L2Report:
    """Replay the recorded tool corpus and score it against its baseline.

    ``skip`` when no corpus exists yet (a gap is not a pass); ``red`` for an
    untrustworthy corpus, any receipt/ledger disagreement, or a replay that is
    not reproducible; ``pass`` only when every case replays to exactly the
    recorded classification, receipt and ledger state.
    """
    corpus = Path(corpus_dir)
    if not corpus.is_dir():
        return L2Report(
            "skip",
            (
                f"{corpus} not found: record a tool corpus first, e.g. "
                f"`python scripts/eval/record_tool_results.py --seed --out {corpus}`; "
                "a missing corpus is a gap, not a pass"
            ),
        )
    try:
        cases = load_tool_cases(corpus)
    except ToolCorpusGap as exc:
        return L2Report("skip", f"{exc}: a missing corpus is a gap, not a pass")
    except (ToolCorpusError, OSError, ValueError) as exc:
        return L2Report("red", f"tool corpus could not be replayed: {exc}")
    if not cases:
        return L2Report(
            "skip",
            (
                f"{corpus / MANIFEST_NAME} lists 0 cases: record a tool corpus first; "
                "an empty corpus is a gap, not a pass"
            ),
        )
    try:
        mismatches = _run_sync(_replay_all(cases))
    except Exception as exc:
        return L2Report("red", f"tool cases could not be replayed: {exc}")
    if mismatches:
        shown = "; ".join(str(item) for item in mismatches[:5])
        return L2Report(
            "red",
            f"{len(cases)} tool case(s) replayed; {len(mismatches)} mismatch(es): {shown}",
            cases=len(cases),
            mismatches=tuple(str(item) for item in mismatches),
        )
    return L2Report(
        "pass",
        (
            f"{len(cases)} tool case(s) replayed; classification, receipt and effect-ledger "
            "state are identical to the recorded baseline"
        ),
        cases=len(cases),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Optional CLI: run the replay over one corpus and print the verdict."""
    import argparse

    parser = argparse.ArgumentParser(description="Replay a recorded L2 tool corpus.")
    parser.add_argument("--corpus", type=Path, default=Path(".eval-tool-corpus"))
    options = parser.parse_args(argv)
    report = run_l2_replay(options.corpus)
    print(report.summary())
    return 0 if report.status == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
