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


def test_messages_are_always_dropped_because_raw_output_can_quote_people():
    redacted, report = fx.redact_state(STATE)
    assert "messages" not in redacted
    assert report.dropped_keys == 1


def test_real_schema_identity_fields_do_not_reach_the_fixture(tmp_path: Path):
    """Regression from the independent review: the denylist must cover the schema.

    These are the fields the real state carries (PublishResult.workflow_thread_id,
    BloggerProfile nickname/avatar_url, CompetitorPost.author, ShootingPlan
    creator nickname/profile link, HumanFeedback.reviewer, post/note URLs).  A
    fixture that keeps any of them is a leak even though the key was not in the
    original eight-name list.
    """
    state = {
        "publish_result": {"workflow_thread_id": "real-thread-id", "post_url": "https://x/1"},
        "blogger_candidates": [
            {"nickname": "真实博主", "avatar_url": "https://img/avatar.jpg", "note_id": "n-1"}
        ],
        "competitor_posts": [{"author": "达人真名", "post_id": "p-9"}],
        "shooting_plan": {
            "creator_nickname": "达人真名",
            "profile_link": "https://www.xiaohongshu.com/user/profile/5f0real",
            "shooting_angles": [{"reference_image": "C:/Users/alice/Pictures/ref.png"}],
        },
        "human_feedback": {"reviewer": "alice@example.com"},
    }
    fixture = fx.build_fixture(
        source="sqlite", thread_id="thread-plain", checkpoint_id="cp-1", state=state
    )
    written = fixture.model_dump_json()

    for leaked in (
        "real-thread-id",
        "真实博主",
        "达人真名",
        "alice@example.com",
        "https://",
        "C:/Users/alice",
        "n-1",
        "p-9",
    ):
        assert leaked not in written, leaked
    assert fixture.state["publish_result"]["workflow_thread_id"].startswith("thread_")
    assert fixture.state["blogger_candidates"][0]["nickname"].startswith("creator_")
    assert fixture.state["human_feedback"]["reviewer"].startswith("user_")
    assert fixture.state["shooting_plan"]["shooting_angles"][0]["reference_image"].startswith(
        "image/"
    )


def test_an_absolute_path_hidden_in_an_unlabelled_key_is_blanked():
    redacted, report = fx.redact_state({"some_blob": "D:\\secret\\dir\\file.png"})
    assert redacted == {"some_blob": ""}
    assert report.locations == 1


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
                dry_run=True,
            )
        )


def test_pseudonyms_can_be_keyed_and_stay_stable_per_key():
    value = "acc-1"
    keyed = fx.pseudonym("acct", value, b"deployment-secret")
    assert keyed == fx.pseudonym("acct", value, b"deployment-secret")
    assert keyed != fx.pseudonym("acct", value)
    assert keyed != fx.pseudonym("acct", value, b"other-secret")
    fixture = fx.build_fixture(
        source="sqlite",
        thread_id="thread-plain",
        checkpoint_id="cp-1",
        state=STATE,
        redaction_key=b"deployment-secret",
    )
    plain = fx.build_fixture(
        source="sqlite", thread_id="thread-plain", checkpoint_id="cp-1", state=STATE
    )
    assert fixture.thread_pseudonym != plain.thread_pseudonym


def test_a_salted_extraction_records_its_mode_and_writes_a_manifest_digest(tmp_path: Path):
    db = tmp_path / "checkpoints.sqlite"
    _sqlite_seed(db, [("thread-a", "cp-a", {"account_id": "acc-a"})])
    out = tmp_path / "corpus"
    _, _, manifest = asyncio.run(
        ex.run_extraction(
            sqlite_path=db,
            postgres_uri=None,
            out_dir=out,
            limit=5,
            phases=None,
            dry_run=False,
            redaction_key=b"deployment-secret",
        )
    )
    assert manifest is not None
    assert manifest.pseudonym_mode == "hmac"
    digest = (out / "manifest.sha256").read_text(encoding="utf-8").strip()
    import hashlib

    assert digest == hashlib.sha256((out / "manifest.json").read_bytes()).hexdigest()


def test_an_unsalted_extraction_is_marked_as_such(tmp_path: Path):
    db = tmp_path / "checkpoints.sqlite"
    _sqlite_seed(db, [("thread-a", "cp-a", {"account_id": "acc-a"})])
    _, _, manifest = asyncio.run(
        ex.run_extraction(
            sqlite_path=db,
            postgres_uri=None,
            out_dir=tmp_path / "corpus",
            limit=5,
            phases=None,
            dry_run=False,
        )
    )
    assert manifest is not None and manifest.pseudonym_mode == "sha256"


