"""Post-import niche bind + empty account-overview degradation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from backend.db.creator_stats import _reset_memory_store
from backend.services.creator_stats.client import CreatorStatsClient, FixtureTransport
from backend.services.creator_stats.normalize import normalize_bundle
from backend.services.creator_stats.pipeline import import_bundle, sync_from_fixture
from backend.services.niche_resolver import resolve_account_niche


@pytest.fixture(autouse=True)
def _clear():
    _reset_memory_store()
    yield
    _reset_memory_store()


@pytest.mark.asyncio
async def test_empty_account_overview_still_imports_notes():
    """data=[] / null overview must not block note list import."""
    transport = FixtureTransport(
        account_payload={"success": True, "data": []},
        notes_payload={
            "list": [
                {
                    "note_id": "only_note",
                    "title": "宝宝辅食记录",
                    "view_count": 100,
                    "like_count": 10,
                }
            ]
        },
    )
    client = CreatorStatsClient(cookie="c", transport=transport)
    bundle = await client.fetch_all("acc_empty_ov")
    assert len(bundle.notes) == 1
    assert bundle.notes[0].note_id == "only_note"
    assert bundle.account.views == 100  # filled from notes


@pytest.mark.asyncio
async def test_null_account_data_degrades_to_empty_dict():
    transport = FixtureTransport(
        account_payload={"success": True, "data": None},
        notes_payload=[{"note_id": "n", "view_count": 5, "like_count": 1}],
    )
    bundle = await CreatorStatsClient(cookie="c", transport=transport).fetch_all("a")
    assert len(bundle.notes) == 1


@pytest.mark.asyncio
async def test_import_bundle_syncs_real_creator_name_to_account_picker():
    """A browser-imported nickname becomes the durable account display name."""
    from backend.db.accounts import AccountRow

    bundle = normalize_bundle(
        {"view_count": 10},
        [],
        "profile_name_acc",
        profile_raw={"nickname": "真实创作者昵称"},
    )
    account = AccountRow(id="profile_name_acc", name="待登录账号")
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.db.accounts.update_account", new_callable=AsyncMock) as update,
    ):
        result = await import_bundle(bundle, run_creative_analysis=False)

    assert result.account_synced is True
    update.assert_awaited_once_with("profile_name_acc", name="真实创作者昵称")


@pytest.mark.asyncio
async def test_import_bundle_keeps_existing_name_when_profile_name_is_missing():
    """A partial profile response must not blank a user-visible account name."""
    from backend.db.accounts import AccountRow

    bundle = normalize_bundle({"view_count": 10}, [], "missing_profile_name")
    account = AccountRow(id="missing_profile_name", name="保留原账号名")
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.db.accounts.update_account", new_callable=AsyncMock) as update,
    ):
        await import_bundle(bundle, run_creative_analysis=False)

    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_fixture_import_never_replaces_account_display_name():
    """Only the real browser import path may alter the account picker label."""
    from backend.db.accounts import AccountRow

    bundle = normalize_bundle(
        {"view_count": 10},
        [],
        "fixture_profile_name",
        profile_raw={"nickname": "样例昵称"},
    )
    bundle.account.source = "fixture"
    account = AccountRow(id="fixture_profile_name", name="保留账号名")
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=account),
        patch("backend.db.accounts.update_account", new_callable=AsyncMock) as update,
    ):
        await import_bundle(bundle, run_creative_analysis=False)

    update.assert_not_awaited()


@pytest.mark.asyncio
async def test_import_bundle_attaches_inferred_niche_from_notes():
    bundle = normalize_bundle(
        {"view_count": 10},
        [
            {
                "note_id": "1",
                "title": "宝宝夜醒怎么办",
                "tags": ["母婴", "育儿"],
                "view_count": 100,
                "like_count": 10,
            },
            {
                "note_id": "2",
                "title": "辅食添加时间表",
                "tags": ["辅食"],
                "view_count": 50,
                "like_count": 5,
            },
        ],
        "import_niche_acc",
    )
    with (
        patch(
            "backend.db.accounts.get_account",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "backend.db.accounts.update_account",
            new_callable=AsyncMock,
        ) as upd,
    ):
        result = await import_bundle(bundle, run_creative_analysis=False)

    assert result.niche_resolution is not None
    assert result.niche_resolution["source"] == "inferred"
    assert result.niche_resolution["niche"] == "母婴"
    assert result.notes_imported == 2
    # persist attempted for inferred
    assert upd.await_count >= 1


@pytest.mark.asyncio
async def test_import_does_not_clobber_account_manual_niche():
    """If account.niche_source=manual, post-import infer must not overwrite."""
    from backend.db.accounts import AccountRow

    bundle = normalize_bundle(
        {},
        [
            {
                "note_id": "1",
                "title": "宝宝日常",
                "tags": ["母婴"],
                "view_count": 10,
                "like_count": 1,
            }
        ],
        "manual_acc",
    )
    manual_acc = AccountRow(
        id="manual_acc",
        name="x",
        niche="数码",
        niche_source="manual",
    )
    with (
        patch(
            "backend.db.accounts.get_account",
            new_callable=AsyncMock,
            return_value=manual_acc,
        ),
        patch(
            "backend.db.accounts.update_account",
            new_callable=AsyncMock,
        ) as upd,
    ):
        result = await import_bundle(bundle, run_creative_analysis=False)

    assert result.niche_resolution is not None
    assert result.niche_resolution["niche"] == "数码"
    assert result.niche_resolution["source"] == "account_bound"
    # Must not persist inferred 母婴 over manual 数码
    upd.assert_not_awaited()


@pytest.mark.asyncio
async def test_resolve_account_niche_protects_manual_binding():
    from backend.db.accounts import AccountRow

    acc = AccountRow(id="a1", name="n", niche="旅行", niche_source="manual")
    notes = [{"title": "宝宝辅食", "tags": ["母婴"]}]
    with patch(
        "backend.db.accounts.get_account",
        new_callable=AsyncMock,
        return_value=acc,
    ):
        res = await resolve_account_niche("a1", manual_niche="", notes=notes)
    assert res.niche == "旅行"
    assert res.source == "account_bound"


@pytest.mark.asyncio
async def test_sync_fixture_returns_niche_resolution():
    with (
        patch("backend.db.accounts.get_account", new_callable=AsyncMock, return_value=None),
        patch("backend.db.accounts.update_account", new_callable=AsyncMock),
    ):
        result = await sync_from_fixture("fx_niche")
    assert result.error is None
    assert result.notes_imported == 5
    assert result.niche_resolution is not None
    assert result.niche_resolution["niche"] == "母婴"
    assert result.niche_resolution["source"] == "inferred"
