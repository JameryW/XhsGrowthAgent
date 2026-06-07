# 热门博主爆款笔记参考功能

## Goal

在 trend 模式和 brief 模式中，增加"按赛道关键词搜索 → 找到该赛道热门笔记 → 反查博主 → 获取博主 top 笔记 → 人工选择参考博主"的链路，让创作环节能参考热门博主的爆款笔记，提升内容质量。人工参与选型是核心需求——不是自动选取，而是让用户从候选博主中挑选。

## What I already know

* 两种模式：`WorkflowMode.TREND`（趋势发现）和 `WorkflowMode.BRIEF`（商单 Brief）
* 两种模式都经过 `viral_matcher` 节点（搜索爆款参考）
* 现有 `ViralMatcherAgent` 仅基于关键词搜索爆款笔记，不涉及博主维度
* XHS API 已有 `SEARCH_USER`、`USER_INFO`、`USER_NOTES` 端点，但 `_HTTPClient` / `XHSClient` 未封装
* `ViralPost` 状态模型缺少博主信息字段
* `compile_graph_dev/prod` 已有 `interrupt_before` 机制（review_gate, choice_gate, draft_gate, brief_gate, ripple_gate）
* `XHSClient.search_notes(keyword)` 和 `_HTTPClient.search_notes(keyword)` 已可用

## Requirements

* 在 `_HTTPClient` 和 `XHSClient` 中新增 `search_users(keyword)`、`get_user_info(user_id)`、`get_user_notes(user_id, cursor, limit)` 方法
* 新增 `BloggerProfile`（博主信息）和 `BloggerNote`（博主笔记）TypedDict 状态模型
* 新增 `blogger_scout` Agent + 节点：从赛道热门笔记提取博主，按笔记互动总量排序，取 top N 候选
* 新增 `blogger_gate` 节点（interrupt）：暂停等用户从候选博主中选择
* 用户选型后，获取选中博主的 top N 笔记（按互动数据排序），注入 state 供后续创作参考
* 候选数量可配置（state 字段 `blogger_candidate_limit`，默认 5）
* 笔记获取深度可配置（state 字段 `blogger_note_limit`，默认 20）
* trend 模式和 brief 模式均支持
* Graph 拓扑：viral_matcher → blogger_scout → blogger_gate(中断) → 获取选中博主笔记 → 后续节点

## Decision (ADR-lite)

**Context**: 博主搜索链路在 graph 中的位置和交互粒度
**Decision**:
1. 在 viral_matcher 之后插入独立节点（blogger_scout + blogger_gate），而非扩展 viral_matcher 内部
2. 人工选型粒度为"选博主"——用户选博主后，系统自动按互动数据取 top N 笔记
3. 笔记获取深度可配置，默认 20
4. 候选博主数量可配置，默认 5，按笔记互动总量排序
**Consequences**: graph 多 2 个节点，但职责清晰；interrupt_before 需新增 blogger_gate；博主维度参考更宏观

## Acceptance Criteria

* [ ] `_HTTPClient` 新增 `search_users`、`get_user_info`、`get_user_notes` 方法
* [ ] `XHSClient` 封装对应高级方法
* [ ] `BloggerProfile` 和 `BloggerNote` TypedDict 定义
* [ ] `blogger_scout` 节点：搜索赛道笔记 → 提取博主 → 按互动排序 → 取 top N 候选
* [ ] `blogger_gate` 节点：interrupt 暂停，用户选择博主后 resume
* [ ] 选型后获取选中博主 top 笔记并写入 state
* [ ] trend 模式链路：draft_gate → viral_matcher → blogger_scout → blogger_gate → content_analyzer
* [ ] brief 模式链路：brief_gate → viral_matcher → blogger_scout → blogger_gate → shooting_planner/content_analyzer
* [ ] `blogger_candidate_limit` 和 `blogger_note_limit` 可配置
* [ ] 新增方法有单元测试
* [ ] Lint / typecheck 通过

## Definition of Done

* Tests added/updated (unit/integration where appropriate)
* Lint / typecheck / CI green
* Docs/notes updated if behavior changes
* Rollout/rollback considered if risky

## Out of Scope (explicit)

* 博主粉丝互动/社交关系分析
* 博主历史数据趋势追踪
* 自动选型（无人工参与的纯自动模式）
* 多博主对比评分排序

## Technical Approach

### 新增文件
* `backend/agents/blogger_scout.py` — BloggerScoutAgent
* `backend/agents/nodes/blogger_scout.py` — blogger_scout_node
* `backend/agents/nodes/blogger_gate.py` — blogger_gate_node
* `backend/config/prompts/blogger_scout.yaml` — prompt
* `tests/unit/services/test_xhs_client_blogger.py` — 客户端方法测试
* `tests/unit/agents/test_blogger_scout.py` — Agent 测试

### 修改文件
* `backend/services/xhs_api.py` — 新增 API params（search_users, user_info, user_notes）
* `backend/services/xhs_client.py` — 新增 `_HTTPClient` 和 `XHSClient` 方法
* `backend/state/substates.py` — 新增 BloggerProfile, BloggerNote
* `backend/state/schema.py` — 新增 blogger_candidates, selected_blogger, blogger_notes, blogger_candidate_limit, blogger_note_limit 字段
* `backend/graph/builder.py` — 新增 blogger_scout, blogger_gate 节点和边
* `backend/graph/routers.py` — 新增路由逻辑
* `backend/agents/nodes/__init__.py` — 导出新节点
* `backend/agents/nodes/optimization/__init__.py` — 导出
* `backend/tools/registry.py` — 注册 blogger 相关工具（如需要）

### Graph 拓扑变更
```
# trend 模式
draft_gate → viral_matcher → blogger_scout → blogger_gate(interrupt)
    → content_analyzer (or visual_designer if skip)

# brief 模式
brief_gate → viral_matcher → blogger_scout → blogger_gate(interrupt)
    → shooting_planner / content_analyzer (按 should_brief_or_optimize 路由)
```

## Technical Notes

* 关键文件：
  * `backend/services/xhs_api.py` — API 端点定义（已有 SEARCH_USER, USER_INFO, USER_NOTES）
  * `backend/services/xhs_client.py` — 客户端封装（需新增方法）
  * `backend/agents/viral_matcher.py` — 现有爆款匹配 Agent
  * `backend/agents/nodes/optimization/viral_matcher.py` — 现有节点
  * `backend/graph/builder.py` — Graph 拓扑
  * `backend/state/substates.py` — ViralPost 状态模型
  * `backend/state/schema.py` — XHSGrowthState 主状态
  * `backend/tools/registry.py` — 工具注册表
  * `backend/agents/nodes/choice_gate.py` — 参考实现（interrupt gate 模式）
