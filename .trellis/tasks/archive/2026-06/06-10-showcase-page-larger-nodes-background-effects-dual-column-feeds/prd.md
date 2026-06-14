# Showcase page: larger nodes, background effects, dual-column feeds

## Goal

升级 Showcase 页面视觉效果：让 pipeline 节点更大更醒目、增加背景氛围动效、将工作流卡片从单列/三列改为双列 feeds 布局，提升整体视觉冲击力和信息密度。

## What I already know

* 当前 Showcase.vue 有 5 层布局：椭圆闭环动画 → 统计条 → Featured 卡片 → 过滤器 → 三列卡片网格
* 桌面端 pipeline 节点 68px 圆形，带 SVG 椭圆轨道、彗星动画、能量脉冲
* 移动端是 3 列 48px 节点网格
* 卡片使用 `liquid-glass` 系列样式，含 hover 效果
* 页面背景是多层线性渐变
* 卡片网格：`grid-cols-1 md:grid-cols-2 lg:grid-cols-3`

## Requirements

* 增大 pipeline 节点：桌面端从 68px → 88px 圆形，保持圆形+图标布局
* 添加背景氛围效果：渐变光晕浮动（纯 CSS radial-gradient + animation，2-3 个缓慢移动的模糊光斑）
* 改为双列宽卡片 feeds 布局：桌面端 2 列（`grid-cols-1 md:grid-cols-2`），移除 lg:3 列

## Acceptance Criteria

- [ ] Pipeline 节点桌面端尺寸为 88px，图标适配放大
- [ ] 页面背景有 2-3 个渐变光晕缓慢浮动（纯 CSS，无 JS）
- [ ] 卡片网格桌面端为双列，卡片宽度利用更充分
- [ ] 移动端适配正常（单列卡片，节点保持 48px）
- [ ] `prefers-reduced-motion` 下光晕动画静止
- [ ] 无性能回退（动画帧率 ≥ 30fps）

## Definition of Done

* Lint / typecheck / CI green
* 移动端和桌面端手动验证

## Out of Scope

* 瀑布流（masonry）布局 — 未来可选
* 卡片内嵌 mini-timeline — 未来可选
* 实时执行节点高亮脉冲 — 未来可选
* Replay 页面联动修改 — 独立页面不涉及
* Featured 卡片尺寸比例调整 — 保持现有逻辑

## Technical Approach

1. **节点放大**：修改 `stepStyle()` 中的 `nodeSize` 常量从 68→88，更新椭圆轨道偏移计算，图标 `size="lg"` 保持
2. **光晕浮动**：在 `.showcase-page` 背景 CSS 中叠加 2-3 个 `radial-gradient` 光斑，用 CSS `animation` 做 `translate` + `opacity` 浮动，周期 8-15s
3. **双列布局**：grid 从 `1/2/3` 列改为 `1/2` 列，移除 `lg:grid-cols-3`

## Decision (ADR-lite)

**Context**: 需要确定三个视觉升级的具体实现方向
**Decision**: 双列宽卡片（不是左右分栏）；渐变光晕浮动（不是 Canvas 粒子）；88px 圆形节点（不是方形卡片）
**Consequences**: 改动量最小、纯 CSS 无性能风险、视觉提升明显；双列可能减少同时可见卡片数量，但单卡信息密度更高

## Technical Notes

* 主要修改文件：`frontend/src/views/Showcase.vue`（模板 + CSS + JS 常量）
* 椭圆轨道 SVG 参数需随 nodeSize 调整
* 光晕动画需 `prefers-reduced-motion` 降级为静止渐变
* `WorkflowCardBody` 组件内容不需要修改（卡片更宽后内容自动受益）
