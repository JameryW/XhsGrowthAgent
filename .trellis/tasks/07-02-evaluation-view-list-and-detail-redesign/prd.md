# 质量评估页改造：列表 → 详情，支持搜索

## Goal
单独的质量评估页（EvaluationView.vue）改造：打开先展示工作流列表（带搜索），点击某条进详细评估报告。当前是输入 thread_id 查询，体验差。

## What I already know
- EvaluationView.vue 现状：search bar（input thread_id）→ search → 展示评估结果（总分/雷达图/维度/bias/revision_hints）+ 评估历史趋势
- `GET /api/workflow/list?account_id=&status=&limit=&offset=` 返回 WorkflowRow（thread_id/account_id/status/phase/label/workflow_mode/updated_at），**不含标题**
- 标题在 state.copy_content.selected_title，需 `GET /api/workflow/status/{thread_id}` 或 `/api/review/pending/{thread_id}` 取
- `GET /api/evaluation/result/{thread_id}` 读评估结果
- `GET /api/evaluation/trend` 趋势（已有，保留）
- review 页的 queue 列表是按 status=awaiting_review 过滤的工作流列表 + 详情

## Decisions (已确认)
1. **详情展示**：路由跳转 `/evaluation/:thread_id` 独立页（URL 可分享/收藏，浏览器后退友好，详情页有返回按钮）
2. **列表标题**：后端 GET /api/workflow/list 扩返回 copy_content.selected_title（从 checkpoint 读 state）
3. **搜索**：前端过滤（标题 + thread_id + account_id）
4. **列表范围**：仅有评估结果的工作流（后端 list 过滤 has_evaluation，或前端取 evaluation_result 过滤）

## Requirements
- EvaluationView 改造为列表页：打开展示工作流列表（标题/phase/status/account_id/updated_at/总分预览）
- 列表仅含有评估结果的工作流
- 列表支持搜索（前端过滤标题+ID+账号）
- 点击某条 → 路由跳转 `/evaluation/:thread_id` → 详情页展示完整评估报告
- 详情页有返回按钮回列表
- 保留评估历史趋势（列表页顶部保留，或详情页保留）
- 后端 GET /api/workflow/list 扩返回 selected_title + overall_score（评估预览）+ 过滤有评估结果

## Acceptance Criteria
- [ ] 打开 /evaluation 直接见工作流列表（有评估结果的）
- [ ] 列表展示标题帮识别
- [ ] 搜索框前端过滤（标题/ID/账号）
- [ ] 点击跳转 /evaluation/:thread_id 详情页
- [ ] 详情页展示完整评估报告（复用现有组件）
- [ ] 详情页返回按钮回列表
- [ ] 趋势图保留

## Out of Scope
- 不改评估 agent / 评估结果数据结构
- 不改 EvaluationRadar 等组件
- 不改 review 页（已独立 PR）

## Technical Approach
### 后端
- GET /api/workflow/list 扩返回：selected_title（从 checkpoint state.copy_content）+ evaluation_result 摘要（overall_score/decision）+ has_evaluation 过滤
- 性能：list 从 DB 查 workflows 表，需批量读 checkpoint 取 title/evaluation——评估批量读成本，必要时限制 limit 或加 has_evaluation 列到 workflows 表
- 或：新增 GET /api/evaluation/list 专用端点（只返回有评估结果的，含标题+总分），避免污染通用 list

### 前端
- 路由：/evaluation（列表）+ /evaluation/:thread_id（详情）
- 列表页：搜索框 + 列表 + 趋势图
- 详情页：现有评估结果展示（overview/radar/bias/dims/hints）+ 返回按钮
- 复用 EvaluationRadar/TrendChart

## Implementation Plan
- PR1：后端 list 扩返回标题+评估摘要（或新 evaluation/list 端点）+ 测试
- PR2：前端 EvaluationView 拆列表页+详情页 + 搜索 + 路由
