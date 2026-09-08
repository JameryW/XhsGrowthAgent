from __future__ import annotations

import pytest
from pydantic import ValidationError as PydanticValidationError

from backend.creator_agent import (
    ContentObservation,
    ContentObservationKind,
    ContentObservationScan,
    CreatorAdvisor,
    CreatorModelDefinition,
    EvidenceProposal,
    EvidenceSource,
    PreferenceStance,
    build_evidence_proposals,
    observation_claim,
    observation_confidence,
    observation_evidence_id,
    observation_source_ref,
)
from backend.creator_agent.models import Evidence, ModelRevisionSource, Preference
from backend.db import creative_memory as creative_memory_db
from backend.db import creator_agent as creator_agent_db
from backend.memory.creator_agent_observations import CreativeMemoryObservationSource


@pytest.fixture(autouse=True)
def _reset_stores():
    creator_agent_db._reset_memory_store()
    creative_memory_db._reset_memory_store()
    yield
    creator_agent_db._reset_memory_store()
    creative_memory_db._reset_memory_store()


def _obs(
    kind: ContentObservationKind = ContentObservationKind.STYLE,
    source_id: str = "style-1",
    *,
    description: str = "治愈/温暖治愈",
    rate: float = 0.8,
    samples: int = 15,
    observed_at: str = "2026-09-01T00:00:00+00:00",
) -> ContentObservation:
    return ContentObservation(
        kind=kind,
        source_id=source_id,
        description=description,
        measured_rate=rate,
        sample_count=samples,
        observed_at=observed_at,
    )


class _FakeSource:
    def __init__(self, observations: list[ContentObservation]) -> None:
        self.observations_list = observations
        self.seen: list[tuple[str, int]] = []

    async def observations(self, account_id: str, *, window: int) -> ContentObservationScan:
        self.seen.append((account_id, window))
        return ContentObservationScan(observations=list(self.observations_list))


def test_identity_and_traceability_helpers_are_deterministic():
    observation = _obs()
    assert observation_source_ref(observation) == "creative-memory://style/style-1"
    assert observation_evidence_id(observation) == "ev_style_style-1"
    first = build_evidence_proposals([observation])
    second = build_evidence_proposals([observation])
    assert [p.model_dump() for p in first.items] == [p.model_dump() for p in second.items]
    assert first.items[0].proposal_id.startswith("prop_")
    assert first.items[0].evidence.source_kind is EvidenceSource.CREATOR_CONTENT


@pytest.mark.parametrize(
    ("rate", "samples", "expected"),
    [
        (0.8, 15, 0.6),  # 0.8 * 15/20
        (0.8, 0, 0.0),  # no proven samples earns nothing
        (0.8, 1, 0.133),  # 0.8 * 1/6
        (1.0, 1000, 0.995),  # large samples approach the rate, never exceed 1
        (0.0, 50, 0.0),
    ],
)
def test_confidence_shrinks_with_sample_size_and_stays_in_range(
    rate: float, samples: int, expected: float
):
    confidence = observation_confidence(_obs(rate=rate, samples=samples))
    assert confidence == pytest.approx(expected, abs=0.001)
    assert 0.0 <= confidence <= 1.0


def test_confidence_is_monotonic_in_rate_and_samples():
    low = observation_confidence(_obs(rate=0.3, samples=4))
    high = observation_confidence(_obs(rate=0.9, samples=4))
    more_samples = observation_confidence(_obs(rate=0.3, samples=40))
    assert high > low
    assert more_samples > low


def test_claims_are_numeric_renderings_per_kind():
    assert (
        observation_claim(_obs(description="治愈/温暖治愈", rate=0.5, samples=7))
        == "风格「治愈/温暖治愈」历史互动率 0.500（样本 7）"
    )
    play = _obs(ContentObservationKind.PLAY, "play-1", description="新品首发", rate=0.25, samples=2)
    assert observation_claim(play) == "打法「新品首发」平均互动率 0.250（验证 2 次）"
    material = _obs(
        ContentObservationKind.MATERIAL, "mat-1", description="文案片段", rate=0.4, samples=9
    )
    assert observation_claim(material) == "素材「文案片段」复用效果 0.400（复用 9 次）"


def test_proposals_are_ordered_by_confidence_then_source_ref_and_truncated():
    strong = _obs(source_id="b-strong", rate=0.95, samples=90)
    weak = _obs(source_id="a-weak", rate=0.2, samples=4)
    mid = _obs(source_id="c-mid", rate=0.6, samples=20)

    page = build_evidence_proposals([weak, mid, strong])
    proposals = page.items
    assert page.total == 3
    assert [p.evidence.source_ref for p in proposals] == [
        "creative-memory://style/b-strong",
        "creative-memory://style/c-mid",
        "creative-memory://style/a-weak",
    ]
    assert [p.evidence.confidence for p in proposals] == [0.9, 0.48, 0.089]

    limited = build_evidence_proposals([weak, mid, strong], limit=2).items
    assert [p.evidence.source_ref for p in limited] == [
        "creative-memory://style/b-strong",
        "creative-memory://style/c-mid",
    ]