def test_the_second_review_real_fields_are_also_redacted():
    """platform_post_id/run_id/target_id/ids/confirmer and plural URL keys."""
    state = {
        "publish_result": {
            "platform_post_id": "64f0abc123",
            "run_id": "run-real-1234",
        },
        "engagement_actions": [{"target_id": "user-777"}],
        "blogger_notes_meta": {"ids": ["note-real-1", "note-real-2"]},
        "publish_confirmation": {"confirmer": "user-42"},
        "publish_options": {"confirmed_by": "user-42"},
        "user_viral_links": ["https://www.xiaohongshu.com/explore/abc"],
        "logo_urls": ["https://img.example/logo.png"],
        "artifacts": {"copy_content": {"ref": "artifact://copy_content/latest"}},
        "misc": r"\\fileserver\share\x.png",
    }
    fixture = fx.build_fixture(source="sqlite", thread_id="t", checkpoint_id="cp-1", state=state)
    written = fixture.model_dump_json()
    for leaked in (
        "64f0abc123",
        "run-real-1234",
        "user-777",
        "note-real-1",
        "user-42",
        "https://",
        r"\\fileserver",
    ):
        assert leaked not in written, leaked
    assert "artifacts" not in fixture.state
    assert fixture.state["blogger_notes_meta"]["ids"][0].startswith("id_")
    assert fixture.state["publish_result"]["run_id"].startswith("run_")


def test_artifact_backed_checkpoints_are_skipped_without_a_store(tmp_path: Path):
    db = tmp_path / "checkpoints.sqlite"
    _sqlite_seed(
        db,
        [
            (
                "thread-a",
                "cp-a",
                {
                    "phase": "reviewing",
                    "artifacts": {"copy_content": {"ref": "artifact://copy_content/latest"}},
                },
            )
        ],
    )
    fixtures, skipped, _ = asyncio.run(
        ex.run_extraction(
            sqlite_path=db,
            postgres_uri=None,
            out_dir=tmp_path / "corpus",
            limit=5,
            phases=None,
            dry_run=True,
        )
    )
    assert fixtures == []
    assert skipped["unresolved_artifacts"] == 1


def test_artifact_backed_checkpoints_are_resolved_with_a_store(tmp_path: Path):
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.memory import InMemoryStore

    from backend.state.artifacts import put_artifact

    async def _run():
        store = InMemoryStore()
        ref = await put_artifact(store, "thread-a", "copy_content", {"selected_title": "真实标题"})
        assert ref is not None
        state = {
            "phase": "reviewing",
            "account_id": "acc-a",
            "artifacts": {"copy_content": ref},
        }
        db = tmp_path / "checkpoints.sqlite"
        async with aiosqlite.connect(str(db)) as conn:
            saver = AsyncSqliteSaver(conn=conn)
            await saver.setup()
            checkpoint = {
                "v": 1,
                "id": "cp-a",
                "ts": "2026-01-01T00:00:00+00:00",
                "channel_values": state,
                "channel_versions": {key: 1 for key in state},
                "versions_seen": {},
                "pending_sends": [],
            }
            config = {
                "configurable": {
                    "thread_id": "thread-a",
                    "checkpoint_ns": "",
                    "checkpoint_id": "cp-a",
                }
            }
            await saver.aput(
                config, checkpoint, {"source": "loop", "step": 1}, {key: 1 for key in state}
            )
        fixtures, skipped, _ = await ex.run_extraction(
            sqlite_path=db,
            postgres_uri=None,
            out_dir=tmp_path / "corpus",
            limit=5,
            phases=None,
            dry_run=True,
            store=store,
        )
        return fixtures, skipped

    fixtures, skipped = asyncio.run(_run())
    assert skipped.get("unresolved_artifacts", 0) == 0
    assert fixtures[0].state["copy_content"] == {"selected_title": "真实标题"}
    assert "artifacts" not in fixtures[0].state


def test_phase_filter_looks_past_a_newer_checkpoint_in_another_phase():
    records = [
        ex.CheckpointRecord("t1", "cp-new", {"phase": "publishing"}),
        ex.CheckpointRecord("t1", "cp-old", {"phase": "reviewing"}),
    ]
    fixtures, skipped = ex.select_corpus(records, source="sqlite", phases=frozenset({"reviewing"}))
    assert [fixture.checkpoint_id for fixture in fixtures] == ["cp-old"]
    assert skipped["phase_filtered"] == 1


