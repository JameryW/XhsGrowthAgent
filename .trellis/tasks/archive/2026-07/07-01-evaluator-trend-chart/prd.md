# Evaluator Trend Chart

## Goal

前端加评估历史趋势图：多 thread 的 overall_score 时序 + 各维度均值趋势，让评估闭环有纵向视角。

## What I already know

- 前端已有 TrendChart.vue + EvaluationRadar.vue
- /evaluation 页当前只查单 thread
- 后端 evaluator_samples 表有 thread_id + overall_score + dimensions + created_at

## Requirements

- 后端聚合端点：GET /evaluation/trend?account_id=X&limit=N → 时序样本（created_at, overall_score, decision, 各维度分）
- 前端 /evaluation 页加"趋势"tab/区：overall_score 时序折线 + 各维度均值
- 复用 TrendChart 模式（vue-echarts line）
- 空数据空状态
- 响应式

## Acceptance Criteria

- [ ] GET /evaluation/trend 返回时序数据
- [ ] 前端趋势折线图渲染
- [ ] 空数据空状态
- [ ] mobile 可用
- [ ] build + type-check 绿
- [ ] 后端单测覆盖 trend 端点

## Definition of Done

- 端点 + 前端趋势图
- build/type-check/lint 绿

## Out of Scope

- 跨账号对比
- 实时流式趋势

## Technical Notes

- 端点：backend/api/routes/evaluation.py 加 /trend
- 前端：EvaluationView.vue 加趋势区 + 复用 TrendChart 或新 LineChart
- 数据：evaluator_samples 已有时序字段