def test_ties_break_on_source_ref_not_input_order():
    first = _obs(source_id="z", rate=0.5, samples=10)
    second = _obs(source_id="a", rate=0.5, samples=10)
    from_forward = build_evidence_proposals([first, second]).items
    from_reverse = build_evidence_proposals([second, first]).items
    assert [p.evidence.source_ref for p in from_forward] == [
        "creative-memory://style/a",
        "creative-memory://style/z",
    ]
    assert [p.evidence.source_ref for p in from_reverse] == [
        p.evidence.source_ref for p in from_forward
    ]


def test_already_cited_and_duplicate_observations_are_not_re_proposed():
    observation = _obs(source_id="style-1")
    duplicated = build_evidence_proposals([observation, observation])
    assert (len(duplicated.items), duplicated.total) == (1, 1)

    deduped = build_evidence_proposals(
        [observation, _obs(source_id="style-2")],
        cited_source_refs={observation_source_ref(observation)},
    )
    assert [p.evidence.source_ref for p in deduped.items] == ["creative-memory://style/style-2"]
    assert deduped.total == 1


def test_min_confidence_filters_before_limit():
    strong = _obs(source_id="s", rate=0.95, samples=90)
    weak = _obs(source_id="w", rate=0.2, samples=4)
    filtered = build_evidence_proposals([strong, weak], min_confidence=0.5, limit=50)
    assert [p.evidence.source_ref for p in filtered.items] == ["creative-memory://style/s"]
    assert (filtered.total, len(filtered.items)) == (1, 1)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"limit": 0},
        {"limit": 101},
        {"limit": True},
        {"min_confidence": 1.5},
        {"min_confidence": -0.1},
    ],
)
def test_invalid_bounds_fail_loudly(kwargs: dict):
    with pytest.raises(ValueError):
        build_evidence_proposals([_obs()], **kwargs)


def test_draft_preference_only_for_backed_observations():
    backed = build_evidence_proposals([_obs(source_id="rich", rate=0.9, samples=30)]).items[0]
    thin_samples = build_evidence_proposals([_obs(source_id="thin", rate=0.9, samples=2)]).items[0]
    thin_confidence = build_evidence_proposals(
        [_obs(source_id="lowrate", rate=0.2, samples=40)]
    ).items[0]

    assert backed.draft_preference is not None
    draft = backed.draft_preference
    assert draft is not None
    assert draft.stance is PreferenceStance.PREFER
    assert draft.applies_when == {}
    assert draft.strength == backed.evidence.confidence
    assert draft.evidence_ids == [backed.evidence.evidence_id]
    assert draft.label == "治愈/温暖治愈"
    assert thin_samples.draft_preference is None
    assert thin_confidence.draft_preference is None


def test_proposal_rejects_a_draft_that_cites_something_else():
    proposal = build_evidence_proposals([_obs()]).items[0]
    evidence = proposal.evidence
    with pytest.raises(PydanticValidationError, match="its own evidence"):
        EvidenceProposal(
            proposal_id=proposal.proposal_id,
            evidence=evidence,
            draft_preference=Preference(
                preference_id="pref-x",
                label="x",
                evidence_ids=["ev_something_else"],
            ),
        )
    with pytest.raises(PydanticValidationError, match="aversion"):
        EvidenceProposal(
            proposal_id=proposal.proposal_id,
            evidence=evidence,
            draft_preference=Preference(
                preference_id="pref-x",
                label="x",
                stance=PreferenceStance.AVOID,
                evidence_ids=[evidence.evidence_id],
            ),
        )


@pytest.mark.asyncio
async def test_adapter_maps_durable_rows_and_drops_unusable_ones():
    await creative_memory_db.upsert_style(
        "account-a",
        "s-good",
        {"tone": "治愈", "visual_style": "温暖", "engagement_rate": 0.8, "sample_count": 12},
    )
    await creative_memory_db.upsert_style(
        "account-a",
        "default_warm",
        {"tone": "治愈", "visual_style": "温暖", "engagement_rate": 0.99, "sample_count": 99},
    )
    await creative_memory_db.upsert_style(
        "account-a", "s-norate", {"tone": "专业", "visual_style": "高冷", "sample_count": 5}
    )
    await creative_memory_db.upsert_style(
        "account-a", "s-textrate", {"tone": "专业", "engagement_rate": "0.9", "sample_count": 5}
    )
    await creative_memory_db.upsert_play(
        "account-a",
        "p-1",
        {"trigger_condition": "新品首发", "avg_engagement_rate": 0.5, "proven_count": 4},
    )
    await creative_memory_db.upsert_material(
        "account-a", "m-1", {"category": "文案片段", "effectiveness": 0.7, "reuse_count": 6}
    )

    scan = await CreativeMemoryObservationSource().observations("account-a", window=50)
    by_id = {item.source_id: item for item in scan.observations}
    assert scan.saturated is False

    assert set(by_id) == {"s-good", "p-1", "m-1"}
    assert by_id["s-good"].kind is ContentObservationKind.STYLE
    assert by_id["s-good"].description == "治愈/温暖"
    assert by_id["p-1"].kind is ContentObservationKind.PLAY
    assert by_id["p-1"].sample_count == 4
    assert by_id["m-1"].kind is ContentObservationKind.MATERIAL
    assert by_id["m-1"].measured_rate == 0.7


