"""S4-6 纯模板批迁移契约：content_analyzer / viral_matcher /
version_generator / shooting_planner。

四个 agent 均无管线 ns recall、system YAML 无占位符（任务数据全走
user_msg）——system 组装接 ContextCompiler.compile_prompt（无标记整段
L0），静态 policy 文本经 compile 后逐字保留（仅段边缘空白规范化）。
"""

import pytest

from backend.agents.content_analyzer import ContentAnalyzerAgent
from backend.agents.shooting_planner import ShootingPlannerAgent
from backend.agents.version_generator import VersionGeneratorAgent
from backend.agents.viral_matcher import ViralMatcherAgent

_CASES = [
    (ContentAnalyzerAgent, "content_analyzer", "content_analyzer.yaml"),
    (ViralMatcherAgent, "viral_matcher", "viral_matcher.yaml"),
    (VersionGeneratorAgent, "version_generator", "version_generator.yaml"),
    (ShootingPlannerAgent, "shooting_planner", "shooting_planner.yaml"),
]


class TestTemplateBatchContextPipeline:
    @pytest.mark.parametrize("agent_cls,agent_name,prompt_file", _CASES)
    def test_yaml_static_no_placeholders(self, agent_cls, agent_name, prompt_file):
        """YAML system 为纯静态 policy：无 {memory_context} 占位符、无分段
        标记（整段 L0）。"""
        agent = agent_cls()
        assert agent.agent_name == agent_name
        assert agent.prompt_file == prompt_file
        system = agent.prompt_template["system"]
        assert "{memory_context}" not in system
        assert "<!-- ctx:" not in system

    @pytest.mark.parametrize("agent_cls,agent_name,prompt_file", _CASES)
    def test_compile_system_prompt_preserves_policy(self, agent_cls, agent_name, prompt_file):
        """compile 路径渲染静态 policy 逐字保留（段边缘空白规范化除外），
        且不依赖 niche——本批 agent 不读 niche，RunContext 传 "" 不新造默认值。"""
        agent = agent_cls()
        system = agent.prompt_template["system"]
        prompt = agent._compile_system_prompt({"account_id": "acct", "session_id": "t1"})
        assert prompt.strip() == system.strip()

    @pytest.mark.parametrize("agent_cls,agent_name,prompt_file", _CASES)
    def test_compile_system_prompt_minimal_state(self, agent_cls, agent_name, prompt_file):
        """缺 session_id/niche 的 state 不崩溃（键全部缺省安全）。"""
        agent = agent_cls()
        prompt = agent._compile_system_prompt({})
        assert prompt.strip() == agent.prompt_template["system"].strip()
