# optimize: analytics page detail polish

## Goal

打磨数据分析页面的视觉细节：卡片副标题区分度、图表标题对称性、成本可视化、表格标题截断、MetricCard 风格一致性。

## Requirements

1. **MetricCard subtitle 区分度**：4个卡片不要都用"This Week"，成本卡用"Today's cost"，互动率卡用"Based on N posts"，帖子数卡用"This Week"
2. **EngagementChart 添加标题显示**：当前 TrendChart 有 title prop 显示区域，EngagementChart 没有，两者视觉不对称。给 EngagementChart 加 title prop 和标题栏
3. **成本进度条**：预算剩余只显示数字，加一个可视化进度条对比 total vs remaining
4. **DataTable title 列截断**：标题过长时 truncation 处理，避免溢出
5. **MetricCard subtitle icon 颜色跟随 variant**：当前 TrendingUp icon 固定 cyan 色，改为跟随卡片 variant

## Acceptance Criteria

* [ ] 成本卡 subtitle 显示 "Today" 而非 "This Week"
* [ ] 互动率卡 subtitle 显示 "Based on N posts"
* [ ] EngagementChart 显示标题栏
* [ ] 成本区域有进度条可视化
* [ ] DataTable title 列长文本截断
* [ ] MetricCard subtitle icon 颜色跟随 variant
* [ ] TypeScript 编译通过

## Out of Scope

* 新增分析指标
* 后端 API 变更
* 新增图表类型

## Technical Approach

1. MetricCard subtitle：Analytics.vue 传入不同 subtitle 文案 + icon variant
2. EngagementChart：加 title/variant Props 和标题栏渲染（参考 TrendChart 的标题区域样式）
3. 成本进度条：计算 budget_remaining / total_cost 比率，用 Tailwind div 渲染
4. DataTable title 列：在 Analytics.vue 的 tableColumns 里给 title 列加 className，或修改 DataTable 组件支持 column class
5. MetricCard icon：从固定 cyan 改为 variant 对应色

## Technical Notes

* 关键文件：Analytics.vue, MetricCard.vue, EngagementChart.vue, DataTable.vue
* MetricCard colors 对象已有 pink/cyan/purple/peach 的 bgLight 和 text 字段，可以直接用
* EngagementChart 目前无 title prop，需新增
* DataTable 目前无列级 class 支持，最简单方案是在 Analytics.vue tableData 里把 title 做截断预处理，但这样丢失完整信息。更好的方案是 DataTable 给 title 列加 `truncate` class