# 评估删除 vestigial ToolRegistry

## 背景
trellis-check 发现 `backend/tools/registry.py` 的 `ToolRegistry` 整体 vestigial：
- `register_all_tools()` 零生产调用方（仅 `tests/unit/tools/test_llm_tools.py` 用）
- agents 不走 registry 取工具——`get_tools_for_agent` 在 backend/agents/ 零调用
- `_agent_tools` dict 零引用
- `get_tools_for_agent` 静默丢弃 `_agent_tools` 中永不注册的名字
- `backend/agents/base.py` 无 tool binding 逻辑

agents 实际通过直接 submodule import 取工具（如 `content_strategist.py:483 from backend.tools.analysis.topic_scorer import topic_scorer`）。

## 需求
1. 调研确认 ToolRegistry 全链路零生产依赖（agents / graph / api / services 均不调 registry 取工具）
2. 确认 `_agent_tools` 映射是否纯文档性（列出 agent 该有哪些 tool，但实际从未被消费）
3. 评估删除影响：
   - 删 `backend/tools/registry.py`
   - 删 `backend/tools/__init__.py` 的 `ToolRegistry` lazy 导出 + `__all__`
   - 删 `tests/unit/tools/test_llm_tools.py`（仅测 registry）
   - `_agent_tools` 是否删（若纯文档，移到 CLAUDE.md 或删）
4. 验证：2050 测试 - test_llm_tools 后全绿，ruff/mypy 绿

## 待定（research 回答）
- `_agent_tools` 是否被任何动态逻辑读取？
- ToolRegistry 是否被 omp / 外部插件引用？
- 删后 agent 工具发现机制是否需补文档？

## 非目标
- 不改 agents 取工具方式（直接 import 是对的，保持）
- 不实现 registry 替代（YAGNI，无人用）
