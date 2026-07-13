"""Import path: fixture → normalize → persist → round-trip identity/metrics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.db.creator_stats import (
    _reset_memory_store,
    get_account_stats,
    get_note_stats,
    list_note_stats,
    upsert_account_stats,
    upsert_notes,
)
from backend.services.creator_stats.normalize import (
    normalize_account_overview,
    normalize_account_profile,
    normalize_bundle,
    normalize_note_list,
)
from backend.services.creator_stats.pipeline import (
    DEFAULT_FIXTURE_PATH,
    load_fixture_payload,
    sync_from_fixture,
    sync_from_payload,
)

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "creator_stats_sample.json"


@pytest.fixture(autouse=True)
def _clear_mem():
    _reset_memory_store()
    yield
    _reset_memory_store()


def test_fixture_file_exists_and_has_notes():
    assert FIXTURE.is_file()
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "account" in payload
    assert len(payload["notes"]) >= 3
    assert DEFAULT_FIXTURE_PATH.is_file()


def test_normalize_account_maps_creator_aliases():
    raw = {
        "view_count": 100,
        "like_count": 10,
        "comment_count": 2,
        "collect_count": 5,
        "share_count": 1,
        "fans_count": 50,
        "note_count": 3,
    }
    profile = {
        "data": {
            "userId": "creator-a",
            "userName": "创作者 A",
            "redId": "red_a",
            "userAvatar": "https://img.example/a.jpg",
            "userDesc": "账号简介",
            "role": "creator",
            "zone": "杭州",
            "phone": "must-not-be-saved",
        }
    }
    overview = normalize_account_overview(
        raw,
        "acc_a",
        period="30d",
        synced_at="t0",
        profile_raw=profile,
    )
    assert overview.account_id == "acc_a"
    assert overview.views == 100
    assert overview.likes == 10
    assert overview.comments == 2
    assert overview.collects == 5
    assert overview.shares == 1
    assert overview.fans == 50
    assert overview.note_count == 3
    assert overview.creator_user_id == "creator-a"
    assert overview.creator_name == "创作者 A"
    assert overview.red_id == "red_a"
    assert overview.avatar_url == "https://img.example/a.jpg"
    assert overview.bio == "账号简介"
    assert overview.creator_role == "creator"
    assert overview.zone == "杭州"
    assert "phone" not in overview.to_dict()


def test_normalize_account_profile_ignores_sensitive_and_nested_fields():
    profile = normalize_account_profile(
        {
            "data": {
                "userId": "creator-a",
                "phone": "must-not-be-saved",
                "permissions": {"creator": True},
                "realNameVerified": True,
            }
        }
    )
    assert profile["creator_user_id"] == "creator-a"
    assert set(profile) == {
        "creator_user_id",
        "creator_name",
        "red_id",
        "avatar_url",
        "bio",
        "creator_role",
        "zone",
    }


def test_normalize_notes_maps_metrics_and_engagement():
    raw = [
        {
            "note_id": "n1",
            "title": "测试标题",
            "view_count": 1000,
            "like_count": 50,
            "comment_count": 10,
            "collect_count": 20,
            "share_count": 5,
            "publish_time": "2026-06-01T00:00:00+00:00",
            "tags": ["母婴"],
        }
    ]
    notes = normalize_note_list(raw, "acc_a", synced_at="t0")
    assert len(notes) == 1
    n = notes[0]
    assert n.note_id == "n1"
    assert n.title == "测试标题"
    assert n.views == 1000
    assert n.likes == 50
    assert n.comments == 10
    assert n.collects == 20
    assert n.shares == 5
    assert n.engagement_rate == round((50 + 10 + 20 + 5) / 1000, 4)
    assert n.published_at.startswith("2026-06-01")


def test_normalize_bundle_fills_account_totals_from_notes():
    bundle = normalize_bundle({}, [{"note_id": "a", "view_count": 10, "like_count": 2}], "acc")
    assert bundle.account.views == 10
    assert bundle.account.likes == 2
    assert bundle.account.note_count == 1


def test_normalize_creator_insights_keeps_aggregate_data_and_drops_tokens():
    raw = {
        "data": {"thirty": {"view_count": 10}},
        "_creator_insights": {
            "audience_source": {
                "data": {"thirty": [{"title": "首页", "value": 8, "xsec_token": "drop"}]}
            },
            "audience_periods": {
                "data": {"thirty": [{"start_point": "20:00", "end_point": "21:00", "count": 5}]}
            },
            "note_detail": {
                "data": {
                    "thirty": {
                        "gender": [{"title": "女性", "value": 0.7}],
                        "xsec_token": "drop",
                    }
                }
            },
        },
    }
    overview = normalize_account_overview(raw, "acc-insight", period="30d", synced_at="t0")
    assert overview.audience_sources == [{"title": "首页", "value": 8}]
    assert overview.audience_view_periods[0]["start_point"] == "20:00"
    assert overview.audience_profile == [{"title": "女性", "value": 0.7}]
    assert "xsec_token" not in overview.detail_metrics


@pytest.mark.asyncio
async def test_upsert_round_trip_identity_and_metrics():
    payload = load_fixture_payload(FIXTURE)
    bundle = normalize_bundle(
        payload["account"],
        payload["notes"],
        "acct_rt",
        period="30d",
        synced_at="2026-07-12T00:00:00+00:00",
        profile_raw=payload["profile"],
    )
    await upsert_account_stats(bundle.account)
    imported, updated = await upsert_notes(bundle.notes)
    assert imported == len(bundle.notes)
    assert updated == 0

    loaded_account = await get_account_stats("acct_rt")
    assert loaded_account is not None
    assert loaded_account.views == bundle.account.views
    assert loaded_account.likes == bundle.account.likes
    assert loaded_account.comments == bundle.account.comments
    assert loaded_account.collects == bundle.account.collects
    assert loaded_account.shares == bundle.account.shares
    assert loaded_account.creator_user_id == bundle.account.creator_user_id
    assert loaded_account.creator_name == bundle.account.creator_name
    assert loaded_account.red_id == bundle.account.red_id
    assert loaded_account.avatar_url == bundle.account.avatar_url
    assert loaded_account.bio == bundle.account.bio
    assert loaded_account.creator_role == bundle.account.creator_role
    assert loaded_account.zone == bundle.account.zone

    notes = await list_note_stats("acct_rt", limit=20)
    assert len(notes) == len(bundle.notes)
    by_id = {n.note_id: n for n in notes}
    for original in bundle.notes:
        got = by_id[original.note_id]
        assert got.title == original.title
        assert got.views == original.views
        assert got.likes == original.likes
        assert got.comments == original.comments
        assert got.collects == original.collects
        assert got.shares == original.shares
        assert got.published_at == original.published_at

    # single get
    one = await get_note_stats("acct_rt", "note_heal_001")
    assert one is not None
    assert one.views == 42000
    assert one.likes == 3800


@pytest.mark.asyncio
async def test_upsert_is_idempotent_by_note_id():
    payload = load_fixture_payload(FIXTURE)
    result1 = await sync_from_payload(
        "acct_idem", payload["account"], payload["notes"], source="fixture"
    )
    assert result1.notes_imported == 5
    assert result1.notes_updated == 0

    result2 = await sync_from_payload(
        "acct_idem", payload["account"], payload["notes"], source="fixture"
    )
    assert result2.notes_imported == 0
    assert result2.notes_updated == 5

    notes = await list_note_stats("acct_idem")
    assert len(notes) == 5


@pytest.mark.asyncio
async def test_missing_profile_response_does_not_clear_previously_saved_profile():
    payload = load_fixture_payload(FIXTURE)
    await sync_from_payload(
        "acct_profile_keep",
        payload["account"],
        payload["notes"],
        profile_raw=payload["profile"],
        source="fixture",
    )
    await sync_from_payload(
        "acct_profile_keep",
        payload["account"],
        payload["notes"],
        profile_raw=None,
        source="creator_statistics",
    )

    account = await get_account_stats("acct_profile_keep")
    assert account is not None
    assert account.creator_name == "温柔育儿笔记"
    assert account.red_id == "gentle_parenting"
    assert account.avatar_url == "https://example.com/avatar.jpg"


@pytest.mark.asyncio
async def test_sync_from_fixture_entry_returns_import_counts():
    result = await sync_from_fixture("acct_entry")
    assert result.error is None
    assert result.account_synced is True
    assert result.notes_imported == 5
    assert result.source == "fixture"
    assert result.analysis is not None
    assert result.analysis.note_count == 5
