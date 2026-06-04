# optimize: analytics page UX polish and empty states

## Goal

在已完成布局间距和 echarts 懒加载的基础上，继续打磨数据分析页面的 UX 细节：空状态、数据展示、错误处理、交互体验。

## Requirements

1. **空状态优化**：无数据时显示引导空状态（带图标 + 描述 + 操作按钮跳转首页启动 workflow）
2. **数据格式化**：engagement_rate 列加 % 后缀；published_at 列格式化为友好日期
3. **间距一致性**：成本明细子卡片 p-3→p-4；insight 卡片 p-3→p-4；模型成本行 py-1.5 px-3→py-2 px-4
4. **i18n 修复**：Header 中 Account/Period 硬编码英文改为 i18n key
5. **错误状态**：API 失败时显示错误提示 + 重试按钮
6. **刷新按钮**：Header 区域添加刷新按钮，点击重新 fetchAllData

## Acceptance Criteria

* [x] 无数据时显示引导空状态组件（图标 + 文字 + CTA 按钮）
* [x] engagement_rate 显示如 "5.2%" 而非 "5.2"
* [x] published_at 显示如 "Jun 4" 而非 ISO 串
* [x] 成本/insight 子卡片 padding 与 MetricCard 风格一致
* [x] Header Account/Period 标签走 i18n
* [x] API 错误时显示错误提示 + 重试按钮
* [x] 刷新按钮可触发 fetchAllData
* [x] TypeScript 编译通过

## Out of Scope

* 新增分析指标
* 后端 API 变更
* 图表类型变更
* 数据缓存

## Technical Approach

* 数据格式化：Analytics.vue 预处理 tableData，生成 engagement_rate_display / published_at_display 列
* 错误/空状态：新增 hasError / isEmpty computed，用 v-else-if 切换
* 刷新按钮：Header 区域添加 RefreshCw 图标按钮
* 间距：成本子卡片 p-4、insight p-4、模型行 py-2 px-4、section header mb-5
* i18n：新增 analytics.account / analytics.period / analytics.refresh / analytics.refreshing / analytics.empty.* / analytics.error.*

## Technical Notes

* 关键文件：Analytics.vue, en.json, zh-CN.json
* DataTable 未修改 — 格式化在 Analytics.vue 预处理，不侵入通用组件
