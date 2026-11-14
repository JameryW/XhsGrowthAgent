"""Record boundary ``ToolResult`` cases for the L2 tool/gateway replay (P3/E3).

Two sources, one output format (read by ``scripts/eval/tool_replay.py``):

* ``--seed`` writes the five built-in boundary cases the L2 replay must cover:
  a plain success, a timeout that survives its retry budget, a retry that
  succeeds (degraded), a domain outcome that is never retried, and an exception
  that is retried then normalised.  These need no workflow, checkpoint or
  network — the corpus is deterministic and safe to regenerate anywhere:
  ``python scripts/eval/record_tool_results.py --seed --out .eval-tool-corpus``.
* ``--sqlite-path`` reads a real checkpoint store **read-only**, pairs recorded
  ``AIMessage.tool_calls`` with the ``ToolMessage`` that answered them, and
  classifies each receipt (gateway-receipt JSON, or text heuristics:
  ``timeout after``, ``domain outcome: <reason>``, status ``error``, else
  success) into the same case shape.

What a recorded case is *not*: a promise about the current code.  It is the
baseline the replay is scored against, so the recorder must not invent receipt
fields — where the recording is ambiguous (an unpaired result, content that
neither parses as a receipt nor matches a known failure shape) it skips the
record and counts it.  An empty recording stays an empty corpus (manifest with
0 cases, picked up as SKIP), never a faked pass.

Sanitisation: absolute paths (Windows drive/UNC and POSIX home/tmp trees),
secret-shaped values (keys such as ``api_key``/``token``/``secret``, ``sk-...``
strings, bearer tokens) and e-mail addresses are replaced with placeholders, and
the number of replacements is reported.  Tool payloads are replayed as
read-only scripted calls, so recording them is safe; the sanitisation is about
not committing machine paths and credentials into the eval corpus.

Deterministic output: case order is fixed (seed order, or sorted by serialised
case for the sqlite source), filenames are ``tool-case-NN-<slug>.json``, and the
manifest pins each file's sha256 so a hand edit cannot slip through unnoticed.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

__all__ = [
    "DEFAULT_OUTPUT",
    "EMPTY_NOTE",
    "SEED_NOTE",
    "extract_cases_from_messages",
    "main",
    "read_checkpoint_states",
    "record_sqlite",
    "sanitize_text",
    "sanitize_value",
    "seed_case_dicts",
    "seed_cases",
    "write_corpus",
]

# Kept in step with ``tool_replay`` (same directory, same on-disk contract).  They
# are duplicated instead of imported so either script stays runnable on its own.
MANIFEST_SCHEMA_VERSION = 1
CASE_SCHEMA_VERSION = 1
MANIFEST_NAME = "manifest.json"
CASE_FILE_PREFIX = "tool-case-"

DEFAULT_OUTPUT = Path(".eval-tool-corpus")
SEED_NOTE = "built-in boundary cases for the L2 tool/gateway replay"
EMPTY_NOTE = "no tool calls/results found in the recorded checkpoints; nothing to replay"

_ERROR_KINDS = frozenset({"timeout", "exception", "domain"})


# --------------------------------------------------------------------------- #
# Sanitisation
# --------------------------------------------------------------------------- #

# Matches credential-ish *keys* without eating benign counters like "max_tokens"
# or "token_count": the word must sit on a key boundary.
_SECRET_KEY = re.compile(
    r"(?:^|_)(?:token|secret|password|passwd|cookie|authorization|api_key|apikey"
    r"|access_key|private_key|session)(?:$|_)",
    re.IGNORECASE,
)
_WINDOWS_PATH = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/][^\s\"'<>|]*")
_UNC_PATH = re.compile(r"\\\\[^\s\"'<>|]+")
_POSIX_PATH = re.compile(
    r"(?<![\w.])/(?:home|Users|tmp|var|etc|opt|root|mnt|srv|private)(?:/[^\s\"'<>]*)?"
)
_SECRET_VALUE = re.compile(r"sk-[A-Za-z0-9_-]{6,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_MAX_TEXT = 1000


def sanitize_text(text: str) -> str:
    """Redact paths, secret-shaped tokens and e-mails from one string."""
    cleaned = _WINDOWS_PATH.sub("<path>", text)
    cleaned = _UNC_PATH.sub("<path>", cleaned)
    cleaned = _POSIX_PATH.sub("<path>", cleaned)
    cleaned = _SECRET_VALUE.sub("<secret>", cleaned)
    cleaned = _EMAIL.sub("<email>", cleaned)
    if len(cleaned) > _MAX_TEXT:
        cleaned = cleaned[:_MAX_TEXT] + "…"
    return cleaned


def sanitize_value(value: Any, counter: list[int] | None = None) -> Any:
    """Recursively sanitise a JSON-ish value, counting the redactions."""
    counts = counter if counter is not None else [0]
    if isinstance(value, Mapping):
        cleaned: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if _SECRET_KEY.search(name):
                cleaned[name] = "<redacted>"
                counts[0] += 1
                continue
            cleaned[name] = sanitize_value(item, counts)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, counts) for item in value]
    if isinstance(value, str):
        cleaned_text = sanitize_text(value)
        if cleaned_text != value:
            counts[0] += 1
        return cleaned_text
    if value is None or isinstance(value, (bool, int, float)):
        return value
    counts[0] += 1
    return sanitize_text(repr(value))


# --------------------------------------------------------------------------- #
# Corpus writing
# --------------------------------------------------------------------------- #


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "case"


def write_corpus(
    cases: Sequence[Mapping[str, Any]],
    *,
    out_dir: Path | str,
    note: str = "",
) -> dict[str, Any]:
    """Write ``cases`` plus a sha256-pinned manifest; return the manifest.

    Only files this recorder owns are replaced: stale ``tool-case-*.json`` files
    are removed first, because a shrunk corpus must not leave an unlisted file
    behind (the replay deliberately treats that as untrusted).
    """
    target = out_dir if isinstance(out_dir, Path) else Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    for stale in target.glob(f"{CASE_FILE_PREFIX}*.json"):
        stale.unlink()
    entries: list[dict[str, str]] = []
    for index, case in enumerate(cases):
        capability = str(case.get("capability") or "case")
        name = f"{CASE_FILE_PREFIX}{index:02d}-{_slug(capability)}.json"
        payload = json.dumps(case, ensure_ascii=False, indent=2).encode("utf-8")
        (target / name).write_bytes(payload)
        entries.append({"file": name, "sha256": hashlib.sha256(payload).hexdigest()})
    manifest: dict[str, Any] = {"schema_version": MANIFEST_SCHEMA_VERSION, "cases": entries}
    if note:
        manifest["note"] = note
    (target / MANIFEST_NAME).write_bytes(
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    )
    return manifest


# --------------------------------------------------------------------------- #
# Built-in boundary cases
# --------------------------------------------------------------------------- #


def _spec(max_attempts: int = 1, *, timeout_s: float = 1.0) -> dict[str, Any]:
    return {
        "side_effect": "read",
        "max_attempts": max_attempts,
        "requires_idempotency_key": False,
        "timeout_s": timeout_s,
        "max_concurrency": None,
        "auth_scope": [],
    }


def _expected(
    *,
    ok: bool,
    error_kind: str | None = None,
    attempts: int = 1,
    degraded: bool = False,
    domain_reason: str = "",
    error_contains: str = "",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "error_kind": error_kind,
        "attempts": attempts,
        "degraded": degraded,
        "domain_reason": domain_reason,
        "error_contains": error_contains,
    }


def seed_case_dicts() -> list[dict[str, Any]]:
    """The five boundary cases the L2 replay must cover, in fixed order."""
    return [
        {
            "schema_version": CASE_SCHEMA_VERSION,
            "capability": "eval.echo",
            "spec": _spec(),
            "payload": {"text": "hello"},
            "script": [{"outcome": "value", "value": {"echoed": "hello"}}],
            "expected": _expected(ok=True),
            "ledger": None,
        },
        {
            "schema_version": CASE_SCHEMA_VERSION,
            "capability": "eval.slow",
            "spec": _spec(max_attempts=2, timeout_s=0.01),
            "payload": {"wait_s": 5},
            "script": [{"outcome": "timeout"}, {"outcome": "timeout"}],
            "expected": _expected(
                ok=False, error_kind="timeout", attempts=2, error_contains="timeout after"
            ),
            "ledger": {"initial": "in_flight", "expected": "unknown"},
        },
        {
            "schema_version": CASE_SCHEMA_VERSION,
            "capability": "eval.flaky",
            "spec": _spec(max_attempts=2),
            "payload": {"attempt": 1},
            "script": [
                {"outcome": "timeout"},
                {"outcome": "value", "value": {"recovered": True}},
            ],
            "expected": _expected(ok=True, attempts=2, degraded=True),
            "ledger": None,
        },
        {
            "schema_version": CASE_SCHEMA_VERSION,
            "capability": "eval.ripple",
            "spec": _spec(max_attempts=3),
            "payload": {"simulation": "spread"},
            "script": [{"outcome": "domain", "reason": "pending", "payload": {"job_id": "job-1"}}],
            "expected": _expected(
                ok=False,
                error_kind="domain",
                domain_reason="pending",
                error_contains="domain outcome: pending",
            ),
            "ledger": {"initial": "prepared", "expected": "failed"},
        },
        {
            "schema_version": CASE_SCHEMA_VERSION,
            "capability": "eval.broken",
            "spec": _spec(max_attempts=2),
            "payload": {"simulation": "spread"},
            "script": [
                {"outcome": "exception", "message": "upstream exploded"},
                {"outcome": "exception", "message": "upstream exploded"},
            ],
            "expected": _expected(
                ok=False,
                error_kind="exception",
                attempts=2,
                error_contains="RuntimeError: upstream exploded",
            ),
            "ledger": {"initial": "in_flight", "expected": "failed"},
        },
    ]


def seed_cases(out_dir: Path | str, *, note: str = "") -> int:
    """Write the built-in boundary corpus and return its case count.

    This is the no-subprocess seam integration tests use to build a corpus in
    ``tmp_path``: deterministic bytes, deterministic order, no CLI/network.
    """
    cases = seed_case_dicts()
    write_corpus(cases, out_dir=out_dir, note=note or SEED_NOTE)
    return len(cases)


# --------------------------------------------------------------------------- #
# Extraction from recorded messages
# --------------------------------------------------------------------------- #


def _field(message: Any, name: str, default: Any = None) -> Any:
    if isinstance(message, Mapping):
        return message.get(name, default)
    return getattr(message, name, default)


def _tool_calls(message: Any) -> list[Mapping[str, Any]]:
    raw = _field(message, "tool_calls") or ()
    calls: list[Mapping[str, Any]] = []
    for call in raw:
        if isinstance(call, Mapping):
            calls.append(call)
        elif hasattr(call, "name"):
            calls.append(
                {
                    "id": getattr(call, "id", ""),
                    "name": getattr(call, "name", ""),
                    "args": getattr(call, "args", {}),
                }
            )
    return calls


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, Mapping):
        return json.dumps(content, ensure_ascii=False, default=str)
    if isinstance(content, (list, tuple)):
        parts: list[str] = []
        for block in content:
            if isinstance(block, Mapping) and isinstance(block.get("text"), str):
                parts.append(block["text"])
            elif isinstance(block, str):
                parts.append(block)
            else:
                parts.append(json.dumps(block, ensure_ascii=False, default=str))
        return "\n".join(parts)
    return str(content)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _json_object(text: str) -> Mapping[str, Any] | None:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return None
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _as_int(value: Any, default: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def _recorded_attempts(text: str, default: int = 1) -> int:
    match = re.search(r"(?:attempts?|after)\D{0,4}(\d+)", text.lower())
    if match is None:
        return default
    return max(1, int(match.group(1)))


def _decode_value(text: str) -> Any:
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except (json.JSONDecodeError, TypeError):
        return text


def _classification_from_receipt(receipt: Mapping[str, Any]) -> dict[str, Any] | None:
    if receipt.get("ok") is True:
        attempts = max(1, _as_int(receipt.get("attempts"), 1))
        value = receipt["value"] if "value" in receipt else receipt.get("result")
        return {
            "ok": True,
            "error_kind": None,
            "attempts": attempts,
            "degraded": receipt.get("degraded") is True,
            "domain_reason": "",
            "error": "",
            "value": value,
        }
    kind = str(receipt.get("error_kind") or "").strip().lower()
    if kind not in _ERROR_KINDS:
        return None
    error = str(receipt.get("error") or "")
    domain = _as_mapping(receipt.get("domain"))
    reason = str(receipt.get("domain_reason") or domain.get("reason") or "")
    return {
        "ok": False,
        "error_kind": kind,
        "attempts": 1 if kind == "domain" else max(1, _as_int(receipt.get("attempts"), 1)),
        "degraded": False,
        "domain_reason": reason,
        "error": error,
        "value": None,
    }


_ERROR_SIGNALS = (
    "timeout after",
    "domain outcome:",
    "runtimeerror:",
    "traceback (most recent call last)",
)


def _classify(content: Any, status: str) -> dict[str, Any] | None:
    """Classify one recorded tool result, or None when it is not replayable."""
    text = _content_text(content).strip()
    if text:
        receipt = _json_object(text)
        if receipt is not None and isinstance(receipt.get("ok"), bool):
            return _classification_from_receipt(receipt)
    if not text:
        return None
    lowered = text.lower()
    is_error = status.strip().lower() == "error" or any(
        signal in lowered for signal in _ERROR_SIGNALS
    )
    if is_error:
        domain = re.search(r"domain outcome:\s*([A-Za-z0-9_.:-]+)", text, re.IGNORECASE)
        if domain is not None:
            return {
                "ok": False,
                "error_kind": "domain",
                "attempts": 1,
                "degraded": False,
                "domain_reason": domain.group(1),
                "error": text,
                "value": None,
            }
        kind = "timeout" if "timeout after" in lowered else "exception"
        return {
            "ok": False,
            "error_kind": kind,
            "attempts": _recorded_attempts(text),
            "degraded": False,
            "domain_reason": "",
            "error": text,
            "value": None,
        }
    return {
        "ok": True,
        "error_kind": None,
        "attempts": 1,
        "degraded": False,
        "domain_reason": "",
        "error": "",
        "value": _decode_value(text),
    }


def _capability_for(tool_name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", tool_name.strip()) or "tool"
    return cleaned if "." in cleaned else f"recorded.{cleaned}"


def _error_contains(classification: Mapping[str, Any]) -> str:
    kind = classification["error_kind"]
    if kind is None:
        return ""
    if kind == "domain":
        return f"domain outcome: {classification['domain_reason']}"
    if kind == "timeout":
        return "timeout after"
    return sanitize_text(str(classification["error"])) or "RuntimeError"


def _script_for(classification: Mapping[str, Any], counter: list[int]) -> list[dict[str, Any]]:
    """Synthesise the script that produces the recorded receipt shape."""
    kind = classification["error_kind"]
    attempts = int(classification["attempts"])
    if kind is None:
        script = [{"outcome": "timeout"} for _ in range(max(0, attempts - 1))]
        script.append(
            {
                "outcome": "value",
                "value": sanitize_value(classification["value"], counter),
            }
        )
        return script
    if kind == "domain":
        return [
            {
                "outcome": "domain",
                "reason": str(classification["domain_reason"] or "recorded"),
            }
        ]
    if kind == "timeout":
        return [{"outcome": "timeout"} for _ in range(attempts)]
    message = sanitize_text(str(classification["error"]))
    if message.startswith("RuntimeError: "):
        message = message[len("RuntimeError: ") :]
    return [
        {"outcome": "exception", "message": message or "recorded tool failure"}
        for _ in range(attempts)
    ]


def _case_from_recorded_result(
    tool_name: str,
    arguments: Any,
    content: Any,
    status: str,
    counter: list[int],
) -> dict[str, Any] | None:
    classification = _classify(content, status)
    if classification is None:
        return None
    attempts = int(classification["attempts"])
    kind = classification["error_kind"]
    payload = sanitize_value(dict(_as_mapping(arguments)), counter)
    if not isinstance(payload, Mapping):
        payload = {}
    expected = {
        "ok": classification["ok"],
        "error_kind": kind,
        "attempts": attempts,
        "degraded": bool(classification["degraded"]) or (kind is None and attempts > 1),
        "domain_reason": classification["domain_reason"],
        "error_contains": _error_contains(classification),
    }
    return {
        "schema_version": CASE_SCHEMA_VERSION,
        "capability": _capability_for(tool_name),
        "spec": _spec(max(1, attempts)),
        "payload": dict(payload),
        "script": _script_for(classification, counter),
        "expected": expected,
        "ledger": None,
    }


def extract_cases_from_messages(
    messages: Iterable[Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Pair recorded tool calls with their results and turn them into cases.

    Returns ``(cases, counts)`` where ``counts`` reports unpaired results,
    unclassifiable results and the number of sanitised strings.
    """
    pending: dict[str, tuple[str, Any]] = {}
    cases: list[dict[str, Any]] = []
    counter = [0]
    skipped = {"unpaired_result": 0, "unclassified": 0}
    for message in messages or ():
        for call in _tool_calls(message):
            call_id = str(call.get("id") or call.get("tool_call_id") or "")
            name = str(call.get("name") or "")
            if not call_id or not name:
                continue
            pending[call_id] = (name, call.get("args", call.get("input", {})))
        call_id = str(_field(message, "tool_call_id") or "")
        if not call_id:
            continue
        pair = pending.pop(call_id, None)
        if pair is None:
            skipped["unpaired_result"] += 1
            continue
        status = str(_field(message, "status") or "")
        case = _case_from_recorded_result(
            pair[0], pair[1], _field(message, "content"), status, counter
        )
        if case is None:
            skipped["unclassified"] += 1
            continue
        cases.append(case)
    skipped["sanitized_strings"] = counter[0]
    return cases, skipped


