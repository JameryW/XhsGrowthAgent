"""P1-2 scrape budget + nickname/ID minimization."""

from __future__ import annotations

import pytest

from backend.services.scrape_budget import (
    ERROR_SCRAPE_BUDGET_EXHAUSTED,
    ScrapeBudgetExhaustedError,
    check_budget,
    get_cache,
    mask_nickname,
    mask_user_id,
    minimize_scrape_row,
    record_success,
    reset_for_tests,
    usage,
)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("XHS_SCRAPE_HOMEFEED_DAILY_LIMIT", "2")
    monkeypatch.setenv("XHS_SCRAPE_SEARCH_DAILY_LIMIT", "2")
    monkeypatch.setenv("XHS_SCRAPE_COMMENTS_DAILY_LIMIT", "2")
    reset_for_tests()
    yield
    reset_for_tests()


def test_mask_helpers():
    assert mask_nickname("张三") == "张*"
    assert mask_nickname("小红薯创作者")[0] == "小"
    assert mask_user_id("abcdef123456") == "ab…56"
    assert mask_user_id("ab") == "***"


def test_minimize_masks_nested_user_fields():
    row = {
        "note_id": "n1",
        "display_title": "标题",
        "user": {"nickname": "真实昵称很长", "user_id": "deadbeefcafebabe"},
    }
    out = minimize_scrape_row(row)
    assert out["user"]["nickname"] != "真实昵称很长"
    assert "*" in out["user"]["nickname"]
    assert out["user"]["user_id"] != "deadbeefcafebabe"
    assert "…" in out["user"]["user_id"]
    assert out["display_title"] == "标题"


def test_budget_serves_cache_then_errors():
    record_success(
        "acc-1",
        "homefeed",
        [{"note_id": "a", "user": {"nickname": "甲", "user_id": "u1"}}],
    )
    record_success(
        "acc-1",
        "homefeed",
        [{"note_id": "b", "user": {"nickname": "乙", "user_id": "u2"}}],
    )
    snap = usage("acc-1")
    assert snap["used"]["homefeed"] == 2
    assert snap["remaining"]["homefeed"] == 0

    cached = check_budget("acc-1", "homefeed")
    assert isinstance(cached, list) and len(cached) >= 1
    assert get_cache("acc-1", "homefeed") is not None

    # Wipe cache → hard error with stable code.
    reset_for_tests()
    # Re-consume budget without leaving cache.
    from backend.services import scrape_budget as sb

    sb._daily_counts["acc-1"] = {sb._utc_day_key(): {"homefeed": 2, "search": 0, "comments": 0}}
    with pytest.raises(ScrapeBudgetExhaustedError) as exc:
        check_budget("acc-1", "homefeed")
    assert exc.value.error_code == ERROR_SCRAPE_BUDGET_EXHAUSTED
