# optimize: analytics page layout and loading

## Goal

优化数据分析页面：宽松舒展的间距 + echarts 懒加载改善首次加载体验。

## Requirements

* MetricCard/DataTable/图表组件增加宽松内边距（20px+）
* Analytics 页面统一 spacing 体系（section gap 24px, card padding 20px+）
* echarts 图表改为 defineAsyncComponent 懒加载，先显示 skeleton 再渐进渲染
* 图表区域加载时显示 skeleton 占位

## Acceptance Criteria

* [x] MetricCard 内容距离边框 ≥ 20px
* [x] DataTable 行间距 ≥ 8px gap，单元格 padding ≥ 12px
* [x] 页面 section gap 24px
* [x] echarts 组件懒加载，首次加载不再阻塞页面
* [x] 图表加载中显示 skeleton
* [x] TypeScript 编译通过

## Out of Scope

* 数据可视化图表类型变更
* 新增分析指标
* 后端 API 性能优化
* API 缓存

## Technical Approach

1. **间距**：MetricCard `p-5` → `p-6`，DataTable 行 `gap-2` + 单元格 `px-3 py-2`，section `space-y-6`
2. **echarts 懒加载**：图表组件改用 `defineAsyncComponent` + `Suspense`/loading slot
3. **skeleton**：图表区域加载时显示 AnalyticsSkeleton

## Technical Notes

* 关键文件：Analytics.vue, MetricCard.vue, DataTable.vue, charts/*.vue, AnalyticsSkeleton.vue
* echarts 注册在各 chart 组件的 setup 中同步执行，需改为异步
