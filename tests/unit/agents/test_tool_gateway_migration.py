"""P1c-S3 migration proofs: agents reach tools *through* the Gateway.

The pre-existing agent tests double a tool by rebinding its module attribute
and assert the double was awaited — which a direct call would satisfy just as
well. These go further: they wrap the shared gateway and assert the capability
was actually requested through it, and that the call is traced against the
node's own thread.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.agents.analyst import AnalystAgent
from backend.agents.base import BaseAgent
from backend.agents.content_strategist import ContentStrategistAgent
from backend.agents.copywriter import CopywriterAgent
from backend.config.models import TaskType
from backend.services.ripple_service import RippleTimeoutError
from backend.tools.runtime import shared_gateway

_TOPIC_SCORER = "backend.tools.analysis.topic_scorer.topic_scorer"
_GET_REPORT = "backend.tools.ripple.integration.get_report"
_SHARED_GATEWAY = "backend.tools.runtime.bridge.shared_gateway"


class _Recorder:
    """A gateway that records the capabilities asked of it, then delegates."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self._gateway = shared_gateway()

    async def invoke(self, capability: str, payload: Any = None, **kwargs: Any) -> Any:
        self.calls.append(capability)
        return await self._gateway.invoke(capability, payload, **kwargs)

    def shared(self) -> "_Recorder":
        return self


class TestToolTracing:
    @pytest.mark.asyncio
    async def test_a_nodes_tool_call_is_stored_against_its_thread(self):
        class ToolAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "tool_agent"
            prompt_file = ""

            async def execute(self, state: Any, store: Any) -> dict[str, Any]:
                result = await self.tools.invoke(
                    "content.algorithmic_de_ai", {"selected_title": "震惊！这个方法绝了"}
                )
                return {"tool_ok": result.ok}

        captured: list[tuple[str, list[dict[str, Any]]]] = []

        async def fake_emit(thread_id: str, entries: list[dict[str, Any]], /) -> int:
            captured.append((thread_id, list(entries)))
            return len(entries)

        with patch("backend.state.events.emit_events", fake_emit):
            update = await ToolAgent()({"thread_id": "t-1"}, store=AsyncMock())

        tool_events = [
            (thread_id, entry)
            for thread_id, entries in captured
            for entry in entries
            if entry.get("kind") == "tool"
        ]
        assert len(tool_events) == 1
        thread_id, event = tool_events[0]
        assert thread_id == "t-1"
        assert event["capability"] == "content.algorithmic_de_ai"
        assert event["ok"] is True
        assert event["thread_id"] == "t-1"
        assert update["tool_ok"] is True

    @pytest.mark.asyncio
    async def test_a_bare_execute_call_has_nowhere_to_trace_to(self):
        """Calling execute() directly (as many tests do) stays legal."""

        class ToolAgent(BaseAgent):
            task_type = TaskType.WRITING
            agent_name = "tool_agent"
            prompt_file = ""

            async def execute(self, state: Any, store: Any) -> dict[str, Any]:
                result = await self.tools.invoke(
                    "content.algorithmic_de_ai", {"selected_title": "震惊！绝了"}
                )
                return {"tool_ok": result.ok}

        update = await ToolAgent().execute({}, store=AsyncMock())
        assert update["tool_ok"] is True


class TestMigrationsGoThroughTheGateway:
    @pytest.mark.asyncio
    async def test_strategist_scores_topics_through_the_gateway(self):
        agent = ContentStrategistAgent()
        recorder = _Recorder()
        scorer = AsyncMock()
        scorer.ainvoke = AsyncMock(return_value={"heat_score": 82, "growth_trend": "爆发期"})

        with (
            patch(_TOPIC_SCORER, scorer),
            patch(_SHARED_GATEWAY, recorder.shared),
        ):
            context = await agent._score_trend_topics({"hot_topics": [{"topic": "探店"}]}, "美食")

        assert recorder.calls == ["analysis.topic_scorer"]
        assert "话题热度评分" in context
        assert "82" in context

    @pytest.mark.asyncio
    async def test_copywriter_scrubs_variants_through_the_gateway(self):
        agent = CopywriterAgent()
        recorder = _Recorder()

        with patch(_SHARED_GATEWAY, recorder.shared):
            variants = await agent._algorithmic_de_ai_variants(
                [
                    {
                        "title": "震惊！这个方法绝了",
                        "body": "总之就是非常好用",
                        "cta": "",
                        "tone": "真诚",
                    }
                ]
            )

        assert recorder.calls == ["content.algorithmic_de_ai"]
        assert len(variants) == 1
        assert variants[0]["tone"] == "真诚"
        assert isinstance(variants[0]["title"], str)

    @pytest.mark.asyncio
    async def test_no_variants_means_no_tool_call(self):
        """Cost control that existed before the migration must survive it."""
        agent = CopywriterAgent()
        recorder = _Recorder()

        with patch(_SHARED_GATEWAY, recorder.shared):
            assert await agent._algorithmic_de_ai_variants([]) == []

        assert recorder.calls == []

    @pytest.mark.asyncio
    async def test_analyst_fetches_the_report_through_the_gateway(self):
        """S3c: the wait budget moved onto the capability, so the call site no
        longer wraps the call in its own ``asyncio.wait_for`` — the invocation
        itself must now be visible to the runtime."""
        agent = AnalystAgent()
        recorder = _Recorder()
        report = AsyncMock(return_value={"rounds": [{"content": "Report text"}]})

        with (
            patch(_GET_REPORT, report),
            patch(_SHARED_GATEWAY, recorder.shared),
        ):
            text = await agent._ripple_report(
                {"content_plan": {"ripple_prediction": {"ripple_job_id": "job_1"}}}
            )

        assert recorder.calls == ["ripple.get_report"]
        assert text == "Report text"

    @pytest.mark.asyncio
    async def test_analyst_without_a_job_id_never_reaches_the_gateway(self):
        agent = AnalystAgent()
        recorder = _Recorder()

        with patch(_SHARED_GATEWAY, recorder.shared):
            assert await agent._ripple_report({"content_plan": {}}) is None

        assert recorder.calls == []


