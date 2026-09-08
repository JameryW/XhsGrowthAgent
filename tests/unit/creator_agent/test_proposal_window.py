"""The proposal page must not reuse its page size as the storage scan window.

Each Creative Memory family picks rows with its own ordering — materials by
soft-demotion `weight`, styles/plays by raw measured rate — while the proposal
projection ranks by *sample-shrunk* confidence. When one `limit` value serves as
both the per-family fetch window and the page size, a small page silently drops
the most decisive observation and still returns something that looks correctly
ranked.
"""

from __future__ import annotations

import pytest

from backend.creator_agent import (
    ContentObservation,
    ContentObservationKind,
    ContentObservationScan,
    CreatorAdvisor,
    build_evidence_proposals,
)
from backend.db import creative_memory as creative_memory_db
from backend.db import creator_agent as creator_agent_db
from backend.memory.creator_agent_observations import CreativeMemoryObservationSource

DECISIVE = "creative-memory://material/m-decisive"


@pytest.fixture(autouse=True)
def _reset_stores():
    creator_agent_db._reset_memory_store()
    creative_memory_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()
    creative_memory_db._reset_memory_store()


def _advisor() -> CreatorAdvisor:
    return CreatorAdvisor(
        creator_agent_db.DurableCreatorAgentRepository(),
        content_observations=CreativeMemoryObservationSource(),
    )


async def _material(material_id: str, *, effectiveness: float, reuse: int, weight: float) -> None:
    await creative_memory_db.upsert_material(
        "account-a",
        material_id,
        {
            "category": "文案片段",
            "effectiveness": effectiveness,
            "reuse_count": reuse,
            "weight": weight,
        },
    )


class _RecordingSource:
    def __init__(self, observations: list[ContentObservation]) -> None:
        self._observations = observations
        self.windows: list[int] = []

    async def observations(self, account_id: str, *, window: int) -> ContentObservationScan:
        self.windows.append(window)
        return ContentObservationScan(observations=list(self._observations))


def _styles(count: int) -> list[ContentObservation]:
    return [
        ContentObservation(
            kind=ContentObservationKind.STYLE,
            source_id=f"s-{index}",
            description="治愈/温暖",
            measured_rate=0.9,
            sample_count=30,
        )
        for index in range(count)
    ]


@pytest.mark.asyncio
async def test_small_page_still_surfaces_the_strongest_observation():
    # Storage order hides the decisive row behind three higher-weight materials
    # and nine zero-sample materials whose raw rate is the account's highest.
    for index in range(3):
        await _material(f"m-noise-{index}", effectiveness=0.2, reuse=40, weight=1.0)
    for index in range(9):
        await _material(f"m-zero-{index}", effectiveness=0.99, reuse=0, weight=0.5)
    await _material("m-decisive", effectiveness=0.8, reuse=40, weight=0.2)

    page = await _advisor().list_evidence_proposals("account-a", limit=3)

    refs = [item.evidence.source_ref for item in page.items]
    assert DECISIVE in refs, "the decisive observation was cut by the scan window, not the page"
    assert refs[0] == DECISIVE
    assert page.items[0].evidence.confidence == 0.711
    assert page.total == 13
    assert page.limit == 3
    assert page.truncated is False


@pytest.mark.asyncio
async def test_a_saturated_window_is_reported_instead_of_looking_exhaustive():
    for index in range(120):
        await _material(f"m-{index}", effectiveness=0.5, reuse=20, weight=1.0)

    page = await _advisor().list_evidence_proposals("account-a", limit=2)

    # 120 materials exist, but the scan budget is max(60, limit * 4) == 60, so
    # total is a scanned floor here rather than an exhaustive count.
    assert page.truncated is True
    assert len(page.items) == 2
    assert page.total == 60


@pytest.mark.asyncio
async def test_page_size_never_changes_what_the_scan_considers():
    source = _RecordingSource(_styles(3))
    advisor = CreatorAdvisor(
        creator_agent_db.DurableCreatorAgentRepository(), content_observations=source
    )

    await advisor.list_evidence_proposals("account-a", limit=1)
    await advisor.list_evidence_proposals("account-a", limit=50)

    assert len(source.windows) == 2
    assert min(source.windows) >= 60, "the smallest page must still get a real candidate window"
    assert source.windows[0] < source.windows[1]
    # Same scan floor on both calls: the tiny page is not a tiny scan.
    assert source.windows[0] == 60


@pytest.mark.asyncio
async def test_no_source_or_blank_account_returns_an_explicit_empty_page():
    advisor = CreatorAdvisor(creator_agent_db.DurableCreatorAgentRepository())
    empty = await advisor.list_evidence_proposals("account-a", limit=7)

    assert (empty.items, empty.total, empty.limit, empty.truncated) == ([], 0, 7, False)

    sourced = CreatorAdvisor(
        creator_agent_db.DurableCreatorAgentRepository(), content_observations=_RecordingSource([])
    )
    blank = await sourced.list_evidence_proposals("   ")
    assert (blank.items, blank.total, blank.truncated) == ([], 0, False)


def test_projection_counts_matches_before_the_page_cut():
    page = build_evidence_proposals(_styles(5), limit=2)

    assert page.total == 5
    assert len(page.items) == 2
    assert page.truncated is False


def test_saturation_flows_through_the_projection():
    page = build_evidence_proposals(_styles(2), limit=50, scan_saturated=True)

    assert page.truncated is True
    assert page.total == 2
