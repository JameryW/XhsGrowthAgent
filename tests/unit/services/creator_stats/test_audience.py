from backend.services.creator_stats.audience import summarize_audience
from backend.services.creator_stats.types import AccountStatsOverview, NoteStats


def test_summarize_audience_orders_sources_and_periods():
    account = AccountStatsOverview(
        account_id="a",
        audience_sources=[
            {"title": "搜索", "value": 2},
            {"title": "首页", "value": 9},
        ],
        audience_view_periods=[
            {"start_point": "08:00", "end_point": "09:00", "count": 1},
            {"start_point": "20:00", "end_point": "21:00", "count": 8},
        ],
        audience_profile=[{"title": "女性", "value": 0.7}],
    )
    result = summarize_audience(account, [NoteStats(note_id="n", account_id="a")])
    assert result["source_distribution"][0]["title"] == "首页"
    assert result["peak_view_periods"][0]["start_point"] == "20:00"
    assert result["coverage"] == {
        "sources": True,
        "periods": True,
        "profile": True,
        "notes_with_view_sources": 0,
    }
    assert result["insights"]


def test_summarize_audience_marks_missing_dimensions_without_inventing_zeroes():
    result = summarize_audience(AccountStatsOverview(account_id="a"))
    assert result["source_distribution"] == []
    assert result["coverage"]["sources"] is False
    assert result["coverage"]["periods"] is False
    assert result["coverage"]["profile"] is False
