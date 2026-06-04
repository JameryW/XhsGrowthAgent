# optimize: analytics page data depth and interactivity

## Goal

增加数据分析页面的数据深度和交互能力：模型成本可视化、最佳帖子高亮、Views 展示、趋势图空态、表格排序。

## Requirements

1. **模型成本可视化**：by_model 列表改为横向条形图，直观对比各模型费用占比
2. **最佳帖子高亮**：展示 growthReport.metrics.best_post_title，在表格区标注 top performer 行
3. **Views 数据展示**：在 MetricCard 新增 Views 指标卡，表格新增 Views 列
4. **趋势图空态**：trendData 全为 0 或无 published_at 数据时，图表显示友好提示而非空线段
5. **DataTable 排序**：支持点击列头排序（likes/comments/collects/engagement_rate 等数字列）

## Acceptance Criteria

* [ ] 模型成本有横向条形图可视化
* [ ] best_post_title 在表格区有高亮标识
* [ ] 新增 Views MetricCard 和表格列
* [ ] 无 published_at 数据时趋势图显示友好提示
* [ ] 数字列可点击排序（升序/降序切换）
* [ ] TypeScript 编译通过

## Out of Scope

* 新增分析指标
* 后端 API 变更
* 新增图表类型（如饼图）

## Technical Approach

1. **模型成本条形图**：不用 echarts，用纯 Tailwind div 渲染（与预算进度条风格一致），计算每模型占比，用 gradient bar 显示
2. **best_post_title 高亮**：在 Analytics.vue computed 里标记 bestRow，DataTable 接收 highlightRowKey prop
3. **Views MetricCard**：metrics 数组新增第 5 个 card（Total Views），tableColumns 新增 views 列，tableData 预处理
4. **趋势图空态**：TrendChart 组件增加 v-if 判断 data 全为 0 时显示 "No trend data" 文字提示
5. **DataTable 排序**：DataTable 新增 sortable prop 标记可排序列，维护 sortKey/sortOrder ref，点击列头切换排序

## Technical Notes

* 关键文件：Analytics.vue, DataTable.vue, MetricCard.vue, TrendChart.vue, EngagementChart.vue, en.json, zh-CN.json
* PostPerformance.views 字段在 types 里已存在但未使用
* views 的 total 需在 Analytics.vue 新增 computed
* DataTable 排序是通用功能，应放在 DataTable 组件内而非 Analytics.vue
* best_post_title 来自 growthReport.metrics，需要判断是否与 tableData 中某行 title 匹配