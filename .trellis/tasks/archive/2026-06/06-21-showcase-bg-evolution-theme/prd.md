# 展示页背景自我进化主题元素

## Goal

背景加密已让页面"不空"，但当前背景元素（grid/星座/mesh/粒子/光球）偏抽象装饰，与页面核心主题"闭环自我进化"没有语义关联。本轮在背景上增加元素，使其呼应/强化"自我进化"主题。

## What I already know

- 主题语义载体：闭环中心 `closedLoop`（"闭环自我进化"）+ `closedLoopDesc`（"数据分析驱动下一轮趋势洞察"）
- 椭圆闭环轨道 + 6 节点（scouting→planning→creating→reviewing→publishing→analyzing）已表达"闭环"，但背景层无主题呼应
- 当前背景层（scoped style）：`showcase-bg-grid`（细线网格）/`showcase-bg-mesh`（双色 blob）/`showcase-constellation`（SVG 连线）/`showcase-bg-dots`（点阵）/`showcase-aurora`（极光）/`showcase-glow-amber/emerald`（光球）/`showcase-particles`（20 粒子）
- 颜色品牌：rose/teal/amber/violet/emerald/sky
- spec `frontend/animation-patterns.md`：新增常驻动效必须 reduced-motion 显式覆盖

## Open Questions

- ~~用哪类元素？~~ → 进化树/分支生长线

## Requirements

### 进化树背景元素
- 在背景增加细线绘制的进化树/分支生长 SVG，从一点（或闭环中心/左下）向外逐级分叉
- 语义："从单次洞察生长出多轮内容/多分支演化"——呼应"自我进化"
- 视觉：极淡品牌色细线、节点小圆点、分叉 2-3 级深度、多棵散布在不同区域填补空白
- 可选：分支末端有缓慢生长动效（stroke-dashoffset 绘制）或末端点呼吸——传达"持续生长"
- 与现有椭圆闭环视觉协调（可作为闭环外的"演化森林"背景）

### 一致性 & 兜底
- z-0 层、不抢内容
- 颜色用品牌色（rose/teal/amber/violet/emerald/sky 轮转）
- prefers-reduced-motion：生长动效静止，树静态显示
- 不破坏已验证的背景加密效果（grid/mesh/粒子/星座保留）

## Acceptance Criteria

- [ ] 背景新增元素视觉上呼应"自我进化"主题
- [ ] 前景内容可读性不降
- [ ] prefers-reduced-motion 下新增动效静止
- [ ] 不破坏现有交互
- [ ] typecheck + build 通过

## Out of Scope

- 不改闭环轨道/节点本身的结构
- 不改数据/交互逻辑
- 不引入新依赖

## Technical Notes

- 主文件 `frontend/src/views/Showcase.vue`
- 主题文案 `showcase.closedLoop` / `closedLoopDesc`