def _ripple_service(**overrides: Any) -> MagicMock:
    """A healthy ``RippleService`` double."""
    service = MagicMock()
    service.is_healthy.return_value = True
    service.health_check = AsyncMock()
    for name, value in overrides.items():
        setattr(service, name, value)
    return service


class TestRippleMigratedToTheGateway:
    """S3c-2: the two remaining Ripple capabilities, end to end.

    These deliberately let the *real* ``integration`` layer run: the whole
    point of this slice is the translation it performs (a service timeout into
    a domain outcome carrying the ``job_id``, a degraded service into a stated
    fact). Doubling ``integration`` would test a shape the agent never sees.
    """

    @pytest.mark.asyncio
    async def test_the_simulation_and_its_pmf_go_through_the_gateway(self):
        agent = ContentStrategistAgent()
        recorder = _Recorder()
        service = _ripple_service(
            predict_spread=AsyncMock(
                return_value={
                    "ripple_job_id": "job-9",
                    "ripple_prediction": {"viral_probability": 0.4},
                }
            ),
            validate_pmf=AsyncMock(return_value={"ripple_pmf": {"pmf_score": 0.6}}),
        )

        with (
            patch("backend.tools.ripple.integration.RippleService") as mock_cls,
            patch(_SHARED_GATEWAY, recorder.shared),
        ):
            mock_cls.get_instance.return_value = service
            plan = {"selected_topic": "美食探店", "content_angle": "探店攻略"}
            prediction = await agent._ripple_predict(plan, max_wait=60.0, thread_id="t-1")
            pmf = await agent._ripple_validate_pmf(plan, max_wait=60.0, thread_id="t-1")

        assert recorder.calls == ["ripple.predict_spread", "ripple.validate_pmf"]
        assert prediction.ok is True
        assert prediction.data["ripple_job_id"] == "job-9"
        assert prediction.data["viral_probability"] == 0.4
        assert pmf.data == {"pmf_score": 0.6}

    @pytest.mark.asyncio
    async def test_a_running_simulation_keeps_its_job_id(self):
        """A job that is still running is not a success, and its id must
        survive the trip through the Gateway — that id is the whole reason
        this answer is carried as data instead of as an exception."""
        agent = ContentStrategistAgent()
        recorder = _Recorder()
        service = _ripple_service(
            predict_spread=AsyncMock(side_effect=RippleTimeoutError("job-late", 900.0))
        )

        with (
            patch("backend.tools.ripple.integration.RippleService") as mock_cls,
            patch(_SHARED_GATEWAY, recorder.shared),
        ):
            mock_cls.get_instance.return_value = service
            call = await agent._ripple_predict(
                {"selected_topic": "美食探店"}, max_wait=900.0, thread_id="t-1"
            )

        assert recorder.calls == ["ripple.predict_spread"]
        assert call.ok is False
        assert call.reason == "timeout"
        assert call.job_id == "job-late"

    @pytest.mark.asyncio
    async def test_a_degraded_service_is_not_a_prediction(self):
        """``RippleService`` degrades by returning a zeroed prediction body.

        Read as a value, those zeros were stored as the workflow's forecast —
        the test double's ``{"ripple_fallback": True}`` hid that, because it
        carries no body at all. Through the Gateway the degradation is a fact
        the caller branches on.
        """
        agent = ContentStrategistAgent()
        recorder = _Recorder()
        service = _ripple_service(
            predict_spread=AsyncMock(
                return_value={
                    "ripple_prediction": {"viral_probability": 0.0, "estimated_reach": 0},
                    "ripple_fallback": True,
                    "ripple_reason": "unreachable",
                }
            )
        )

        with (
            patch("backend.tools.ripple.integration.RippleService") as mock_cls,
            patch(_SHARED_GATEWAY, recorder.shared),
        ):
            mock_cls.get_instance.return_value = service
            call = await agent._ripple_predict({"selected_topic": "美食探店"}, thread_id="t-1")

        assert recorder.calls == ["ripple.predict_spread"]
        assert call.ok is False
        assert call.reason == "unavailable"
        assert call.job_id == ""
