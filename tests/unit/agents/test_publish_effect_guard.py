"""Publish guard copy per effect status (P0-B: six states, three messages)."""

from __future__ import annotations

from backend.agents.publisher import _blocked_duplicate_result


class TestBlockedCopy:
    def test_confirmed_says_already_published(self):
        result = _blocked_duplicate_result("p1", {"status": "confirmed"})
        assert "已成功发布" in result["error"]
        assert result["error_type"] == "duplicate_publish_blocked"

    def test_legacy_published_spelling_says_already_published(self):
        result = _blocked_duplicate_result("p1", {"status": "published"})
        assert "已成功发布" in result["error"]

    def test_unknown_says_result_unclear(self):
        result = _blocked_duplicate_result("p1", {"status": "unknown"})
        assert "结果不明" in result["error"]

    def test_reconciling_says_result_unclear(self):
        result = _blocked_duplicate_result("p1", {"status": "reconciling"})
        assert "结果不明" in result["error"]

    def test_in_flight_says_in_progress(self):
        result = _blocked_duplicate_result("p1", {"status": "in_flight"})
        assert "正在进行" in result["error"]

    def test_prepared_reaches_in_progress_branch_when_reported(self):
        # PREPARED does not block, but if a caller asks for the copy anyway the
        # message must not claim the note exists.
        result = _blocked_duplicate_result("p1", {"status": "prepared"})
        assert "已成功发布" not in result["error"]
        assert "结果不明" not in result["error"]
