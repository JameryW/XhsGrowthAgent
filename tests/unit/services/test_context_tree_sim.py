"""Context-Tree deterministic dry-run simulator tests (MCP-Persona-style)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.services.context_tree_sim import (
    ContextTree,
    SimulationConfig,
    simulate_publish,
)


def test_valid_publish_creates_post() -> None:
    result = simulate_publish(
        {
            "account_id": "acct-1",
            "title": "新手化妆步骤",
            "body": "先保湿，再上底妆。",
            "hashtags": ["化妆", "教程"],
            "image_count": 2,
        }
    )
    assert result["status"] == "published"
    assert result["post_id"].startswith("post_")
    assert result["errors"] == []


def test_title_over_20_chars_is_rejected() -> None:
    result = simulate_publish(
        {
            "account_id": "acct-1",
            "title": "这是一条超过二十个字符的小红书笔记标题内容",
            "body": "正文",
            "image_count": 1,
        }
    )
    assert result["status"] == "rejected"
    assert "TITLE_TOO_LONG" in [item["code"] for item in result["errors"]]


def test_body_and_image_boundaries() -> None:
    result = simulate_publish(
        {
            "account_id": "acct-1",
            "title": "标题",
            "body": "正" * 1001,
            "image_count": 0,
        }
    )
    codes = [item["code"] for item in result["errors"]]
    assert "BODY_TOO_LONG" in codes
    assert "NO_IMAGES" in codes


def test_banned_term_and_signature_fault() -> None:
    result = simulate_publish(
        {
            "account_id": "acct-1",
            "title": "最好用的面霜",
            "body": "绝对回购",
            "image_count": 1,
            "injected_faults": ["signature_unavailable"],
        }
    )
    codes = [item["code"] for item in result["errors"]]
    assert "BANNED_TERM" in codes
    assert "SIGNATURE_UNAVAILABLE" in codes


def test_daily_post_limit_is_enforced() -> None:
    config = SimulationConfig(daily_post_limit=1)
    tree = ContextTree(config=config)
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    first = simulate_publish(
        {"account_id": "acct-1", "title": "首发笔记", "body": "正文", "image_count": 1},
        config=config,
        tree=tree,
        now=now,
    )
    assert first["status"] == "published"
    second = simulate_publish(
        {"account_id": "acct-1", "title": "第二篇笔记", "body": "正文", "image_count": 1},
        config=config,
        tree=tree,
        now=now,
    )
    assert "RATE_LIMITED" in [item["code"] for item in second["errors"]]


def test_session_expiry_and_dm_quota() -> None:
    tree = ContextTree(config=SimulationConfig(dm_quota=1))
    now = datetime(2026, 11, 15, 12, tzinfo=UTC)
    tree.add_user("u1")
    tree.add_account("acct-1", "u1", session_valid_until=now - timedelta(minutes=1))
    draft = tree.create_draft("acct-1", "标题", "正文", image_count=1)
    errors = tree.check_draft(draft, now=now)
    assert "SESSION_EXPIRED" in [item["code"] for item in errors]
    assert tree.send_dm("acct-1", "u1", "hi")["status"] == "sent"
    assert tree.send_dm("acct-1", "u1", "hi again")["errors"][0]["code"] == "DM_QUOTA_EXHAUSTED"


def test_trace_always_present() -> None:
    result = simulate_publish(
        {"account_id": "acct-1", "title": "标题", "body": "正文", "image_count": 1}
    )
    assert result["trace"]["simulator"] == "context-tree"
    assert result["trace"]["draft_id"].startswith("draft_")
