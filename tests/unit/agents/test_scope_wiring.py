"""票 5g / §9.6 — the declared ``auth_scope`` is applied on the read paths.

``test_scope_coverage.py`` counts *whether* a call site passes
``granted_scopes`` (recomputed from the tree, so a dropped argument fails
there). This file pins what the wiring **does**, which the AST cannot see:

* the resolved grant actually reaches ``invoke`` — a tuple that never leaves
  the call site leaves the declaration exactly as decorative as it was;
* the grant is resolved for the identity the tool will authenticate as — and
  for ``xhs.competitor_analyzer`` that is *not* the value sitting in its
  payload's ``account_id`` key, which is the niche;
* a missing ``xhs:read`` skips the reads and degrades **without** letting
  ``PermissionDeniedError`` out — these three calls were always "no data"
  shaped, and the caller's decision to degrade stays where it was;
* the skip is itself an event (票 5j, ``TestASkippedReadIsVisibleInTheTrace``):
  "we hold no ``xhs:read``" must not be indistinguishable from "these reads
  were never planned".

The refusal is *not* tested by catching an exception. Catching one would only
prove the code raised; the assertion here is on the outcome value, so a
mutation that lets the refusal escape (instead of degrading) fails as an
assertion rather than as a crash.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.base import BaseAgent
from backend.agents.content_strategist import ContentStrategistAgent
from backend.agents.trend_scout import TrendScoutAgent
from backend.config.models import TaskType
from backend.tools.runtime.bridge import tracing_to
from backend.tools.runtime.models import ToolResult

_SHARED_GATEWAY = "backend.tools.runtime.bridge.shared_gateway"
_GRANTED_SCOPES = "backend.services.xhs_credentials.granted_scopes"

#: Distinguishable on purpose: a call site that hardcodes ``("xhs:read",)``
#: instead of handing over the tuple it resolved fails the equality below.
_GRANT = ("xhs:read", "xhs:write")


class _RecordingTools:
    """A stand-in for ``agent.tools`` that records the grant it was handed.

    It also answers ``trace_skipped`` (票 5j): the call site now reports the
    skipped read through the Gateway seam, so a stand-in that only has
    ``invoke`` would turn a legitimately skipped call into an ``AttributeError``
    — i.e. the double would invent the failure the production path degrades
    from.
    """

    def __init__(self, values: dict[str, Any] | None = None) -> None:
        self.seen: list[tuple[str, dict[str, Any], tuple[str, ...] | None]] = []
        self.skips: list[tuple[str, tuple[str, ...], str, str]] = []
        self.values = values or {}

    async def invoke(
        self,
        capability: str,
        payload: Any = None,
        *,
        thread_id: str = "",
        granted_scopes: tuple[str, ...] | None = None,
    ) -> ToolResult:
        self.seen.append((capability, dict(payload or {}), granted_scopes))
        return ToolResult(capability=capability, ok=True, value=self.values.get(capability))

    async def trace_skipped(
        self,
        capability: str,
        *,
        granted: tuple[str, ...],
        account_id: str = "",
        thread_id: str = "",
    ) -> None:
        self.skips.append((capability, tuple(granted), account_id, thread_id))


def _granting(accounts: list[str], scopes: tuple[str, ...] = _GRANT):
    """A ``granted_scopes`` stand-in that records which identity it was asked about."""

    async def _fake(account_id: str, **kwargs: Any) -> tuple[str, ...]:
        accounts.append(account_id)
        return scopes

    return _fake


def _tool_returning(rows: Any) -> MagicMock:
    """A tool body double with data in it — so "called" is distinguishable."""
    double = MagicMock()
    double.ainvoke = AsyncMock(return_value=rows)
    return double


class TestTheGrantTravelsWithTheInvocation:
    @pytest.mark.asyncio
    async def test_all_three_scout_reads_carry_the_resolved_grant(self, monkeypatch):
        """One judgement, three enforcements — the same tuple, every time."""
        asked: list[str] = []
        monkeypatch.setattr(_GRANTED_SCOPES, _granting(asked))
        tools = _RecordingTools(
            values={
                "xhs.trending": [{"topic": "露营", "heat_score": 88}],
                "xhs.competitor_analyzer": [{"account": "竞品A"}],
                "xhs.keyword_monitor": [{"keyword": "母婴"}],
            }
        )
        agent = TrendScoutAgent()

        with patch(_SHARED_GATEWAY, lambda: tools):
            data = await agent._fetch_real_data("母婴", account_id="acc-7", thread_id="t-1")

        assert [capability for capability, _, _ in tools.seen] == [
            "xhs.trending",
            "xhs.competitor_analyzer",
            "xhs.keyword_monitor",
        ], "gather order: trending, competitor, then the serial keyword monitor"
        assert [grant for _, _, grant in tools.seen] == [_GRANT] * 3
        assert asked == ["acc-7"], "one resolution per fetch, not one per call"
        assert data["hot_topics"] == [{"topic": "露营", "heat_score": 88}]
        assert data["keyword_monitor"] == [{"keyword": "母婴"}]

    @pytest.mark.asyncio
    async def test_topic_scoring_carries_the_resolved_grant(self, monkeypatch):
        asked: list[str] = []
        monkeypatch.setattr(_GRANTED_SCOPES, _granting(asked))
        tools = _RecordingTools(
            values={"analysis.topic_scorer": {"heat_score": 82, "growth_trend": "爆发期"}}
        )
        agent = ContentStrategistAgent()

        with patch(_SHARED_GATEWAY, lambda: tools):
            context = await agent._score_trend_topics(
                {"hot_topics": [{"topic": "探店"}]}, "美食", account_id="acc-9"
            )

        assert [(capability, grant) for capability, _, grant in tools.seen] == [
            ("analysis.topic_scorer", _GRANT)
        ]
        assert asked == ["acc-9"]
        assert "82" in context

    @pytest.mark.asyncio
    async def test_a_real_cookie_produces_the_grant_that_travels(self, monkeypatch, xhs_read_grant):
        """End to end: env -> credential -> grant -> invoke (no stub in the middle)."""
        tools = _RecordingTools(values={"xhs.trending": []})
        agent = TrendScoutAgent()

        with patch(_SHARED_GATEWAY, lambda: tools):
            await agent._fetch_real_data("母婴", account_id="acc-7", thread_id="t-1")

        trending = [entry for entry in tools.seen if entry[0] == "xhs.trending"]
        assert trending[0][2] == xhs_read_grant, "the real resolver's grant is what travels"


class TestTheGrantFollowsTheCredentialIdentity:
    @pytest.mark.asyncio
    async def test_competitor_is_attributed_to_the_credential_account_not_the_niche(
        self, monkeypatch
    ):
        """``credential_account_id`` is the identity; ``account_id`` is the niche.

        The payload's ``account_id`` key holds the competitor keyword here, so a
        resolution that follows the payload's *field name* instead of the
        identity would ask for a grant belonging to "竞品B" — an account that is
        the thing being looked at, not the one doing the looking.
        """
        asked: list[str] = []
        monkeypatch.setattr(_GRANTED_SCOPES, _granting(asked))
        tools = _RecordingTools(values={"xhs.competitor_analyzer": []})
        agent = TrendScoutAgent()

        with patch(_SHARED_GATEWAY, lambda: tools):
            await agent._fetch_real_data("竞品B", account_id="acc-7", thread_id="t-1")

        assert asked == ["acc-7"]
        # Fetched by capability, not by position: the gather's completion order
        # is not the point of this test, and a positional lookup would report a
        # wrong-answer as a KeyError instead of as a failed assertion.
        competitor = [entry for entry in tools.seen if entry[0] == "xhs.competitor_analyzer"]
        assert len(competitor) == 1
        payload = competitor[0][1]
        assert payload.get("credential_account_id") == "acc-7", "the identity the tool resolves"
        assert payload.get("account_id") == "竞品B", "the competitor keyword, unchanged"

    @pytest.mark.asyncio
    async def test_the_reads_are_attributed_to_the_account_not_the_deployment(self, monkeypatch):
        asked: list[str] = []
        monkeypatch.setattr(_GRANTED_SCOPES, _granting(asked))
        tools = _RecordingTools(values={"xhs.trending": []})
        agent = TrendScoutAgent()

        with patch(_SHARED_GATEWAY, lambda: tools):
            await agent._fetch_real_data("母婴", account_id="", thread_id="t-1")

        assert asked == [""], "a blank account id is the deployment's own declaration"
        trending = [entry for entry in tools.seen if entry[0] == "xhs.trending"]
        assert trending[0][1].get("account_id") == ""


class TestARefusalDegradesInsteadOfEscaping:
    @pytest.mark.asyncio
    async def test_the_platform_reads_are_skipped_without_the_read_scope(self, monkeypatch):
        monkeypatch.setattr(_GRANTED_SCOPES, _granting([], scopes=()))
        # The doubles carry data: if the calls went out, ``data`` would not be
        # empty, so this assertion cannot pass by way of an empty stub.
        tools = _RecordingTools(
            values={
                "xhs.trending": [{"topic": "露营"}],
                "xhs.competitor_analyzer": [{"account": "竞品A"}],
                "xhs.keyword_monitor": [{"keyword": "母婴"}],
            }
        )
        agent = TrendScoutAgent()

        with patch(_SHARED_GATEWAY, lambda: tools):
            data = await agent._fetch_real_data("母婴", account_id="acc-7", thread_id="t-1")

        assert tools.seen == [], "not called at all: the grant said it could not read"
        assert data == {}, "the same empty shape a failed read has always produced"

    @pytest.mark.asyncio
    async def test_the_refusal_does_not_escape_as_a_permission_error(self, monkeypatch):
        """Outcome-valued on purpose — see the module docstring.

        This one runs against the **real** gateway (only the tool bodies are
        doubled), because the thing being pinned is that the refusal never
        reaches the caller: ``ToolGateway._check_scopes`` raises
        ``PermissionDeniedError`` *before* the tool runs, and these three calls
        are documented as "no try/except — failures arrive as data". Without
        the call-site judgement, a single unreadable account would take the
        whole scout node down instead of degrading.
        """
        monkeypatch.setattr(_GRANTED_SCOPES, _granting([], scopes=()))
        agent = TrendScoutAgent()
        outcome = "not-run"

        with (
            patch("backend.tools.xhs.trending.xhs_trending", new=_tool_returning([])),
            patch("backend.tools.xhs.trending.keyword_monitor", new=_tool_returning([])),
            patch("backend.tools.xhs.trending.competitor_analyzer", new=_tool_returning([])),
        ):
            try:
                data = await agent._fetch_real_data("母婴", account_id="acc-7", thread_id="t-1")
            except PermissionError as exc:
                outcome = f"escaped: {type(exc).__name__}"
            else:
                outcome = "degraded" if data == {} else f"unexpected:{data}"

        assert outcome == "degraded", "a refusal is the caller's degrade, never a crash"

    @pytest.mark.asyncio
    async def test_the_web_fallback_still_gets_its_chance(self, monkeypatch):
        """Authorization skips the XHS reads only — it is not a silent degrade."""
        monkeypatch.setattr(_GRANTED_SCOPES, _granting([], scopes=()))
        tools = _RecordingTools(values={"search.web": {"results": [{"url": "u", "summary": "s"}]}})
        agent = TrendScoutAgent()

        with (
            patch(_SHARED_GATEWAY, lambda: tools),
            patch.object(type(agent), "_web_search_available", lambda self: True),
        ):
            data = await agent._fetch_real_data("母婴", account_id="acc-7", user_topic="露营")

        assert [capability for capability, _, _ in tools.seen] == ["search.web"], (
            "web enrichment is a different provider and needs no xhs scope"
        )
        assert data["web_search"]["results"]

    @pytest.mark.asyncio
    async def test_topic_scoring_is_skipped_without_the_read_scope(self, monkeypatch):
        monkeypatch.setattr(_GRANTED_SCOPES, _granting([], scopes=()))
        tools = _RecordingTools()
        agent = ContentStrategistAgent()

        with patch(_SHARED_GATEWAY, lambda: tools):
            context = await agent._score_trend_topics(
                {"hot_topics": [{"topic": "探店"}]}, "美食", account_id="acc-9"
            )

        assert tools.seen == []
        assert context == "", "the same empty section every per-topic failure produces"


class TestASkippedReadIsVisibleInTheTrace:
    """票 5j — the §9.6 cost is paid off: the skip itself is an event.

    5g kept the call-site judgement (no grant ⇒ do not even ask), which meant an
    unauthorized account produced *no* tool event at all: the trace could not
    tell "we hold no ``xhs:read``" from "these reads were never planned". The
    call site now writes ``event:"skipped"`` through the same sink an invocation
    uses; ``attempts:0`` and ``scopes:"missing"`` keep it from reading as a
    failed call, which is the other thing that can produce ``ok=False``.
    """

    @staticmethod
    def _sink(events: list[dict[str, Any]]):
        async def sink(event: Mapping[str, Any]) -> None:
            events.append(dict(event))

        return sink

    @pytest.mark.asyncio
    async def test_the_three_skipped_reads_are_recorded(self, monkeypatch):
        monkeypatch.setattr(_GRANTED_SCOPES, _granting([], scopes=()))
        agent = TrendScoutAgent()
        events: list[dict[str, Any]] = []

        with tracing_to(self._sink(events)):
            data = await agent._fetch_real_data("母婴", account_id="acc-7", thread_id="t-1")

        assert data == {}, "the degrade shape is unchanged"
        skipped = {
            str(event.get("capability")): event
            for event in events
            if event.get("event") == "skipped"
        }
        assert set(skipped) == {
            "xhs.trending",
            "xhs.competitor_analyzer",
            "xhs.keyword_monitor",
        }, "one event per read this branch skipped, not one for the branch"
        assert [event for event in events if event.get("event") == "invoke"] == []
        for capability, event in skipped.items():
            assert event.get("attempts") == 0, capability
            assert event.get("ok") is False, capability
            assert event.get("scopes") == "missing", capability
            assert event.get("reason") == "missing_scope", capability
            assert event.get("missing_scopes") == ["xhs:read"], capability
            assert event.get("account_id") == "acc-7", capability
            assert event.get("thread_id") == "t-1", capability

    @pytest.mark.asyncio
    async def test_a_permitted_read_records_invocations_and_no_skips(
        self, monkeypatch, xhs_read_grant
    ):
        """The reverse direction: an authorized account must not get skip events."""
        agent = TrendScoutAgent()
        events: list[dict[str, Any]] = []

        with (
            tracing_to(self._sink(events)),
            patch(
                "backend.tools.xhs.trending.xhs_trending",
                new=_tool_returning([{"topic": "露营"}]),
            ),
            patch("backend.tools.xhs.trending.keyword_monitor", new=_tool_returning([])),
            patch("backend.tools.xhs.trending.competitor_analyzer", new=_tool_returning([])),
        ):
            await agent._fetch_real_data("母婴", account_id="acc-7", thread_id="t-1")

        invoked = {
            str(event.get("capability")) for event in events if event.get("event") == "invoke"
        }
        assert invoked == {
            "xhs.trending",
            "xhs.competitor_analyzer",
            "xhs.keyword_monitor",
        }
        assert [event for event in events if event.get("event") == "skipped"] == []

    @pytest.mark.asyncio
    async def test_topic_scoring_skip_is_recorded(self, monkeypatch):
        monkeypatch.setattr(_GRANTED_SCOPES, _granting([], scopes=()))
        agent = ContentStrategistAgent()
        events: list[dict[str, Any]] = []

        with tracing_to(self._sink(events)):
            context = await agent._score_trend_topics(
                {"hot_topics": [{"topic": "探店"}]}, "美食", account_id="acc-9"
            )

        assert context == ""
        skipped = [event for event in events if event.get("event") == "skipped"]
        assert len(skipped) == 1, "one decision, one capability: not one event per topic"
        event = skipped[0]
        assert event.get("capability") == "analysis.topic_scorer"
        assert event.get("missing_scopes") == ["xhs:read"]
        assert event.get("attempts") == 0
        assert event.get("account_id") == "acc-9"

    @pytest.mark.asyncio
    async def test_the_skip_event_reaches_the_event_store(self):
        """Through ``__call__``: the node's sink names the thread the caller omitted."""
        from backend.db.workflow_events import list_events

        class _SkipAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "skip_agent"
            prompt_file = ""

            async def execute(self, state: Any, store: Any) -> dict[str, Any]:
                await self.tools.trace_skipped("xhs.trending", granted=(), account_id="acc-7")
                return {"ok": True}

        await _SkipAgent()({"thread_id": "t-1"}, store=AsyncMock())

        events = await list_events("t-1", kind="tool")
        assert len(events) == 1
        assert events[0].get("event") == "skipped"
        assert events[0].get("thread_id") == "t-1", (
            "the node's sink supplies the thread id when the call site has none"
        )
