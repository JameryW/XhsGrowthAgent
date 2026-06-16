# 优化展示页工作流卡片信息层级 + 回放页面信息层级优化

## Goal

优化 Showcase 页工作流卡片和 Dashboard 回放页的信息层级：保留全部信息但重新排列视觉层级（4级），突出关键信息，让用户一眼判断工作流状态和价值。

## Requirements

### 1. 卡片信息重组（WorkflowCardBody.vue）

4级视觉层级：

| 层级 | 内容 | 样式 |
|---|---|---|
| **一级** | 选题标题(selected_topic) / 品牌名(brand_name) | `text-base font-bold text-slate-900` |
| **二级** | 文案标题(selected_title) / 产品名(product_name) | `text-sm font-semibold text-rose-600` |
| **三级** | hashtag(≤3) + 博主昵称 + 内容版本数 + 卖点(≤2) | `text-xs` 标签形式 |
| **四级** | 热门话题 + 色板 + 分析数据 + Ripple病毒率 | `text-[10px] text-slate-400` 淡色 |

关键改动：
- 一级标题从 `text-sm font-bold` 升级为 `text-base font-bold text-slate-900`，占据视觉焦点
- 二级标题从 `text-xs font-medium` 升级为 `text-sm font-semibold`
- 三级标签统一为 `text-xs`，去掉多余的间距
- 四级元数据行保持 `text-[10px]`，但用更淡的颜色（`text-slate-400` → `text-slate-300` 对数值）
- 卖点标签从 `text-[10px]` 升为 `text-xs`，但限制 2 个（原 3 个）

### 2. 卡片整体结构优化（Showcase.vue）

- **移除独立进度条区域**（与 header 百分比重复），将进度条整合到 header 中
- 卡片结构简化为：Header(含进度) → Body(4级信息) → Footer

### 3. 回放页面信息层级优化

Dashboard 回放模式中同样突出关键信息、弱化次要信息：
- ContentCards 组件中，选题标题/文案标题用更大字重
- 分析数据、Ripple 数据等次要信息缩小/淡色
- 发布结果、错误信息等关键信息保持醒目

## Acceptance Criteria

* [ ] 卡片一级标题（选题/品牌）明显大于其他文字，2秒扫视可识别
* [ ] 4级视觉层级清晰：大标题 > 副标题 > 标签 > 元数据
* [ ] Brief 模式和 Standard 模式均有正确的 4 级层级
* [ ] 独立进度条区域移除，进度信息保留在 header
* [ ] 回放页面（Dashboard）中关键信息突出、次要信息淡色
* [ ] 移动端和桌面端均可用
* [ ] i18n 合规（无硬编码字符串）

## Definition of Done

* Lint / typecheck green
* 手动验证展示页卡片和回放页视觉效果

## Out of Scope

* 后端 API 改动
* 筛选/排序逻辑改动
* 卡片布局形式改动
* 新增功能/新增信息字段

## Technical Approach

### 文件改动

1. **`frontend/src/components/WorkflowCardBody.vue`** — 重组信息层级
   - 一级标题升级字号/字重
   - 二级标题升级字号/字重
   - 三级标签统一化
   - 四级元数据淡色化

2. **`frontend/src/views/Showcase.vue`** — 移除独立进度条
   - 删除卡片中间的进度条区域（px-4 pt-2 的进度条 div）
   - 将进度信息整合到 header（百分比数字）

3. **`frontend/src/components/dashboard/ContentCards.vue`** — 回放页层级优化
   - 选题/文案标题升级字号
   - 分析数据、Ripple 等淡色处理

## Decision (ADR-lite)

**Context**: 卡片信息堆砌、层级不清，用户难以快速判断工作流状态。

**Decision**: 重组而非减法——保留全部信息但建立4级视觉层级，同时优化回放页面。

**Consequences**: 视觉层次清晰，信息不丢失；改动集中在样式/字号，风险低。
