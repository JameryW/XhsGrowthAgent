from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / "scripts" / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import record_tool_results as recorder  # noqa: E402
import tool_replay as replay  # noqa: E402

from backend.state.effects import EffectRecord, EffectStatus  # noqa: E402
from backend.tools.runtime.models import ErrorKind, ToolResult  # noqa: E402

# --------------------------------------------------------------------------- #
# Fixtures/helpers
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
    ok: bool,
    *,
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


def _success_case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "schema_version": 1,
        "capability": "eval.echo",
        "spec": _spec(),
        "payload": {"text": "hello"},
        "script": [{"outcome": "value", "value": {"echoed": "hello"}}],
        "expected": _expected(True),
        "ledger": None,
    }
    case.update(overrides)
    return case


def _timeout_case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "schema_version": 1,
        "capability": "eval.slow",
        "spec": _spec(max_attempts=2, timeout_s=0.01),
        "payload": {"wait_s": 5},
        "script": [{"outcome": "timeout"}, {"outcome": "timeout"}],
        "expected": _expected(
            False, error_kind="timeout", attempts=2, error_contains="timeout after"
        ),
        "ledger": None,
    }
    case.update(overrides)
    return case


def _domain_case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "schema_version": 1,
        "capability": "eval.ripple",
        "spec": _spec(max_attempts=3),
        "payload": {"simulation": "spread"},
        "script": [{"outcome": "domain", "reason": "pending", "payload": {"job_id": "job-1"}}],
        "expected": _expected(
            False,
            error_kind="domain",
            domain_reason="pending",
            error_contains="domain outcome: pending",
        ),
        "ledger": None,
    }
    case.update(overrides)
    return case


def _exception_case(**overrides: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "schema_version": 1,
        "capability": "eval.broken",
        "spec": _spec(max_attempts=2),
        "payload": {"simulation": "spread"},
        "script": [
            {"outcome": "exception", "message": "upstream exploded"},
            {"outcome": "exception", "message": "upstream exploded"},
        ],
        "expected": _expected(
            False,
            error_kind="exception",
            attempts=2,
            error_contains="RuntimeError: upstream exploded",
        ),
        "ledger": None,
    }
    case.update(overrides)
    return case


def _write_corpus(
    root: Path,
    cases: list[dict[str, Any]],
    *,
    manifest_extra: dict[str, Any] | None = None,
    drop_sha: bool = False,
    sha_overrides: dict[str, str] | None = None,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, str]] = []
    for index, case in enumerate(cases):
        name = f"tool-case-{index:02d}.json"
        payload = json.dumps(case, ensure_ascii=False, indent=2).encode("utf-8")
        (root / name).write_bytes(payload)
        entry: dict[str, str] = {"file": name, "sha256": hashlib.sha256(payload).hexdigest()}
        if drop_sha:
            entry.pop("sha256")
        if sha_overrides and name in sha_overrides:
            entry["sha256"] = sha_overrides[name]
        entries.append(entry)
    manifest: dict[str, Any] = {"schema_version": 1, "cases": entries}
    if manifest_extra:
        manifest.update(manifest_extra)
    (root / "manifest.json").write_bytes(
        json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    )
    return root


def _case(data: dict[str, Any], *, file: str = "tool-case-00.json") -> replay.ToolReplayCase:
    return replay.ToolReplayCase.from_dict(file, data)


def _seed_checkpoints(path: Path, state: dict[str, Any], *, thread_id: str = "thread-1") -> None:
    async def _run() -> None:
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        async with aiosqlite.connect(str(path)) as conn:
            saver = AsyncSqliteSaver(conn=conn)
            await saver.setup()
            config = {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}
            checkpoint = {
                "v": 1,
                "id": "ckpt-1",
                "ts": "2026-01-01T00:00:00+00:00",
                "channel_values": state,
                "channel_versions": {key: 1 for key in state},
                "versions_seen": {},
                "pending_sends": [],
            }
            await saver.aput(
                config, checkpoint, {"source": "loop", "step": 1}, {key: 1 for key in state}
            )

    asyncio.run(_run())


# --------------------------------------------------------------------------- #
# Missing corpora are gaps (SKIP), never passes
# --------------------------------------------------------------------------- #


def test_a_missing_corpus_is_a_skip(tmp_path: Path) -> None:
    report = replay.run_l2_replay(tmp_path / "absent")
    assert report.status == "skip"
    assert report.failed is False
    assert "missing corpus is a gap, not a pass" in report.detail
    assert "l2 skip" in report.summary()