def test_extraction_resolves_content_written_through_the_artifact_write_seam(tmp_path: Path):
    """The graph writes through refify_updates; extraction must read that same seam."""
    import aiosqlite
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from langgraph.store.memory import InMemoryStore

    from backend.state.artifacts import refify_updates

    async def _run():
        store = InMemoryStore()
        updates = await refify_updates(
            store, "thread-a", {"phase": "reviewing", "copy_content": {"selected_title": "真标题"}}
        )
        assert "copy_content" not in updates  # the write seam moved it into the store
        state = {"phase": "reviewing", "account_id": "acc-a", **updates}
        db = tmp_path / "checkpoints.sqlite"
        async with aiosqlite.connect(str(db)) as conn:
            saver = AsyncSqliteSaver(conn=conn)
            await saver.setup()
            checkpoint = {
                "v": 1,
                "id": "cp-a",
                "ts": "2026-01-01T00:00:00+00:00",
                "channel_values": state,
                "channel_versions": {key: 1 for key in state},
                "versions_seen": {},
                "pending_sends": [],
            }
            config = {
                "configurable": {
                    "thread_id": "thread-a",
                    "checkpoint_ns": "",
                    "checkpoint_id": "cp-a",
                }
            }
            await saver.aput(
                config, checkpoint, {"source": "loop", "step": 1}, {key: 1 for key in state}
            )
        return await ex.run_extraction(
            sqlite_path=db,
            postgres_uri=None,
            out_dir=tmp_path / "corpus",
            limit=5,
            phases=None,
            dry_run=True,
            store=store,
        )

    fixtures, skipped, _ = asyncio.run(_run())
    assert skipped.get("unresolved_artifacts", 0) == 0
    assert fixtures[0].state["copy_content"] == {"selected_title": "真标题"}
    assert "artifacts" not in fixtures[0].state


def test_the_postgres_entry_points_the_cli_relies_on_exist():
    """--store-uri/--postgres-uri depend on these langgraph entry points."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore

    assert callable(AsyncPostgresSaver.from_conn_string)
    assert callable(AsyncPostgresStore.from_conn_string)


def test_scan_limit_bounds_store_reads_and_says_the_corpus_may_be_incomplete(tmp_path: Path):
    db = tmp_path / "checkpoints.sqlite"
    _sqlite_seed(
        db,
        [
            ("thread-a", "cp-a", {"phase": "reviewing", "account_id": "acc-a"}),
            ("thread-b", "cp-b", {"phase": "reviewing", "account_id": "acc-b"}),
            ("thread-c", "cp-c", {"phase": "reviewing", "account_id": "acc-c"}),
        ],
    )
    fixtures, skipped, _ = asyncio.run(
        ex.run_extraction(
            sqlite_path=db,
            postgres_uri=None,
            out_dir=tmp_path / "corpus",
            limit=10,
            phases=None,
            dry_run=True,
            scan_limit=2,
        )
    )
    assert len(fixtures) <= 2
    assert skipped["scan_capped"] == 1


def test_iter_sqlite_reads_with_the_project_checkpoint_serde(tmp_path: Path, monkeypatch):
    """E1 must decode checkpoints exactly like the graph does (票 5cz).

    A bare saver logs "unregistered type backend.state.enums.WorkflowPhase" for
    every real checkpoint and will one day refuse to decode it, which would
    silently downgrade the fixture's decision fields to raw strings -- the very
    fields the corpus exists to preserve.
    """
    from langgraph.checkpoint.sqlite import aio as sqlite_aio

    import backend.state.checkpoint_serde as serde_mod

    seen: dict[str, object] = {}

    class _FakeSaver:
        def __init__(self, conn, *, serde=None):
            seen["serde"] = serde

        async def alist(self, config, *, limit=None):
            return
            yield  # pragma: no cover - empty checkpoint store

    monkeypatch.setattr(sqlite_aio, "AsyncSqliteSaver", _FakeSaver)
    monkeypatch.setattr(serde_mod, "checkpoint_serde", lambda: "PROJECT_SERDE")
    db = tmp_path / "checkpoints.sqlite"
    db.touch()

    async def _drain():
        return [record async for record in ex.iter_sqlite(db)]

    assert asyncio.run(_drain()) == []
    assert seen["serde"] == "PROJECT_SERDE"


def test_iter_postgres_reads_with_the_project_checkpoint_serde(monkeypatch):
    """The Postgres entry must pass the same allowlisted serializer (票 5cz)."""
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    import backend.state.checkpoint_serde as serde_mod

    seen: dict[str, object] = {}

    class _FakeSaver:
        async def alist(self, config, *, limit=None):
            return
            yield  # pragma: no cover - empty checkpoint store

    class _Ctx:
        async def __aenter__(self):
            return _FakeSaver()

        async def __aexit__(self, *exc):
            return False

    def _from_conn_string(conn_string, *, pipeline=False, serde=None):
        seen["serde"] = serde
        return _Ctx()

    monkeypatch.setattr(AsyncPostgresSaver, "from_conn_string", _from_conn_string)
    monkeypatch.setattr(serde_mod, "checkpoint_serde", lambda: "PROJECT_SERDE")

    async def _drain():
        return [record async for record in ex.iter_postgres("postgresql://unused")]

    assert asyncio.run(_drain()) == []
    assert seen["serde"] == "PROJECT_SERDE"
