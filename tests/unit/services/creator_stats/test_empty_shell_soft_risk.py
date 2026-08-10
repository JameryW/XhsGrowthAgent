"""Empty-shell soft risk detection for creator stats imports."""

from __future__ import annotations

import pytest

from backend.db.creator_stats import (
    _reset_memory_store,
    get_account_stats,
    list_note_stats,
    upsert_bundle,
)
from backend.services.creator_stats.normalize import normalize_bundle
from backend.services.creator_stats.pipeline import (
    _batch_has_soft_risk,
    _has_successful_live_sync,
    _mark_empty_shell_soft_risk,
    sync_from_creator_center,
)
from backend.services.creator_stats.types import ERROR_EMPTY_SHELL, SyncResult, classify_sync_error


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


def test_classify_empty_shell_error_code():
    assert classify_sync_error("empty shell risk: notes collapsed") == ERROR_EMPTY_SHELL


def test_mark_empty_shell_when_prior_notes_collapse():
    result = SyncResult(account_id="a1", account_synced=True, notes_imported=0)
    marked = _mark_empty_shell_soft_risk(result, prior_note_count=5, fetched_note_count=0)
    assert marked.soft_risk is True
    assert marked.error_code == ERROR_EMPTY_SHELL
    assert "collapsed" in (marked.soft_risk_reason or "")


def test_mark_empty_shell_skips_cold_start():
    result = SyncResult(account_id="a1", account_synced=True, notes_imported=0)
    marked = _mark_empty_shell_soft_risk(result, prior_note_count=0, fetched_note_count=0)
    assert marked.soft_risk is False


def test_mark_empty_shell_skips_when_notes_fetched():
    result = SyncResult(account_id="a1", account_synced=True, notes_imported=3)
    marked = _mark_empty_shell_soft_risk(result, prior_note_count=5, fetched_note_count=3)
    assert marked.soft_risk is False


def test_live_success_excludes_soft_risk_and_fresh_skips():
    assert (
        _has_successful_live_sync(
            {
                "results": [
                    {
                        "account_synced": True,
                        "soft_risk": True,
                    }
                ]
            }
        )
        is False
    )
    assert (
        _has_successful_live_sync(
            {
                "results": [
                    {
                        "account_synced": True,
                        "niche_resolution": {"skipped": "fresh"},
                    }
                ]
            }
        )
        is False
    )
    assert (
        _has_successful_live_sync(
            {
                "results": [
                    {"account_synced": True, "notes_imported": 2},
                ]
            }
        )
        is True
    )


def test_batch_has_soft_risk():
    assert _batch_has_soft_risk({"results": [{"soft_risk": True}]}) is True
    assert _batch_has_soft_risk({"results": [{"account_synced": True}]}) is False


@pytest.mark.asyncio
async def test_empty_shell_preserves_previous_snapshot():
    previous = normalize_bundle(
        {"view_count": 100},
        [{"note_id": "existing", "view_count": 10}],
        "a1",
    )
    await upsert_bundle(previous.account, previous.notes)
    before = await get_account_stats("a1")
    assert before is not None

    class EmptyClient:
        async def fetch_all(self, _account_id: str, **_kwargs):
            return normalize_bundle({"view_count": 999}, [], "a1")

        async def aclose(self):
            return None

    result = await sync_from_creator_center(
        "a1",
        "",
        client=EmptyClient(),
        run_creative_analysis=False,
    )

    assert result.account_synced is True
    assert result.soft_risk is True
    assert result.error_code == ERROR_EMPTY_SHELL
    notes = await list_note_stats("a1")
    assert [note.note_id for note in notes] == ["existing"]
    after = await get_account_stats("a1")
    assert after is not None
    assert after.synced_at == before.synced_at


@pytest.mark.asyncio
async def test_client_cleanup_failure_does_not_mask_successful_import():
    bundle = normalize_bundle(
        {"view_count": 20},
        [{"note_id": "n1", "view_count": 2}],
        "cleanup-a1",
    )

    class FailingCleanupClient:
        async def fetch_all(self, _account_id: str, **_kwargs):
            return bundle

        async def aclose(self):
            raise RuntimeError("browser already disconnected")

    result = await sync_from_creator_center(
        "cleanup-a1",
        "",
        client=FailingCleanupClient(),
        run_creative_analysis=False,
    )

    assert result.account_synced is True
    assert result.error is None
    assert [note.note_id for note in await list_note_stats("cleanup-a1")] == ["n1"]
