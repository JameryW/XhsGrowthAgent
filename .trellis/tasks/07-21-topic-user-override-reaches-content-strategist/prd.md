# Topic user-override reaches content strategist

## Problem

用户传入的 `topic`（`/workflow/start` 的 topic 参数）从存进 `initial_state["topic"]` 后就成了死数据——没有任何 agent 读它，且双重防漂移机制主动把 LLM 拉离用户主题。

证据链（2026-07-21 核实）：
1. 前端 `frontend/src/stores/workflow.ts:743` 正常传 topic 给 `/workflow/start`。
2. 后端 `backend/api/routes/workflow.py` 正常接收并存 `initial_state["topic"]`；`backend/state/schema.py:165` 声明 `topic: str`。
3. 全后端 grep `state.get("topic")` / `state["topic"]` 在 workflow-state 读取上零命中（命中均在 trend topic dict / showcase，无关）。
4. `content_strategist.py:83-86` 的 user_msg 只含 trend_data/account_id/niche/memory_context，无 topic。
5. 双重纠偏挡门：(a) `content_strategist.yaml` 硬约束「selected_topic 必须从趋势候选话题选取，不得自创/改写」；(b) `content_strategist.py:102-120` 代码纠偏——selected_topic 不在候选集则带 hint 重生成强制拉回。
6. 上游 `trend_scout.py:33,42` 只用 niche 作关键词种子拉趋势，不看 topic。

## Fix（最小改动 3 处）

### 1. `backend/agents/content_strategist.py`
- `execute()` 开头读 `user_topic = (state.get("topic") or "").strip()`。
- user_msg 注入 `用户指定主题：{user_topic}`（空则不注入）。
- **当 user_topic 非空时跳过候选集纠偏**（102-120 的 if 条件加 `not user_topic`）——用户主题作为 selected_topic 核心，趋势仅作角度/热点参考。
- 同时把 user_topic 透传给 system prompt 分支（通过 extra_context 或 prompt placeholder）。

### 2. `backend/config/prompts/content_strategist.yaml`
- system prompt 增加用户主题分支：有 user_topic 时以其为选题核心、必须围绕它；硬约束（从候选集选取）只在无 user_topic 时生效。

### 3. `backend/agents/trend_scout.py:42`
- 关键词种子 `keywords = [niche]` 改为纳入 `state["topic"]`：`user_topic` 非空时前置加入 keywords，让趋势/关键词监控围绕用户主题展开。

## Scope (non-goals)

- 不改下游 copywriter/visual_designer（已基于 selected_topic 工作）。
- 不改 niche_resolver 默认值逻辑（次要因素，单独议题）。
- 不改前端。
- topic 为空时行为完全不变（向后兼容）。

## Acceptance

- 传 topic → selected_topic 围绕该主题，不被候选集纠偏拉回。
- 不传 topic → 行为与现状一致（从趋势候选集选）。
- trend_scout 在有 topic 时把 topic 纳入关键词种子。
- 测试：content_strategist 有/无 topic 两 case（selected_topic 来源 + 纠偏跳过）；trend_scout keywords 含 topic。
- ruff/mypy clean + 全量 pytest 绿。

## PR

单 PR（同一链路、3 文件紧耦合）。从 main 新建分支。