def test_a_missing_manifest_is_a_skip(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    report = replay.run_l2_replay(corpus)
    assert report.status == "skip"
    assert "manifest.json not found" in report.detail


def test_a_blank_manifest_is_a_skip(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_bytes(b"  \n")
    assert replay.run_l2_replay(corpus).status == "skip"


def test_an_empty_manifest_is_a_skip(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path / "corpus", [])
    report = replay.run_l2_replay(corpus)
    assert report.status == "skip"
    assert "0 cases" in report.detail


# --------------------------------------------------------------------------- #
# Untrustworthy corpora are red
# --------------------------------------------------------------------------- #


def test_an_unreadable_manifest_is_red(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "manifest.json").write_bytes(b"{not json")
    report = replay.run_l2_replay(corpus)
    assert report.status == "red"
    assert report.failed is True
    assert "tool corpus could not be replayed" in report.detail


def test_a_manifest_entry_without_a_digest_is_red(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path / "corpus", [_success_case()], drop_sha=True)
    report = replay.run_l2_replay(corpus)
    assert report.status == "red"
    assert "sha256" in report.detail


def test_a_sha_mismatch_is_red(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path / "corpus", [_success_case()])
    case_path = corpus / "tool-case-00.json"
    case_path.write_bytes(case_path.read_bytes() + b"\n")
    report = replay.run_l2_replay(corpus)
    assert report.status == "red"
    assert "sha256 mismatch" in report.detail


def test_an_unlisted_json_file_is_red(tmp_path: Path) -> None:
    corpus = _write_corpus(tmp_path / "corpus", [_success_case()])
    (corpus / "tool-case-99.json").write_bytes(b"{}")
    report = replay.run_l2_replay(corpus)
    assert report.status == "red"
    assert "unlisted" in report.detail


def test_a_malformed_case_is_red(tmp_path: Path) -> None:
    broken = _success_case()
    del broken["capability"]
    corpus = _write_corpus(tmp_path / "corpus", [broken])
    report = replay.run_l2_replay(corpus)
    assert report.status == "red"
    assert "capability" in report.detail


def test_a_baseline_that_disagrees_with_the_gateway_is_red(tmp_path: Path) -> None:
    wrong = _timeout_case(
        expected=_expected(False, error_kind="timeout", attempts=1, error_contains="timeout after")
    )
    corpus = _write_corpus(tmp_path / "corpus", [wrong])
    report = replay.run_l2_replay(corpus)
    assert report.status == "red"
    assert "attempts" in report.detail
    assert report.mismatches


# --------------------------------------------------------------------------- #
# Replay: classification and receipt
# --------------------------------------------------------------------------- #


async def test_a_success_case_replays_clean() -> None:
    assert await replay.replay_case(_case(_success_case())) == []


async def test_a_retry_then_success_receipt_is_degraded() -> None:
    case = _case(
        _success_case(
            spec=_spec(max_attempts=2),
            script=[
                {"outcome": "timeout"},
                {"outcome": "value", "value": {"echoed": "hello"}},
            ],
            expected=_expected(True, attempts=2, degraded=True),
        )
    )
    assert await replay.replay_case(case) == []
    wrong = _case(
        _success_case(
            spec=_spec(max_attempts=2),
            script=[
                {"outcome": "timeout"},
                {"outcome": "value", "value": {"echoed": "hello"}},
            ],
            expected=_expected(True, attempts=2, degraded=False),
        )
    )
    assert {mismatch.field for mismatch in await replay.replay_case(wrong)} == {"degraded"}


async def test_timeout_attempts_follow_the_retry_policy() -> None:
    assert await replay.replay_case(_case(_timeout_case())) == []
    wrong = _case(
        _timeout_case(
            expected=_expected(
                False, error_kind="timeout", attempts=1, error_contains="timeout after"
            )
        )
    )
    assert {mismatch.field for mismatch in await replay.replay_case(wrong)} == {"attempts"}


async def test_a_domain_outcome_is_never_retried() -> None:
    assert await replay.replay_case(_case(_domain_case())) == []
    wrong = _case(
        _domain_case(
            expected=_expected(
                False,
                error_kind="domain",
                attempts=2,
                domain_reason="pending",
                error_contains="domain outcome: pending",
            )
        )
    )
    assert {mismatch.field for mismatch in await replay.replay_case(wrong)} == {"attempts"}


async def test_exception_failures_are_normalised_and_retried() -> None:
    assert await replay.replay_case(_case(_exception_case())) == []


# --------------------------------------------------------------------------- #
# Ledger: the classification drives the verdict and its blocking semantics
# --------------------------------------------------------------------------- #


def test_the_receipt_maps_onto_the_ledger_verdict() -> None:
    confirmed = replay.map_ledger_status(ToolResult(capability="eval.echo", ok=True))
    unknown = replay.map_ledger_status(
        ToolResult(
            capability="eval.slow",
            ok=False,
            error="timeout after 1s",
            error_kind=ErrorKind.TIMEOUT,
        )
    )
    failed = replay.map_ledger_status(
        ToolResult(
            capability="eval.broken",
            ok=False,
            error="RuntimeError: boom",
            error_kind=ErrorKind.EXCEPTION,
        )
    )
    domain_failed = replay.map_ledger_status(
        ToolResult(
            capability="eval.ripple",
            ok=False,
            error="domain outcome: pending",
            error_kind=ErrorKind.DOMAIN,
            domain={"reason": "pending"},
        )
    )
    assert (confirmed, unknown, failed, domain_failed) == (
        EffectStatus.CONFIRMED,
        EffectStatus.UNKNOWN,
        EffectStatus.FAILED,
        EffectStatus.FAILED,
    )
    assert EffectRecord(effect_id="e", status=confirmed).blocks_retry is True
    assert EffectRecord(effect_id="e", status=unknown).blocks_retry is True
    assert EffectRecord(effect_id="e", status=failed).blocks_retry is False


async def test_ledger_expected_states_replay_clean() -> None:
    cases = [
        _case(
            _success_case(ledger={"initial": "in_flight", "expected": "confirmed"}),
            file="ok.json",
        ),
        _case(
            _timeout_case(ledger={"initial": "in_flight", "expected": "unknown"}),
            file="timeout.json",
        ),
        _case(
            _domain_case(ledger={"initial": "prepared", "expected": "failed"}),
            file="domain.json",
        ),
    ]
    for case in cases:
        assert await replay.replay_case(case) == []


async def test_a_prepared_effect_is_claimed_before_the_verdict() -> None:
    case = _case(_success_case(ledger={"initial": "prepared", "expected": "confirmed"}))
    assert await replay.replay_case(case) == []


async def test_ledger_disagreement_is_reported() -> None:
    case = _case(_success_case(ledger={"initial": "in_flight", "expected": "failed"}))
    fields = {mismatch.field for mismatch in await replay.replay_case(case)}
    assert "ledger.status" in fields
    assert "ledger.blocks_retry" in fields


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_a_nondeterministic_replay_is_red(tmp_path: Path, monkeypatch: Any) -> None:
    corpus = _write_corpus(tmp_path / "corpus", [_success_case()])
    original = replay._observe
    calls = {"count": 0}

    async def _alternating(case: replay.ToolReplayCase) -> Any:
        observed = await original(case)
        calls["count"] += 1
        if calls["count"] == 2:
            return replace(observed, receipt={**observed.receipt, "attempts": 99})
        return observed

    monkeypatch.setattr(replay, "_observe", _alternating)
    report = replay.run_l2_replay(corpus)
    assert report.status == "red"
    assert "deterministic" in report.detail


# --------------------------------------------------------------------------- #
# Recorder: seeded corpus and recorded (sqlite) corpus
# --------------------------------------------------------------------------- #


def test_the_seed_recorder_builds_a_corpus_the_replay_passes(tmp_path: Path, capsys: Any) -> None:
    seeded = tmp_path / "seeded"
    assert recorder.seed_cases(seeded) == 5
    assert (seeded / "manifest.json").is_file()
    assert len(list(seeded.glob("tool-case-*.json"))) == 5
    report = replay.run_l2_replay(seeded)
    assert report.status == "pass"
    assert report.cases == 5
    assert "[5 case(s)]" in report.summary()

    cli_out = tmp_path / "cli"
    assert recorder.main(["--seed", "--out", str(cli_out)]) == 0
    assert len(list(cli_out.glob("tool-case-*.json"))) == 5
    assert "5 case(s)" in capsys.readouterr().out


def test_the_sqlite_recorder_extracts_and_sanitises_recorded_results(tmp_path: Path) -> None:
    store = tmp_path / "checkpoints.sqlite"
    _seed_checkpoints(
        store,
        {
            "messages": [
                {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "name": "search",
                            "args": {
                                "query": "xiaohongshu",
                                "api_key": "sk-verysecret123",
                                "note_path": r"C:\Users\jamer\private\notes.md",
                                "contact": "author@example.com",
                            },
                        }
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": "call-1",
                    "status": "success",
                    "content": json.dumps(
                        {"ok": True, "value": {"hits": 2}, "attempts": 1, "degraded": False}
                    ),
                },
                {"role": "assistant", "content": "done"},
            ]
        },
    )
    out = tmp_path / "corpus"
    assert recorder.main(["--sqlite-path", str(store), "--out", str(out)]) == 0

    cases = replay.load_tool_cases(out)
    assert len(cases) == 1
    assert cases[0].capability == "recorded.search"
    written = "".join(
        path.read_text(encoding="utf-8") for path in sorted(out.glob("tool-case-*.json"))
    )
    assert "sk-verysecret123" not in written
    assert "jamer" not in written
    assert "example.com" not in written
    assert "<path>" in written
    assert replay.run_l2_replay(out).status == "pass"


def test_the_sqlite_recorder_without_tool_messages_stays_an_empty_corpus(
    tmp_path: Path, capsys: Any
) -> None:
    store = tmp_path / "checkpoints.sqlite"
    _seed_checkpoints(store, {"messages": [{"role": "assistant", "content": "hello"}]})
    out = tmp_path / "corpus"
    assert recorder.main(["--sqlite-path", str(store), "--out", str(out)]) == 0

    manifest = json.loads((out / "manifest.json").read_bytes())
    assert manifest["cases"] == []
    assert manifest["note"] == recorder.EMPTY_NOTE
    assert replay.run_l2_replay(out).status == "skip"
    assert "gap, not a pass" in capsys.readouterr().out
