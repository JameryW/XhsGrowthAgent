# 单篇历史笔记详情与质量评估

## Goal

让用户从已导入的历史笔记中打开单篇内容，查看持久化的正文、标题、封面、发布时间、互动指标和可用的观众明细，并基于同一套历史质量分析能力得到该篇笔记的透明质量信号。该流程只读取本地已导入数据，不重新打开浏览器、不触发同步，也不改变现有工作流级 RQGM 评估。

## What I already know

* `creator_note_stats` 已持久化 `body_text`、标题、封面、标签、互动指标、观看来源、观众画像、趋势和安全化 `detail_metrics`。
* `backend.db.creator_stats.get_note_stats(account_id, note_id)` 已支持按账号和笔记 ID读取单篇数据，但尚未由 API 暴露。
* `GET /api/analytics/creator-stats/{account_id}` 只返回有数量上限的列表；`GET .../{account_id}/quality` 只生成账户级历史报告。
* `backend.services.creator_stats.quality` 是纯函数、无 I/O 的确定性质量分析器，当前复用四个维度：互动、收藏价值、标题表达、表现稳定性。
* 前端 `CreatorQualityWorkspace` / `CreatorQualityPanel` 已提供账户选择和账户级质量报告；历史笔记表目前只在 `CreatorStatsPanel` 展示摘要行，不能打开详情或评分。
* API 使用统一 `success(...)` 响应和 `ValidationError` / `WorkflowNotFoundError` 风格；前端 API 类型和中英文 locale 均集中维护。

## Requirements

* 新增单篇历史笔记详情 API，按 `account_id + note_id` 精确读取，返回完整安全化笔记 DTO，并区分不存在与空字段。
* 新增单篇历史笔记质量分析 API，使用现有质量分析器的相同维度、阈值和文案语言；评分必须明确哪些维度因单篇样本不可用，不能把缺少历史对照误报成账户整体结论。
* 详情/评分接口必须只读持久化数据，不启动 CDP、不调用同步服务、不写数据库或 Creative Memory。
* 质量结果至少包含 `note_id`、评分范围/置信度、可用维度、指标证据、摘要和可执行建议，并保留与该笔记相关的 ID。
* 质量页提供历史笔记列表和单篇详情入口；详情展示正文（若已导入）、标签、封面、发布时间、互动指标、来源/画像/趋势等可用字段及单篇质量结果。
* 前端处理中英文文案、加载、空数据、找不到笔记和请求失败状态；移动端不产生页面级横向溢出。
* 保持账户级历史质量、Creator Center 导入、工作流级 RQGM 评估和现有 API 契约兼容。

## Acceptance Criteria

* [ ] 已导入笔记可通过单篇 API 获取完整安全化详情；错误账号或笔记 ID返回明确 404/错误响应。
* [ ] 单篇质量结果由既有 `quality.py` 计算路径派生，至少覆盖互动、收藏价值和标题表达；稳定性等需要跨笔记样本的维度被标记不可用而不是伪造分数。
* [ ] 单篇接口和评分接口均通过测试证明不会同步、写库或修改输入数据。
* [ ] 质量页可选择历史笔记并展开详情与质量结果，空数据和失败状态可理解且中英文齐全。
* [ ] 后端单元/API测试、前端组件测试、Ruff、Mypy、前端 type-check/build 通过。

## Definition of Done

* Tests added/updated for DTO、分析器、API、前端交互和只读约束。
* 代码质量检查与构建通过。
* 任务上下文和相关 spec 在实现前已配置；完成后补充可复用的规范说明。

## Technical Approach

1. 在 `quality.py` 抽取可复用的“给定样本生成维度/证据”路径，新增单篇报告 DTO；单篇报告复用既有归一化和阈值，只对可由一篇笔记证明的维度给分，跨样本稳定性返回 `available=false`。
2. 在 analytics 路由新增 `/creator-stats/{account_id}/notes/{note_id}`（详情）和 `/creator-stats/{account_id}/notes/{note_id}/quality`（单篇质量），统一返回 `success(data=...)`，使用现有 `get_note_stats`。
3. 前端增加单篇 API 类型与 `CreatorNoteQualityPanel`（列表、选择、详情、指标和质量卡片），由 `CreatorQualityWorkspace` 挂载并复用账户选择；不改变工作流评估视图。

## Decision (ADR-lite)

**Context**: 历史笔记已经持久化足够的内容/指标，但产品只有账户级报告；工作流 RQGM 依赖 workflow state，不能直接用于历史导入笔记。

**Decision**: 采用本地确定性单篇分析，复用历史质量分析器的归一化、维度计算和证据格式；不新增 LLM 评估调用。详情和质量分离为两个 GET 端点，同时前端把它们组合成一个用户操作。

**Consequences**: 结果可重复、成本低、不会泄露登录态；单篇报告只能评价导入的互动/收藏/标题信号，视觉和完整正文缺失时必须显式降级。未来若引入跨笔记百分位比较，可在单篇响应增加可选历史上下文而不改变基础 DTO。

## Out of Scope

* 不替换或修改现有工作流级 RQGM `POST /api/evaluation/run/{thread_id}`。
* 不为缺少正文/图片的历史行重新发起 Creator Center 浏览器抓取。
* 不引入新的模型、外部质量基准或写入 Creative Memory 的副作用。

## Technical Notes

* Relevant code: `backend/db/creator_stats.py`, `backend/services/creator_stats/types.py`, `backend/services/creator_stats/quality.py`, `backend/api/routes/analytics.py`, `frontend/src/api/analytics.ts`, `frontend/src/components/evaluation/CreatorQualityWorkspace.vue`, `frontend/src/components/settings/CreatorQualityPanel.vue`.
* Existing account-level quality contract and rationale: `.trellis/tasks/07-13-historical-note-quality-analysis/prd.md`.
* Existing backend/frontend specs: `.trellis/spec/backend/index.md`, `.trellis/spec/backend/quality-guidelines.md`, `.trellis/spec/frontend/component-patterns.md`, `.trellis/spec/frontend/state-management.md`.
