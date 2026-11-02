"""E1 (Adaptive Harness evaluation): fixture schema, redaction and extraction.

The corpus is real data, so these tests are the only place where the redaction
contract can be checked without holding a real checkpoint: they seed a temporary
SQLite checkpoint store with a synthetic state and assert that nothing
identifying, authenticating or locating survives into the written fixtures.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
EVAL_DIR = REPO / "scripts" / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import extract_fixtures as ex  # noqa: E402  (sibling module after sys.path setup)
import fixtures as fx  # noqa: E402

STATE: dict[str, object] = {
    "phase": "reviewing",
    "account_id": "acc-1",
    "thread_id": "thread-plain",
    "session_id": "session-plain",
    "publish_decision": {"approved_by": "user-7", "source": "mainline_review"},
    "copy_content": {"selected_title": "真实的标题", "body_text": "真实的正文"},
    "visual_plan": {
        "image_paths": ["C:/Users/alice/Pictures/a.png", "C:/Users/alice/Pictures/b.JPG"],
        "cdp_endpoint": "http://192.168.1.9:9223",
        "chrome_profile_path": "C:/Users/alice/profiles/x",
    },
    "publish_options": {"cookie": "a1=secret", "api_key": "sk-secret"},
    "messages": [{"role": "assistant", "content": "raw model output"}],
}


def _sqlite_seed(path: Path, seed: list[tuple[str, str, dict[str, object]]]) -> None:
    """Write *seed* checkpoints into a fresh AsyncSqliteSaver database."""

    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

    async def _seed() -> None:
        async with aiosqlite.connect(str(path)) as conn:
            saver = AsyncSqliteSaver(conn=conn)
            await saver.setup()
            for thread_id, checkpoint_id, state in seed:
                checkpoint = {
                    "v": 1,
                    "id": checkpoint_id,
                    "ts": "2026-01-01T00:00:00+00:00",
                    "channel_values": state,
                    "channel_versions": {key: 1 for key in state},
                    "versions_seen": {},
                    "pending_sends": [],
                }
                config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": "",
                        "checkpoint_id": checkpoint_id,
                    }
                }
                await saver.aput(
                    config,
                    checkpoint,
                    {"source": "loop", "step": 1},
                    {key: 1 for key in state},
                )

    asyncio.run(_seed())


def test_redaction_removes_identity_secrets_and_locations():
    redacted, report = fx.redact_state(STATE)

    assert isinstance(redacted, dict)
    assert redacted["account_id"].startswith("acct_")
    assert redacted["thread_id"].startswith("thread_")
    assert redacted["session_id"].startswith("session_")
    assert redacted["publish_decision"]["approved_by"].startswith("user_")
    # content is kept: the quality dimension needs it
    assert redacted["copy_content"]["selected_title"] == "真实的标题"
    # secrets/locations are blanked, never carried through
    assert redacted["publish_options"]["cookie"] == ""
    assert redacted["publish_options"]["api_key"] == ""
    assert redacted["visual_plan"]["cdp_endpoint"] == ""
    assert redacted["visual_plan"]["chrome_profile_path"] == ""
    assert redacted["visual_plan"]["image_paths"] == ["image/00.png", "image/01.jpg"]
    assert "messages" not in redacted
    assert report.identifiers == 4
    assert report.locations == 2
    assert report.paths == 2
    assert report.secrets == 2
    assert report.dropped_keys == 1


def test_redaction_is_deterministic_and_pseudonyms_are_stable():
    first, _ = fx.redact_state(STATE)
    second, _ = fx.redact_state(STATE)
    assert first == second
    assert fx.pseudonym("acct", "acc-1") != fx.pseudonym("acct", "acc-2")


def test_include_messages_keeps_them_instead_of_dropping():
    redacted, report = fx.redact_state(STATE, include_messages=True)
    assert redacted["messages"] == [{"role": "assistant", "content": "raw model output"}]
    assert report.dropped_keys == 0


def test_a_secret_shaped_key_never_leaks_through_a_container_value():
    """The inner key of {"api_key": {"value": ...}} is innocent; the outer wins."""
    redacted, report = fx.redact_state(
        {
            "api_key": {"value": "sk-secret"},
            "credentials": [{"token": "abc"}],
            "max_tokens": {"budget": 4096},
        }
    )
    assert redacted == {"api_key": "", "credentials": "", "max_tokens": ""}
    assert report.secrets == 3


def test_identifiers_keep_their_shape_without_keeping_the_value():
    redacted, report = fx.redact_state(
        {"account_id": "acc-1", "creator_id": ["c-1", "c-2"], "session_id": {"nested": "s-1"}}
    )
    assert redacted["account_id"].startswith("acct_")
    assert [value.startswith("creator_") for value in redacted["creator_id"]] == [True, True]
    assert redacted["session_id"] == ""
    assert report.identifiers == 3


def test_build_fixture_hashes_the_redacted_state_only():
    fixture = fx.build_fixture(
        source="sqlite",
        thread_id="thread-plain",
        checkpoint_id="cp-1234567890",
        state=STATE,
    )
    assert fixture.state_sha256 == fx.state_sha256(fixture.state)
    assert fixture.thread_pseudonym not in {"thread-plain"}
    assert fixture.fixture_id.startswith(fixture.thread_pseudonym)

    changed = dict(STATE)
    changed["copy_content"] = {"selected_title": "不同标题", "body_text": "不同正文"}
    other = fx.build_fixture(
        source="sqlite", thread_id="thread-plain", checkpoint_id="cp-1234567890", state=changed
    )
    assert other.state_sha256 != fixture.state_sha256


def test_select_corpus_keeps_latest_per_thread_and_counts_skips():
    records = [
        ex.CheckpointRecord("t1", "cp-new", {"phase": "reviewing", "account_id": "a"}),
        ex.CheckpointRecord("t1", "cp-old", {"phase": "creating", "account_id": "a"}),
        ex.CheckpointRecord("t2", "cp-2", {"phase": "publishing", "account_id": "b"}),
    ]

    fixtures, skipped = ex.select_corpus(
        records, source="sqlite", phases=frozenset({"reviewing"}), limit=0
    )

    assert [fixture.phase for fixture in fixtures] == ["reviewing"]
    assert skipped["duplicate_thread"] == 1
    assert skipped["phase_filtered"] == 1


def test_select_corpus_limit_is_the_budget():
    records = [
        ex.CheckpointRecord(f"t{index}", f"cp-{index}", {"account_id": f"a{index}"})
        for index in range(3)
    ]
    fixtures, skipped = ex.select_corpus(records, source="sqlite", limit=2)
    assert len(fixtures) == 2
    assert skipped["limit_reached"] == 1


def test_write_corpus_manifest_hashes_match_and_contain_no_plaintext(tmp_path: Path):
    fixture = fx.build_fixture(
        source="sqlite", thread_id="thread-plain", checkpoint_id="cp-1", state=STATE
    )
    manifest = ex.write_corpus(
        [fixture],
        out_dir=tmp_path,
        source_kind="sqlite",
        include_messages=False,
        skipped={"duplicate_thread": 0},
    )

    assert manifest.total == 1
    entry = manifest.fixtures[0]
    payload = (tmp_path / entry.file).read_bytes()
    import hashlib

    assert hashlib.sha256(payload).hexdigest() == entry.sha256
    written = payload.decode("utf-8")
    for plaintext in ("acc-1", "thread-plain", "session-plain", "alice", "sk-secret", "a1=secret"):
        assert plaintext not in written, plaintext
    assert (tmp_path / "manifest.json").is_file()


def test_extraction_reads_a_real_sqlite_checkpoint_store(tmp_path: Path):
    db = tmp_path / "checkpoints.sqlite"
    _sqlite_seed(
        db,
        [
            ("thread-a", "cp-a", {"phase": "reviewing", "account_id": "acc-a"}),
            ("thread-b", "cp-b", {"phase": "publishing", "account_id": "acc-b"}),
        ],
    )
    out = tmp_path / "corpus"
    fixtures, skipped, manifest = asyncio.run(
        ex.run_extraction(
            sqlite_path=db,
            postgres_uri=None,
            out_dir=out,
            limit=10,
            phases=None,
            include_messages=False,
            dry_run=False,
        )
    )
    assert len(fixtures) == 2
    assert manifest is not None and manifest.total == 2
    assert skipped["invalid"] == 0
    corpus = "".join(path.read_text(encoding="utf-8") for path in out.glob("*.json"))
    assert "acc-a" not in corpus and "thread-a" not in corpus


def test_dry_run_reads_but_writes_nothing(tmp_path: Path):
    db = tmp_path / "checkpoints.sqlite"
    _sqlite_seed(db, [("thread-a", "cp-a", {"account_id": "acc-a"})])
    out = tmp_path / "corpus"
    fixtures, _, manifest = asyncio.run(
        ex.run_extraction(
            sqlite_path=db,
            postgres_uri=None,
            out_dir=out,
            limit=1,
            phases=None,
            include_messages=False,
            dry_run=True,
        )
    )
    assert len(fixtures) == 1
    assert manifest is None
    assert not out.exists()


def test_extraction_requires_exactly_one_source():
    with pytest.raises(ValueError):
        asyncio.run(
            ex.run_extraction(
                sqlite_path=None,
                postgres_uri=None,
                out_dir=Path("unused"),
                limit=1,
                phases=None,
                include_messages=False,
                dry_run=True,
            )
        )
