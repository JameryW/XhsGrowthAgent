# 展示页背景加密与结构装饰

## Goal

上一轮视觉优化为展示页加了背景层（点阵/极光/amber+emerald 光球/漂浮粒子），但用户反馈"背景看着有点空"。本轮在此基础上：加密现有层 + 补结构性纵深装饰，让背景更丰富、有骨架而不只是散光斑。

## What I already know

- 当前背景层（`Showcase.vue` scoped style）：
  - `.showcase-bg-dots`：22px 网格点阵，opacity 0.5，**mask 只让顶部椭圆区可见**（中下部无点阵）
  - `.showcase-aurora`：conic 渐变，blur(70px) + opacity 0.5（被过度稀释）
  - `.showcase-glow-amber/emerald`：radial 光球，opacity 0.5，渐变到 70% transparent（可见范围小）
  - `.showcase-particles`：**只有 5 个点**，no-repeat，opacity 0.6（太稀疏）
  - 原 `.showcase-page::before/after`（rose/sky）、`.showcase-glow-mid`（violet）：opacity 动画上限 0.5-0.9
- 诊断：**层多但每层弱 + mask 限区 + 互相稀释 = 空**
- 全局 `main.css` 已有可复用：`liquid-mesh-bg`（mesh 漂移）、`aurora`、`star-field`、`grid-pattern`、`floating-particles`、`gradient-animate`
- 上一轮 spec `.trellis/spec/frontend/animation-patterns.md`：reduced-motion 必须显式 `animation: none` 覆盖入场/常驻动效

## Requirements

### A. 加密 + 提强度（现有层）
- 点阵：去掉 mask（或大幅放宽），opacity 提到 0.6-0.7，整页可见；可加密网格（22→18px）
- 极光：降 blur（70→40px）保留柔化，opacity 提到 0.6-0.7，尺寸放大
- amber/emerald 光球：opacity 提到 0.65-0.75，尺寸放大，渐变扩散到 80%
- 粒子：从 5 个加密到 18-24 个，分散在更多位置，opacity 0.55-0.7
- 原 rose/sky/violet 光球：opacity 上限适度上调

### B. 结构性纵深装饰（新增，填充空白）
- hero 闭环区后方：加一层缓慢旋转/漂移的渐变 mesh（复用 `liquid-mesh-bg`/`aurora` 思路但更可见）
- 卡片网格区背景：加细线网格或星座连线 SVG（极淡，给"骨架"感）
- 各区段间或页脚：加流光分隔带 / 细装饰线
- 闭环区外围：可加柔光环或同心圆细线，强化"闭环"视觉中心

### C. 一致性 & 兜底
- 所有新增/调整层保持 `z-0`、内容 `z-10` 之上
- 颜色沿用品牌色（rose/teal/amber/violet/emerald/sky）
- `prefers-reduced-motion`：所有新增常驻动效显式 `animation: none`，opacity 静态
- 不抢内容：背景层加完后前景文字/卡片对比度仍清晰

## Acceptance Criteria

- [ ] 背景在桌面+移动端均更"有层次、有骨架"，不再大面积空
- [ ] 前景内容（标题/卡片/统计）可读性不降
- [ ] `prefers-reduced-motion` 下所有新增动效静止
- [ ] 不破坏现有交互（点击/筛选/排序/加载更多/Featured 跳转）
- [ ] 不新增硬编码可见文本
- [ ] typecheck + build 通过

## Definition of Done

- lint/typecheck/build 通过
- 改动符合 `liquid-glass*` 设计语言
- reduced-motion 覆盖完整

## Out of Scope

- 不加鼠标/滚动交互背景（用户未选该方向）
- 不改数据/交互逻辑
- 不做暗色模式
- 不引入新依赖

## Technical Notes

- 主文件：`frontend/src/views/Showcase.vue`（scoped style + 模板背景层 div）
- 复用参考：`frontend/src/styles/main.css`（`liquid-mesh-bg`/`aurora`/`star-field`/`grid-pattern`/`floating-particles`）
- 上一轮 spec：`.trellis/spec/frontend/animation-patterns.md`（reduced-motion 显式覆盖规则）