# --------------------------------------------------------------------------- #
# Checkpoint (sqlite) source
# --------------------------------------------------------------------------- #


async def read_checkpoint_states(
    path: Path | str, *, scan_limit: int | None = None
) -> list[Mapping[str, Any]]:
    """Read ``channel_values`` of the checkpoints in a sqlite store, read-only."""
    source = path if isinstance(path, Path) else Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"checkpoint store not found: {source}")
    # Imported lazily so the seeded mode does not need the sqlite driver stack.
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    from backend.state.checkpoint_serde import checkpoint_serde

    states: list[Mapping[str, Any]] = []
    async with aiosqlite.connect(f"file:{source.as_posix()}?mode=ro", uri=True) as conn:
        saver = AsyncSqliteSaver(conn=conn, serde=checkpoint_serde())
        async for item in saver.alist(None, limit=scan_limit):
            checkpoint = getattr(item, "checkpoint", None)
            if not isinstance(checkpoint, Mapping):
                continue
            values = checkpoint.get("channel_values")
            if isinstance(values, Mapping):
                states.append(values)
    return states


async def record_sqlite(
    sqlite_path: Path | str,
    out_dir: Path | str,
    *,
    limit: int = 0,
) -> dict[str, Any]:
    """Extract replayable cases from a checkpoint store and write a corpus."""
    states = await read_checkpoint_states(sqlite_path)
    cases: list[dict[str, Any]] = []
    skipped = {"unpaired_result": 0, "unclassified": 0, "sanitized_strings": 0}
    for state in states:
        messages = state.get("messages")
        if not messages:
            continue
        found, counts = extract_cases_from_messages(messages)
        for key, value in counts.items():
            skipped[key] = skipped.get(key, 0) + value
        cases.extend(found)
    # Same corpus from the same checkpoints regardless of checkpoint iteration
    # order: sort by the serialised case (stable, content-addressed ordering).
    cases.sort(key=lambda case: json.dumps(case, ensure_ascii=False, sort_keys=True))
    if limit > 0 and len(cases) > limit:
        skipped["limit_truncated"] = len(cases) - limit
        cases = cases[:limit]
    note = "" if cases else EMPTY_NOTE
    write_corpus(cases, out_dir=out_dir, note=note)
    return {"cases": len(cases), "skipped": skipped, "note": note, "out": str(out_dir)}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record ToolResult cases for the L2 tool/gateway replay."
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--seed", action="store_true", help="write the built-in boundary cases")
    source.add_argument(
        "--sqlite-path",
        type=Path,
        default=None,
        help="extract recorded tool calls/results from a checkpoint store",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"corpus directory (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="maximum number of cases to record (0 = no limit)",
    )
    parser.add_argument("--note", default="", help="free-form note stored in the manifest")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    options = _build_parser().parse_args(argv)
    out_dir = options.out if isinstance(options.out, Path) else Path(options.out)
    skipped: dict[str, int] = {}
    try:
        if options.seed:
            count = seed_cases(out_dir, note=options.note)
        else:
            result = asyncio.run(
                record_sqlite(options.sqlite_path, out_dir, limit=max(0, options.limit))
            )
            count = int(result["cases"])
            skipped = dict(result["skipped"])
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"could not record tool corpus: {exc}", file=sys.stderr)
        return 1
    print(f"l2 tool corpus: {count} case(s) -> {out_dir / MANIFEST_NAME}")
    if skipped:
        print(f"skipped: {json.dumps(skipped, ensure_ascii=False)}")
    if count == 0:
        print("no tool messages found: wrote an empty manifest (a gap, not a pass)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
