"""工具模块 — LangChain 工具.

Components:
- ripple: Ripple CAS 模拟引擎工具
- xhs: 小红书平台工具
- content: 内容生成工具
- analysis: 分析工具
- scheduling: 调度工具

Agents obtain their tools via direct submodule imports (e.g.
``from backend.tools.analysis.topic_scorer import topic_scorer``) rather than
through a central registry — see CLAUDE.md "Adding a New Tool".
"""
