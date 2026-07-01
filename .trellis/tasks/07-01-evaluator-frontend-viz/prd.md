# Evaluator Frontend Viz Page

## Goal

为 RQGM agent-as-a-judge 评估结果新增前端可视化页：6 维雷达图 + overall/decision/bias/revision_hints 展示，让评估闭环对用户可见可交互。

## Requirements

- 新增 `EvaluationView.vue` 视图 + `/evaluation` 路由（懒加载，需 auth）
- 页面交互：输入 thread_id → 调 `GET /evaluation/result/{thread_id}` → 展示
- 展示要素：
  - 总分 `overall_score`（大号数字 + 颜色编码：≥70 绿 / 50-70 橙 / <50 红）
  - 决策 `decision`（approved/needs_revision/rejected 徽章）
  - 6 维雷达图（echarts radar，含 bias_check）
  - 各维度详情：score / rationale / issues / is_blocking 标记
  - `bias_warning`（如有，醒目告警块）
  - `revision_hints` 列表（如有）
  - 无评估时（has_evaluation=false）空状态提示
- 导航入口：Navbar 加 "评估" 链接
- i18n：中英双语 key

## Acceptance Criteria

- [ ] `/evaluation` 路由可访问，需登录
- [ ] 输入有效 thread_id 能拉到评估结果并渲染雷达图
- [ ] has_evaluation=false 时显示空状态，不报错
- [ ] decision 三态颜色/文案正确
- [ ] bias_warning 存在时醒目展示
- [ ] mobile 端可用（响应式）
- [ ] `npm run build` 通过
- [ ] lint 通过

## Definition of Done

- 视图 + 路由 + Navbar 入口 + i18n key
- build/lint 绿
- 后端 API 无改动（复用现有 `/evaluation/result/{thread_id}`）

## Technical Approach

- 复用 `vue-echarts`（已装）画 radar，参照 `components/charts/` 现有组件模式
- 新增 `api/evaluation.ts` 封装 GET 调用
- 复用 `EvaluationResult`/`DimensionScore` 类型（参照 omp ext 的 ts 接口，迁到 `types/evaluation.ts` 共享）
- 雷达 6 维：copywriting/visual/compliance/reach/audience/bias_check
- 颜色编码用现有设计 token（参照 Review.vue 的 ContentStatus 处理）

## Out of Scope

- 评估结果历史趋势图（需多 thread 聚合，后续 epoch）
- 手动触发评估（omp 已有 `xhs_evaluation_run` 工具，前端不重复）
- 权重可视化（属 learnable-weights 子任务）

## Technical Notes

- API: `GET /evaluation/result/{thread_id}` → `EvaluationResultResponse`
- 现有图表组件目录：`frontend/src/components/charts/`
- 路由懒加载模式：`component: () => import('@/views/X.vue')`
- ts 接口参考：`backend/omp/extensions/xhsagent-ext/src/tools/evaluation_result.ts`
