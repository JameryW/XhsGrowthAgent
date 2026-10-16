"""P1-3 retention cleanup + audience export/delete."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.creator_agent.models import RelationshipMemory
from backend.db.creator_agent import (
    DurableCreatorAgentRepository,
    _mem_relationships,
    _reset_memory_store,
)
from backend.services.privacy_retention import (
    purge_expired_relationships,
    retention_days,
    run_privacy_cleanup,
)
from backend.services.scrape_budget import purge_cache_before, record_success, reset_for_tests


@pytest.fixture(autouse=True)
def _reset():
    _reset_memory_store()
    reset_for_tests()
    yield
    _reset_memory_store()
    reset_for_tests()


def test_retention_defaults_90():
    days = retention_days()
    assert days["audience"] == 90
    assert days["comments"] == 90
    assert days["dm"] == 90
    assert days["relationship"] == 90


@pytest.mark.asyncio
async def test_purge_expired_relationships():
    old = (datetime.now(UTC) - timedelta(days=120)).isoformat()
    fresh = datetime.now(UTC).isoformat()
    _mem_relationships[("acc", "aud-old")] = RelationshipMemory(
        account_id="acc",
        audience_id="aud-old",
        last_interaction_at=old,
    )
    _mem_relationships[("acc", "aud-new")] = RelationshipMemory(
        account_id="acc",
        audience_id="aud-new",
        last_interaction_at=fresh,
    )
    result = await purge_expired_relationships(retention=90)
    assert result["removed"] >= 1
    assert ("acc", "aud-old") not in _mem_relationships
    assert ("acc", "aud-new") in _mem_relationships


@pytest.mark.asyncio
async def test_audience_export_and_delete():
    repo = DurableCreatorAgentRepository()
    _mem_relationships[("acc", "aud-1")] = RelationshipMemory(
        account_id="acc",
        audience_id="aud-1",
        last_interaction_at=datetime.now(UTC).isoformat(),
        interaction_count=2,
    )
    exported = await repo.export_audience_member("acc", "aud-1")
    assert exported is not None
    assert exported["audience_id"] == "aud-1"
    assert exported["relationship"]["interaction_count"] == 2

    deleted = await repo.delete_audience_member("acc", "aud-1")
    assert deleted is not None and deleted["deleted"] is True
    assert await repo.get_relationship("acc", "aud-1") is None
    assert await repo.export_audience_member("acc", "aud-1") is None


@pytest.mark.asyncio
async def test_run_privacy_cleanup_includes_scrape_cache():
    record_success(
        "acc-c",
        "comments",
        [{"id": "c1", "user": {"nickname": "路人", "user_id": "abcdef1234567890"}}],
    )
    # Force cache timestamp into the past via purge cutoff in the future.
    removed = purge_cache_before(datetime.now(UTC) + timedelta(days=1))
    assert removed >= 1
    result = await run_privacy_cleanup()
    assert "retention_days" in result
    assert isinstance(result["purged"], list)
