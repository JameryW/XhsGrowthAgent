"""Structured-output contract for the four writing agents (P1d-S3).

``copywriter`` / ``version_generator`` / ``visual_designer`` /
``shooting_planner`` share one failure mode and one disposition, which is why
they are tested together:

* ``_parse_json_response`` never failed. A model that answered prose produced
  ``{"raw_content": …}``, a perfectly legal dict against an all-defaults model,
  and the node stopped it into state and reported success. Downstream, the
  result was indistinguishable from "the model really did write nothing" — the
  empty copy, the visual plan naming no cover, the shooting plan with no draft.
* The three agents whose **main product** is that payload now carry a semantic
  validator and let the failure travel: ``_llm_structured`` retries once with
  the correction attached and then raises, and ``BaseAgent.__call__`` turns the
  raise into an error state for the stateful retry. That is the state this file
  pins, end to end through ``__call__`` rather than through ``execute``.
* ``version_generator``'s product is a *collection*, and an empty one is a shape
  the node already handles, so its validator is advisory
  (``accept_last_valid``): the old outcome — ``content_versions: []`` — has to
  stay reachable.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.agents.copywriter import CopywriterAgent
from backend.agents.shooting_planner import ShootingPlannerAgent
from backend.agents.version_generator import VersionGeneratorAgent
from backend.agents.visual_designer import VisualDesignerAgent
from backend.state.schema import WorkflowPhase

PROSE = "这次我就不输出 JSON 了，直接说一段话吧。"


def _store() -> AsyncMock:
    store = AsyncMock()
    store.asearch = AsyncMock(return_value=[])
    return store


def _patched_model(content: str):
    """A model stub that answers ``content`` every time it is asked.

    A real object with a real ``ainvoke``, not a ``MagicMock``: the agent's
    degradation chain reaches the provider's PROMPTED level (every writing task
    routes through the XUNFEI-compatible endpoint), and a mock that grows
    ``with_structured_output``/``bind`` on demand would silently take a level
    the production configuration never reaches.
    """
    response = MagicMock()
    response.content = content
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=response)
    return model


# ── 主产物缺失 → 抛 → error state（copywriter / visual_designer / shooting_planner） ──

_COPY_STATE = {
    "account_id": "test",
    "niche": "母婴",
    "content_plan": {"selected_topic": "美食探店"},
}
_VISUAL_STATE = {
    "account_id": "test",
    "niche": "母婴",
    "content_plan": {"selected_topic": "美食探店", "content_type": "note"},
    "copy_content": {"body_text": "正文"},
}


class TestProseIsRefusedEndToEnd:
    """``__call__`` turns the raise into an error state — not a success with an
    empty product, and not a crash."""

    @pytest.mark.asyncio
    async def test_copywriter_reports_error_instead_of_empty_copy(self):
        agent = CopywriterAgent()
        model = _patched_model(PROSE)
        with patch.object(type(agent), "model", new_callable=PropertyMock) as prop:
            prop.return_value = model
            result = await agent(_COPY_STATE, store=_store())

        assert result["phase"] == WorkflowPhase.ERROR
        assert "copy_content" not in result
        assert result["retry_count"] == 1, "the stateful retry needs the counter to move"
        assert result["error"]

    @pytest.mark.asyncio
    async def test_visual_designer_reports_error_instead_of_empty_plan(self):
        agent = VisualDesignerAgent()
        model = _patched_model(PROSE)
        with patch.object(type(agent), "model", new_callable=PropertyMock) as prop:
            prop.return_value = model
            result = await agent(_VISUAL_STATE, store=_store())

        assert result["phase"] == WorkflowPhase.ERROR
        assert "visual_plan" not in result

    @pytest.mark.asyncio
    async def test_shooting_planner_reports_error_instead_of_an_empty_template(self):
        """The collision this prevents is concrete: an empty *answer* and the
        early return (``{"shooting_plan": {}}``, "nothing to plan from") are the
        same dict, so an all-defaults payload would stop an empty template into
        state and overwrite the creator's."""
        agent = ShootingPlannerAgent()
        model = _patched_model(PROSE)
        with patch.object(type(agent), "model", new_callable=PropertyMock) as prop:
            prop.return_value = model
            result = await agent(_COPY_STATE, store=_store())

        assert result["phase"] == WorkflowPhase.ERROR
        assert "shooting_plan" not in result

    @pytest.mark.asyncio
    async def test_the_retry_carries_a_correction_not_a_repeat(self):
        """Both attempts happen; the second one is told what was wrong. The old
        hand-rolled retry re-sent the identical prompt, which is the difference
        between a retry and a second guess."""
        agent = VisualDesignerAgent()
        model = _patched_model(PROSE)
        with patch.object(type(agent), "model", new_callable=PropertyMock) as prop:
            prop.return_value = model
            await agent(_VISUAL_STATE, store=_store())

        assert model.ainvoke.call_count == 2
        retry_messages = model.ainvoke.await_args_list[-1].args[0]
        assert any("【纠偏】" in str(message) for message in retry_messages)


