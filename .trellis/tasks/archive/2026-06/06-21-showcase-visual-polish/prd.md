# 优化展示页视觉效果

## Goal

优化 `frontend/src/views/Showcase.vue`（"展示页"）的视觉效果，提升整体观感。具体方向待与用户确认。

## What I already know

- 展示页 `Showcase.vue`（881 行）已具备较完整的视觉体系：
  - 背景：3 个漂移的环境光球（`::before` / `::after` / `.showcase-glow-mid`），渐变底色
  - 闭环流水线：桌面端椭圆 SVG 轨道（渐变描边 + 虚线流动 + 6 节点能量脉冲 + 彗星沿 `animateMotion` 运动 + 节点 hover 辉光）；移动端 2x3 网格 + 横向流动小 SVG
  - 数据统计条、Featured 工作流卡、筛选栏、卡片网格、加载更多、页脚
  - 已接入 `liquid-glass*` 设计系统（main.css 中多层玻璃质感）
  - 已支持 `prefers-reduced-motion`
- 全局样式 `styles/main.css` 提供大量可用动效类（`gradient-text-animate`、`shimmer`、`float`、`card-bounce`、`gradient-border-animate` 等），其中多数尚未在展示页使用
- 组件库已存在 `AnimatedCounter.vue`、`CircularProgress.vue`、`CelebrationEffect.vue` 等可复用动效组件

## Assumptions (temporary)

- "优化"指视觉/动效层面的打磨，不涉及数据逻辑或新增页面
- 不要求暗色模式（当前体系为亮色 liquid glass）
- 改动应保留现有 `liquid-glass*` 设计语言的一致性

## Open Questions

- ~~优化方向？~~ → 用户确认：以上全部（打磨 + 降噪 + 增强动效 + 性能）

## Requirements (evolving)

四方向合并为"精修"哲学：**用有目的的微交互替换低价值的常驻环境噪声，强化层次，并改善性能**。

### 背景层丰富（用户明确要求"增加一些背景元素"）
- 保留现有 3 个漂移光球，再增补 1–2 个互补色软光球（amber / emerald），填充视觉空白区，低 opacity 慢漂移
- 叠加一层极淡的径向点阵纹理（复用 `glow-dots`/`particle-bg` 思路），为背景增加质感而非噪点
- 在闭环流水线区后方加一层极淡的 conic aurora / mesh 渐变（复用 `aurora`/`liquid-mesh-bg` 思路），给 hero 区增加纵深
- 少量缓慢漂浮的柔光粒子（复用 `floating-particles` 思路），品牌色、低 opacity
- 所有新增背景层置于 `z-0`、内容 `z-10` 之上；低 opacity、纯 CSS、`prefers-reduced-motion` 下静止
- 原则：背景更"有层次、有氛围"，但绝不抢内容；前景降噪仍对 SVG 闭环常驻动效生效

### 降噪 + 提升层次（针对前景常驻动效与排版）
- SVG 闭环：降低虚线流动 / 能量脉冲 / 彗星的不透明度与频率，节点 hover 辉光保留（有价值的触发式反馈）
- 统一各区段间距节奏（`mb-4`/`md:mb-6` 混用 → 统一）、拉开排版字号层级、强化分区留白

### 增强动效（触发式，非新增常驻循环）
- 卡片网格：交错入场动画（基于 `visibleCards` 的 staggered transition）
- 统计数字：复用 `AnimatedCounter.vue` 做 count-up
- 卡片 hover：更明显的 lift + 渐变描边（复用 `gradient-border`/`gradient-border-animate`）
- Featured 卡：微妙边框流光强调"焦点"
- 闭环节点：依次激活的高光扫过循环，传达"闭环运转"语义（替代部分静态常驻动效）

### 性能 / 流畅度
- 评估将 SMIL `animateMotion`（彗星）改用 CSS `offset-path`；能量脉冲改 CSS keyframe
- 降低网格多卡片并发 `backdrop-filter` 成本（非 hover 卡降级 blur）
- 扩展 `content-visibility: auto` 到 featured / stats

### 一致性 / 细节
- 颜色 token 统一（rose/teal/amber/violet/emerald/sky）
- 移动端闭环区与桌面端视觉对齐（节点辉光一致化）

## Acceptance Criteria (evolving)

- [ ] 展示页在桌面端与移动端均视觉一致
- [ ] `prefers-reduced-motion` 下所有新增动效被正确禁用
- [ ] 不破坏现有交互（点击跳转、筛选、排序、加载更多、Featured 跳转）
- [ ] 不新增硬编码可见文本（如需新增走 i18n 双语 key）
- [ ] lint / typecheck 通过

## Decision (ADR-lite)

**Context**: 用户要求同时降噪、增强动效、提层次、优化性能，并明确要求"增加一些背景元素"——降噪与背景丰富方向需调和。
**Decision**: 背景做"加法"（增补光球/点阵/aurora/漂浮粒子，低 opacity 慢动），前景常驻动效做"减法"（SVG 闭环克制化），触发式微交互做"加法"（入场、count-up、hover、节点激活扫光）；性能上用 CSS 替代部分 SMIL 并降低并发 backdrop-filter。
**Consequences**: 背景更有氛围但不抢内容；前景更"克制而精致"；需确保 reduced-motion 全覆盖新增背景与前景动效；不引入新依赖。

## Definition of Done (team quality bar)

- lint / typecheck 通过
- 改动不破坏现有交互（点击跳转、筛选、排序、加载更多）
- 改动符合现有 `liquid-glass*` 设计语言

## Out of Scope (explicit)

- 不改数据获取/排序/筛选/分页逻辑
- 不新增页面或路由
- 不做暗色模式（当前为亮色 liquid glass 体系）
- 不引入新运行时依赖（offset-path/ CSS keyframe 即可满足）
- 不重写 `WorkflowCardBody` / `AppIcon` 等共享组件内部

## Technical Notes

- 主文件：`frontend/src/views/Showcase.vue`
- 设计系统：`frontend/src/styles/main.css`（`liquid-glass*` 全家桶 + 动效工具类）
- 卡片样式：`frontend/src/styles/cards.css`
- 动效基础：`frontend/src/styles/animations.css`
- 可复用组件：`AnimatedCounter.vue`、`CircularProgress.vue`
- `prefers-reduced-motion` 已在 Showcase `<style scoped>` 末尾处理