@pytest.mark.asyncio
async def test_adapter_returns_nothing_for_blank_or_unknown_account():
    source = CreativeMemoryObservationSource()
    empty = await source.observations("   ", window=50)
    assert (empty.observations, empty.saturated) == ([], False)
    none = await source.observations("account-empty", window=50)
    assert (none.observations, none.saturated) == ([], False)


def _definition() -> CreatorModelDefinition:
    evidence = Evidence(
        evidence_id="e1",
        source_kind=EvidenceSource.CREATOR_STATEMENT,
        source_ref="creator://statement/1",
        claim="我优先耐用性",
    )
    return CreatorModelDefinition(identity_summary="证据型创作者", evidence=[evidence])


@pytest.mark.asyncio
async def test_advisor_propagates_scoping_without_touching_the_model():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    before = await repo.save_model("account-a", _definition(), expected_revision=0)
    source = _FakeSource([_obs(source_id="s-1"), _obs(source_id="s-2", rate=0.4, samples=8)])
    advisor = CreatorAdvisor(repo, content_observations=source)

    page = await advisor.list_evidence_proposals("  account-a  ", limit=10)

    assert source.seen == [("account-a", 60)]
    assert page.limit == 10
    assert [p.evidence.source_ref for p in page.items] == [
        "creative-memory://style/s-1",
        "creative-memory://style/s-2",
    ]
    after = await repo.get_model("account-a")
    assert after is not None
    assert after.model_dump() == before.model_dump()
    history = await advisor.list_model_revisions("account-a")
    assert history.total == 1
    assert history.items[0].source is ModelRevisionSource.CREATOR_EDIT


@pytest.mark.asyncio
async def test_advisor_dedupes_against_evidence_the_model_already_cites():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    observation = _obs(source_id="s-1")
    cited = _definition().model_dump()
    cited["evidence"].append(
        {
            "evidence_id": "ev_style_s-1",
            "source_kind": "creator_content",
            "source_ref": "creative-memory://style/s-1",
            "claim": "已采纳",
        }
    )
    await repo.save_model("account-a", CreatorModelDefinition(**cited), expected_revision=0)
    advisor = CreatorAdvisor(
        repo, content_observations=_FakeSource([observation, _obs(source_id="s-2")])
    )

    page = await advisor.list_evidence_proposals("account-a")
    assert [p.evidence.source_ref for p in page.items] == ["creative-memory://style/s-2"]
    assert page.total == 1


@pytest.mark.asyncio
async def test_advisor_without_a_source_or_bounds_degrades_to_empty_and_typed_errors():
    repo = creator_agent_db.DurableCreatorAgentRepository()
    await repo.save_model("account-a", _definition(), expected_revision=0)

    empty = await CreatorAdvisor(repo).list_evidence_proposals("account-a")
    assert (empty.items, empty.total, empty.truncated) == ([], 0, False)
    blank = await CreatorAdvisor(
        repo, content_observations=_FakeSource([])
    ).list_evidence_proposals("   ")
    assert (blank.items, blank.total, blank.truncated) == ([], 0, False)

    advisor = CreatorAdvisor(repo, content_observations=_FakeSource([_obs()]))
    with pytest.raises(ValueError, match="limit"):
        await advisor.list_evidence_proposals("account-a", limit=0)
    with pytest.raises(ValueError, match="min_confidence"):
        await advisor.list_evidence_proposals("account-a", min_confidence=2.0)


def test_creator_agent_core_does_not_import_content_production_storage():
    """The proposal seam must stay one-directional.

    ``backend/creator_agent`` consumes observations through a Protocol; if it
    ever imported Creative Memory storage directly, cold-start defaults and
    relevance ranking could leak into creator evidence.
    """
    import pathlib
    import re

    forbidden = re.compile(r"backend\.(memory|db\.creative_memory)")
    root = pathlib.Path("backend/creator_agent")
    offenders = {
        str(path): line
        for path in sorted(root.rglob("*.py"))
        for line in _import_lines(path)
        if forbidden.search(line)
    }
    assert offenders == {}


def _import_lines(path):
    import ast

    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]


def test_observation_models_reject_unmeasurable_input():
    with pytest.raises(PydanticValidationError):
        ContentObservation(
            kind=ContentObservationKind.STYLE,
            source_id="",
            description="x",
            measured_rate=0.5,
        )
    with pytest.raises(PydanticValidationError):
        ContentObservation(
            kind=ContentObservationKind.STYLE,
            source_id="s",
            description="x",
            measured_rate=1.5,
        )