class TestVersionGeneratorEmptyAndSingle:
    """The collection product: an empty list stays reachable, a lone version is
    still auto-applied onto ``copy_content``/``visual_plan``."""

    @staticmethod
    def _state() -> dict:
        return {
            "account_id": "test",
            "niche": "母婴",
            "draft_content": {"title": "原标题", "text": "原正文"},
            "optimization_analysis": {"gaps": [], "suggestions": [], "viral_patterns": []},
        }

    @pytest.mark.asyncio
    async def test_an_unusable_answer_degrades_to_zero_versions(self):
        """``accept_last_valid`` is what keeps the pre-migration outcome: no
        versions, the key written with an empty list, the node reporting
        success. Raising here would turn "the model fumbled the format" into a
        workflow failure for a product that is *optional* — the main draft is
        already in state."""
        agent = VersionGeneratorAgent()
        model = _patched_model(PROSE)
        with patch.object(type(agent), "model", new_callable=PropertyMock) as prop:
            prop.return_value = model
            result = await agent.execute(self._state(), _store())

        assert result["content_versions"] == []
        assert result["phase"] == WorkflowPhase.CREATING
        assert model.ainvoke.call_count == 2, "still one attempt + one correction"

    @pytest.mark.asyncio
    async def test_a_payload_the_schema_refuses_also_degrades_to_zero_versions(self):
        """The *other* half of the fallback, and the reason both halves exist.

        Prose passes the schema (``{"raw_content": …}`` validates against an
        all-defaults model) and is stopped by the validator, which
        ``accept_last_valid`` turns into the last schema-valid instance. A bare
        array is refused by the object-only gate instead, so no instance is ever
        valid and ``_llm_structured`` raises — that path is what the agent's
        ``except`` handles. Without it, a model answering with a list would fail
        a workflow over an optional product.
        """
        agent = VersionGeneratorAgent()
        model = _patched_model('[{"version_id": "a", "title": "标题"}]')
        with patch.object(type(agent), "model", new_callable=PropertyMock) as prop:
            prop.return_value = model
            result = await agent.execute(self._state(), _store())

        assert result["content_versions"] == []
        assert result["phase"] == WorkflowPhase.CREATING
        assert model.ainvoke.call_count == 2, "a refused payload is still retried once"

    @pytest.mark.asyncio
    async def test_a_lone_version_is_still_applied_onto_copy_and_visual(self):
        """``len(versions) == 1`` auto-apply, unchanged: the version's title,
        body and palette become the drafts the next node edits."""
        agent = VersionGeneratorAgent()
        model = _patched_model(
            '{"versions": [{"version_id": "a", "title": "新标题", "body": "新正文",'
            ' "hashtags": ["#a"], "tone": "口语", "style_suggestion": "简洁封面",'
            ' "visual_style": "极简", "color_palette": {"primary": "#fff"}}]}'
        )
        with patch.object(type(agent), "model", new_callable=PropertyMock) as prop:
            prop.return_value = model
            result = await agent.execute(self._state(), _store())

        assert len(result["content_versions"]) == 1
        assert result["copy_content"]["selected_title"] == "新标题"
        assert result["copy_content"]["body_text"] == "新正文"
        assert result["visual_plan"]["cover_prompt"] == "简洁封面"
        assert result["visual_plan"]["color_palette"] == {"primary": "#fff"}
