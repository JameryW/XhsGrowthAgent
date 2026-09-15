"""The L1 tool-schema layer's agent-side declaration (P1c-S4).

Two contracts live here:

* which capabilities each agent declares — pinned exactly, because a silent
  edit to this tuple changes what a P2c prompt would say about the system;
* that the layer is **off**, everywhere, until P2c opens a tool-calling
  channel. A flag without a test becomes true the first time someone flips it
  to debug something and forgets.
"""

from __future__ import annotations

from backend.agents.analyst import AnalystAgent
from backend.agents.base import BaseAgent
from backend.agents.content_strategist import ContentStrategistAgent
from backend.agents.copywriter import CopywriterAgent
from backend.agents.trend_scout import TrendScoutAgent
from backend.tools.runtime.catalog import build_registry

_DECLARED: tuple[tuple[type[BaseAgent], tuple[str, ...]], ...] = (
    (TrendScoutAgent, ("xhs.trending", "xhs.keyword_monitor", "xhs.competitor_analyzer")),
    (
        ContentStrategistAgent,
        ("analysis.topic_scorer", "ripple.predict_spread", "ripple.validate_pmf"),
    ),
    (CopywriterAgent, ("content.algorithmic_de_ai", "content.polish_copy")),
    (AnalystAgent, ("ripple.get_report",)),
)


def test_each_agent_declares_exactly_the_capabilities_it_uses() -> None:
    for agent_class, expected in _DECLARED:
        assert set(agent_class.tool_capabilities) == set(expected), agent_class.agent_name


def test_every_declared_capability_exists_in_the_catalogue() -> None:
    """``tool_schema_section`` is the only thing that would notice a typo, and
    it is off by default — so the declaration has to be checked on its own."""
    registered = set(build_registry().capabilities())
    for agent_class, _ in _DECLARED:
        missing = set(agent_class.tool_capabilities) - registered
        assert not missing, f"{agent_class.agent_name} declares unknown: {sorted(missing)}"


def test_declaring_a_capability_renders_nothing_by_default() -> None:
    """The declaration is documentation until the layer is switched on: an
    agent with capabilities and no flag contributes no L1 text at all."""
    for agent_class, _ in _DECLARED:
        assert agent_class().tool_schema_layer() == "", agent_class.agent_name


def test_the_layer_is_off_everywhere() -> None:
    """Pinned decision, not an oversight.

    The model cannot call a tool until P2c, so a prompt that lists capabilities
    describes an ability it cannot exercise — an invitation to put tool-call
    syntax into the JSON it is supposed to return — while spending tokens on
    every request. Turning this on is a deliberate per-agent act, and this test
    is what makes it deliberate.
    """
    assert BaseAgent.include_tool_schema is False
    for agent_class, _ in _DECLARED:
        assert agent_class.include_tool_schema is False, agent_class.agent_name


def test_switching_the_layer_on_renders_the_agents_own_capabilities() -> None:
    """And only its own: the layer narrows to the declaration rather than
    dumping the catalogue into every prompt."""
    agent = TrendScoutAgent()
    agent.include_tool_schema = True
    text = agent.tool_schema_layer()
    assert "- xhs.trending — " in text
    assert "- xhs.keyword_monitor — " in text
    assert "- xhs.competitor_analyzer — " in text
    assert "ripple.predict_spread" not in text


def test_an_agent_without_capabilities_renders_nothing_even_when_switched_on() -> None:
    """No declaration, no layer — enabling the flag on an agent that reaches no
    capabilities is a no-op rather than an empty header in the prompt."""
    agent = TrendScoutAgent()
    agent.include_tool_schema = True
    agent.tool_capabilities = ()
    assert agent.tool_schema_layer() == ""
