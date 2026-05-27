"""Cost tracker tests."""

from backend.models.cost_tracker import CostTracker


def test_record_usage():
    """记录用量"""
    tracker = CostTracker(daily_budget_usd=10.0)
    tracker.record("deepseek-chat", "scouting", 1000, 500)
    assert tracker.today_total() > 0
    assert not tracker.circuit_open


def test_circuit_breaker():
    """预算熔断"""
    tracker = CostTracker(daily_budget_usd=0.001)
    tracker.record("claude-sonnet-4-20250514", "writing", 100000, 50000)
    assert tracker.circuit_open


def test_summary():
    """成本摘要"""
    tracker = CostTracker(daily_budget_usd=10.0)
    tracker.record("deepseek-chat", "scouting", 1000, 500)
    tracker.record("gpt-4o", "analysis", 2000, 1000)

    summary = tracker.summary()
    assert summary["total_calls"] == 2
    assert "deepseek-chat" in summary["by_model"]
    assert "gpt-4o" in summary["by_model"]
