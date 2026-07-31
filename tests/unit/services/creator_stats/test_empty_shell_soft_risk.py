"""Empty-shell soft risk detection for creator stats imports."""

from __future__ import annotations

from backend.services.creator_stats.pipeline import (
    _batch_has_soft_risk,
    _has_successful_live_sync,
    _mark_empty_shell_soft_risk,
)
from backend.services.creator_stats.types import ERROR_EMPTY_SHELL, SyncResult, classify_sync_error


def test_classify_empty_shell_error_code():
    assert classify_sync_error("empty shell risk: notes collapsed") == ERROR_EMPTY_SHELL


def test_mark_empty_shell_when_prior_notes_collapse():
    result = SyncResult(account_id="a1", account_synced=True, notes_imported=0)
    marked = _mark_empty_shell_soft_risk(
        result, prior_note_count=5, fetched_note_count=0
    )
    assert marked.soft_risk is True
    assert marked.error_code == ERROR_EMPTY_SHELL
    assert "collapsed" in (marked.soft_risk_reason or "")


def test_mark_empty_shell_skips_cold_start():
    result = SyncResult(account_id="a1", account_synced=True, notes_imported=0)
    marked = _mark_empty_shell_soft_risk(
        result, prior_note_count=0, fetched_note_count=0
    )
    assert marked.soft_risk is False


def test_mark_empty_shell_skips_when_notes_fetched():
    result = SyncResult(account_id="a1", account_synced=True, notes_imported=3)
    marked = _mark_empty_shell_soft_risk(
        result, prior_note_count=5, fetched_note_count=3
    )
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
