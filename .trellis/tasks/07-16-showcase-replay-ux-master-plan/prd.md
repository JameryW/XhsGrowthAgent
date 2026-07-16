# 展示页与工作流回放全面用户体验优化 PRD（UX V2）

## 0. 文档信息

| 字段 | 内容 |
| --- | --- |
| 状态 | Implemented — automated checks passed; release gates documented below |
| 日期 | 2026-07-16 |
| 优先级 | P0 |
| 产品目标 | 用真实案例建立信任，用可理解的过程回放完成说服和转化 |
| 核心路由 | `/`、`/replay/:publicId` |
| 主要范围 | Showcase、WorkflowReplay、公开只读数据契约、结果 presenter、响应式、暗黑模式、无障碍、性能、埋点 |
| 非主要范围 | 工作流执行逻辑、公开页面编辑能力、全站换肤、生成模型与内容质量算法 |
| 当前基线 | `main@4967acbc`；实现分支 `feat/showcase-replay-ux-v2`；详细证据见 `research/current-ux-audit.md` |
| 建议投入 | 1 名前端主责 + 0.5 名后端 + QA/设计评审，约 15–22 人日 |

本文是 2026-07-16 当前实现之上的下一阶段总方案。此前已完成的缓存、状态分离、
深链、错误恢复和响应式能力是基线，不重复重做。本 PRD 收敛仍在进行的多轮局部视觉任务，
后续不再以“再优化一轮样式”为完成定义。

实现状态：PR-0 至 PR-6 已落地。公开 Showcase/Replay 已切换到独立的脱敏 DTO，默认关键步骤、
认证后的技术步骤、结果 presenter、URL 深链、筛选/分享/CTA、缓存与错误状态均已接入；公开
可见性默认 private，并支持 DB 标记或 `XHS_SHOWCASE_PUBLIC_IDS` 灰度 allowlist。自动化质量门槛
已在本任务验收中通过；视觉矩阵、axe、Lighthouse 和真实环境灰度仍属于发布前操作门槛，不能由
单元测试替代，见第 17、20 节。

---

## 1. 执行摘要

当前两页已经“可用”，但还没有形成一条强、短、可信的用户路径：

```text
首次访问
  → 5 秒内看懂价值
  → 看到一个真实且可解释的案例证据
  → 打开过程回放
  → 看懂关键步骤、输入、决策和产出
  → 顺序浏览或定位某一步
  → 理解最终结果与风险
  → 开始自己的创作 / 回到工作台
```

本轮要完成三个转变：

1. **Showcase：从公开运维看板转为可信案例与转化页面。**
   不再用“总工作流、需关注、平均进度”作为主要说服力，而是用经过授权的真实案例、
   核心产出和完整回放建立信任。
2. **WorkflowReplay：从内部 checkpoint 浏览器转为面向用户的过程解释工具。**
   默认只展示关键业务步骤，原始代理名、错误码、JSON 和技术字段进入受控的高级视图。
3. **公开数据：从复用内部接口转为显式公共契约。**
   只有明确允许公开的案例进入 Showcase；公共 DTO 只包含展示需要的字段，并支持轻量
   manifest + 按选中 checkpoint 加载详情。

默认产品决策已经在本文确定，实施不需要再次等待以下选择：

- Showcase 只展示明确标记为公开的精选案例，不再自动展示所有内部工作流。
- 未登录用户主 CTA 为“开始创作”，跳转 `/login?redirect=/start`。
- Replay 默认显示“关键步骤”；已登录用户可切换“全部技术步骤”。
- P0 不自动播放；先提供上一/下一关键步骤和稳定的顺序阅读。自动播放为 P2 实验。
- 公开页面不展示原始错误、账号 ID、完整 threadId、工具输出、JSON fallback 或调试字段。
- 首次 Replay 使用轻量 checkpoint manifest，选中后再加载详情；旧接口保持一版兼容。

---

## 2. 背景与现状

### 2.1 已完成能力（不得回退）

- Showcase 列表优先，详情最多 3 并发延迟加载；支持 30 秒 session cache。
- Showcase 支持状态/模式/排序 URL 同步、推荐项去重、局部详情重试和返回上下文恢复。
- Replay 已分离 live workflow state 与 selected checkpoint，支持默认有效 checkpoint、
  checkpoint query 深链、移动端检查点折叠、稳定最终摘要和部分成功状态。
- 两页已具备中英文、暗黑模式、reduced-motion 基础降级、主题即时切换和隐私安全埋点壳层。
- 公开路由不再被首屏 token 校验阻塞。

### 2.2 当前核心问题

| ID | 当前表现 | 用户影响 | 优先级 |
| --- | --- | --- | --- |
| P-01 | Showcase 首屏仍以 Hero、动态统计和装饰为主，第一条真实案例在移动端首屏底部才出现 | 价值证据到达较晚，首次访问者难判断产品是否真实有效 | P0 |
| P-02 | Showcase 使用运维语言：运行中、需关注、平均进度，并展示所有工作流 | 页面身份混乱，且公共展示缺少明确数据授权边界 | P0 |
| P-03 | 卡片出现 `trend`、`P1`、`viral`、`views/likes` 等内部或硬编码表达 | 非内部用户看不懂，双语和品牌可信度下降 | P0 |
| P-04 | 公开 Replay 首批 20 checkpoints 样本响应约 1.0 MB | 冷启动首个结果慢，短期缓存只改善重复打开 | P0 |
| P-05 | 49 个 checkpoint 中系统节点和有业务产出的节点同权展示 | 用户面对大量代理名和无数据步骤，无法快速理解过程 | P0 |
| P-06 | Replay 结果可直接展示 `auth_failed`、英文 status、score source、seed 或 JSON | 技术噪声、可理解性和公开数据安全均不足 | P0 |
| P-07 | 未登录用户的 Replay 没有主 CTA | 用户在最有说服力的页面看完后无下一步 | P0 |
| P-08 | 两页和 rail 中有大量 9–11px 用户可见文字 | 移动端和低视力用户阅读困难，层级主要靠“更小更淡”表达 | P0 |
| P-09 | Replay 名为回放，但主要是静态快照选择，没有连续的上一/下一关键步骤体验 | 过程难以形成叙事，用户需要自己拼接步骤关系 | P1 |
| P-10 | 多层玻璃和持续背景动效与业务内容争抢视觉权重 | 页面看起来丰富，但核心证据、结果和动作不够突出 | P1 |
| P-11 | 11 个同区域旧任务仍为 in-progress，两个 route 文件分别接近 2,000/1,400 行 | 并行修改和视觉反复风险高，难形成稳定完成定义 | P0 |

### 2.3 根因

- 页面同时承担营销、公开监控、技术审计和已登录运营四种角色，没有明确默认受众。
- 公共页面直接消费内部 workflow/status/history 数据形状，UI 被后端字段和代理结构牵引。
- 视觉迭代多次在单文件上叠加，缺少稳定的 presenter、设计 token 和页面级状态组件。
- 埋点已有事件，但还没有完整漏斗、曝光事件、首个结果可见事件和性能分桶。
- 验收偏“无溢出、能点击”，不足以判断“是否看懂、是否信任、是否继续行动”。

---

## 3. 目标、指标与非目标

### 3.1 用户目标

1. 首次访客在 5 秒内能回答“这个产品做什么”和“有什么真实证据”。
2. 用户从展示页最多两次操作进入一个有价值的回放。
3. 用户进入回放后 10 秒内能回答：
   - 这个案例最终/当前是什么状态？
   - 我正在查看哪个阶段和关键步骤？
   - 这一步做了什么、产出了什么、为什么重要？
   - 最终内容、指标或失败原因是什么？
4. 用户可顺序查看上一/下一关键步骤，不需要理解 checkpoint、代理或内部阶段映射。
5. 用户看完后能明确选择：开始创作、进入工作台、返回原上下文或复制当前步骤链接。

### 3.2 产品目标

- 提升 Showcase → Replay 的有效打开率。
- 降低 Replay 首个真实结果出现前的退出率。
- 提升非默认关键步骤浏览率、结果展开/复制率和 Replay → 创作 CTA 转化率。
- 将公共案例选择、字段、错误和媒体资源纳入明确治理。
- 将后续体验迭代收敛到一份总 PRD 和一组可测量的完成标准。

### 3.3 上线后目标

先采集 7 天稳定基线，再比较 UX V2：

| 指标 | 目标 |
| --- | --- |
| Showcase → Replay 打开率 | 相对提升 ≥ 20% |
| Replay 首个结果前退出率 | 相对下降 ≥ 20% |
| 至少浏览 2 个关键步骤的会话比例 | 相对提升 ≥ 20% |
| Replay 结果复制/展开交互率 | 相对提升 ≥ 15% |
| Replay → 登录/开始创作 CTA 转化 | 相对提升 ≥ 15% |
| 临时加载失败后的重试成功率 | ≥ 80% |
| 公开字段/隐私事故 | 0 |

低流量阶段效果指标不阻塞上线；功能、隐私、可访问性和性能门槛是硬门槛。

### 3.4 非目标

- 不修改 LangGraph 节点、工作流状态机、审核/发布业务规则或内容生成算法。
- 不允许公开 Replay 修改、恢复、重试、审核或发布工作流。
- 不在本轮重做 Dashboard、Review、History、Analytics 等认证页面。
- 不增加无目的背景层、粒子、3D、自动滚动或默认自动播放。
- 不在浏览器长期保存公开回放正文；继续使用短 TTL session cache。
- 不用前端字符串拼接掩盖数据契约问题；缺失公共字段应在 DTO/presenter 层解决。

---

## 4. 目标用户与 Jobs-to-be-Done

| 用户 | 任务 | 成功状态 |
| --- | --- | --- |
| 首次访客 | 判断产品是否真实、是否适合自己的内容场景 | 快速看到完整案例证据并进入回放 |
| 潜在客户/合作方 | 审阅 AI 每一步的依据、产出和最终结果 | 不理解内部架构也能讲清案例过程 |
| 已登录创作者 | 从公开案例获得信心后开始自己的任务 | CTA 直接进入新建流程，不重复登录或丢来源 |
| 已登录运营/审核者 | 查看全部技术步骤并返回对应工作区 | 高级视图可审计，返回保留 thread 上下文 |
| 移动端浏览者 | 快速扫案例和关键结果 | 首屏看到证据/结果，不先滚过大面积装饰 |
| 键盘/读屏/低动态用户 | 完成相同的筛选、步骤选择和转化 | 控件语义、焦点、状态与内容同等可达 |

---

## 5. 体验原则

1. **证据先于解释**：先给真实结果，再解释六步流程和技术机制。
2. **面向用户，不面向数据结构**：用户看到“趋势洞察”“标题产出”，不是代理 key 和 raw JSON。
3. **公开默认简洁，认证后可审计**：关键步骤是默认；完整技术步骤是高级能力。
4. **一个屏幕一个主任务**：Hero 负责理解和进入案例；Replay 结果区负责阅读和导航。
5. **内容层级不能依赖极小字号**：通过布局、留白、字重和分组建立层级。
6. **状态可区分、可解释、可恢复**：加载、缓存、部分成功、空、失败、私有和已删除语义不同。
7. **移动端重新编排，不压缩桌面**：结果与动作优先，rail、摘要和技术细节按需展开。
8. **性能是体验功能**：第一条案例和第一个回放结果必须在装饰与非关键数据之前到达。
9. **公共数据最小化**：只有明确授权且对体验有价值的数据进入公共 DTO、DOM 和埋点。

---

## 6. 目标用户旅程

```text
进入 Showcase
  ├─ 首屏：一句价值 + 主 CTA + 一条真实案例证据
  ├─ 浏览：精选案例 / 模式 / 已发布结果
  ├─ 判断：标题、过程、状态、关键产出、更新时间
  └─ 打开案例
       ↓
进入 Replay
  ├─ 身份：案例、模式、只读状态、最终/当前状态
  ├─ 默认：最近一个有意义的关键步骤及真实结果
  ├─ 浏览：阶段 → 上/下一关键步骤 → 可选全部技术步骤
  ├─ 理解：本步做了什么 / 产出 / 依据 / 风险
  ├─ 总结：稳定最终结果与指标
  └─ 行动：开始创作 / 进入工作台 / 返回原列表 / 分享当前步骤
```

---

## 7. 整体信息架构

### 7.1 页面职责

| 页面 | 首要任务 | 次要任务 | 不承担 |
| --- | --- | --- | --- |
| Showcase | 建立信任并打开真实案例 | 解释工作流模式、引导开始创作 | 监控内部异常、展示全部账户任务 |
| Replay（公开） | 解释关键过程与最终结果 | 分享当前步骤、引导开始创作 | 展示原始调试数据、修改工作流 |
| Replay（认证高级） | 审计全部 checkpoint | 返回 Dashboard/History/Review | 替代业务工作台操作 |

### 7.2 Showcase 桌面线框

```text
┌ 品牌 ─────────────────────────── 登录 / 开始创作 / 主题 ┐
├─────────────────────────────────────────────────────────┤
│ 价值主张 + 说明 + 主 CTA       │ 精选真实案例：状态/标题/证据 │
│ 次入口：浏览完整案例           │ [查看完整过程]              │
├─────────────────────────────────────────────────────────┤
│ 案例工具栏：精选 / 趋势 / Brief / 已发布   搜索*  排序   │
├─────────────────────────────────────────────────────────┤
│ 案例卡 1                     │ 案例卡 2                      │
│ 状态 · 阶段 · 真实产出        │ 状态 · 阶段 · 真实产出         │
├─────────────────────────────────────────────────────────┤
│ 加载更多 / 状态提示                                        │
├─────────────────────────────────────────────────────────┤
│ 六步工作原理（紧凑、辅助）  →  最终 CTA  →  页脚            │
└─────────────────────────────────────────────────────────┘
```

`*` 公开案例达到 8 条后显示搜索；不足 8 条不展示无意义搜索框。

### 7.3 Showcase 移动线框

```text
品牌                         菜单/主题
价值主张（最多 2 行）
一句说明
[开始创作]  [浏览案例]
精选案例 mini card：状态 / 标题 / 一条证据 / 查看回放
────────────────────────────
筛选 chips                 排序
案例卡（单列）
案例卡（单列）
加载更多
六步工作原理（折叠/2×3）
```

### 7.4 Replay 桌面线框

```text
┌ 返回 │ 案例标题 / 模式 / 只读 │ 当前/最终状态 │ 分享 │ 主 CTA ┐
├ 阶段：洞察 → 策略 → 创作 → 审核 → 发布 → 分析 ─────────────┤
├──────────────┬──────────────────────────┬─────────────────┤
│ 关键步骤 rail │ 选中步骤结果              │ 稳定最终摘要     │
│ 阶段分组      │ 做了什么 / 产出 / 依据     │ 标题/发布/指标   │
│ 时间/数据类型 │ 技术详情（折叠）           │ 只读说明/CTA     │
│              │ [上一步]  12/18  [下一步]  │                 │
└──────────────┴──────────────────────────┴─────────────────┘
```

### 7.5 Replay 移动线框

```text
返回  案例标题                 分享/更多
状态 · 模式 · 只读
阶段横向导航（自动滚入 + 边缘渐隐）
[第 12 步 · 内容创作] [打开关键步骤]
选中步骤结果标题
真实结果内容
[上一个关键步骤] 12/18 [下一个关键步骤]
最终摘要（默认折叠一层）
[开始创作 / 进入工作台]
全部技术步骤（认证高级）
```

---

## 8. P0：Showcase 需求

### SHOW-01 明确公开展示页定位

- 默认受众是首次访客和潜在客户，不是内部运营者。
- 顶部标题必须表达结果价值，不再使用“工作流实例”作为 Hero 主标题。
- 建议中文主文案方向：
  - 标题：`从选题到发布，看见 AI 如何完成一条内容工作流`
  - 说明：`浏览经过授权的真实案例，查看每一步判断、产出与最终结果。`
- 英文使用等义短句，不逐字直译；主标题桌面不超过 2 行、移动不超过 3 行。
- “需关注、异常、平均进度”移出公开默认视图；认证用户去工作台查看运营状态。

### SHOW-02 顶部导航与认证分流

- 未登录：品牌、登录、主动作“开始创作”、主题切换；语言切换进入更多菜单（P1）。
- 已登录：品牌、进入工作台、开始新创作、主题切换。
- 移动端最多同时显示品牌、一个主动作和一个更多/主题入口，禁止横向挤出。
- 主 CTA 规则：
  - 未登录 → `/login?redirect=/start&source=showcase`
  - 已登录 → `/start?source=showcase`
- CTA 必须有按压、focus 和导航中反馈；短时间重复点击只触发一次导航。

### SHOW-03 结果优先 Hero

- 桌面 Hero 使用价值主张 + 精选案例证据双栏；移动端精选案例紧跟 CTA。
- 精选案例 mini card 至少包含：用户化状态、案例标题、一条核心产出、更新时间、
  “查看完整过程”链接。
- 无公开案例时 Hero 仍成立，右侧改为产品能力摘要，不显示全零统计。
- Hero 桌面建议高度 ≤ 360px；`390 × 844` 中第一条真实案例标题必须在前 620px 内出现。
- 装饰轨道只作为背景，不占独立内容列，不影响首个案例绘制。

### SHOW-04 公开案例治理与推荐

- 只有 `showcase_visibility=public` 且通过脱敏校验的案例进入页面。
- 支持后台/配置指定 `featured_rank`；没有人工精选时，fallback 顺序为：
  1. 已完成且有最终摘要；
  2. 有最多业务结果类型；
  3. 最近更新。
- 默认不推荐失败、暂停、取消或需要人工处理的案例。
- 推荐原因使用用户语言：`近期完成`、`完整过程`、`Brief 案例`、`含发布结果`，
  不展示内部 score。
- 精选案例在列表中只出现一次。

### SHOW-05 案例浏览工具栏

- 公开筛选改为：`精选`、`全部`、`趋势模式`、`Brief 模式`、`已发布`。
- 数据量 ≥ 8 时增加搜索，搜索范围只含公开标题、主题、品牌/产品和公开标签。
- 排序：`推荐`、`最近更新`、`流程完整度`；默认推荐。
- 状态、模式、排序和搜索写入 URL query；非法 query 归一化。
- 移动端筛选使用横向 chips + 独立排序按钮；显示边缘渐隐，不允许页面级横向滚动。
- 筛选结果变更后更新结果数；键盘触发时焦点移动到结果标题，指针触发不抢焦点。

### SHOW-06 案例卡信息层级

固定为五层：

1. 标题/品牌与产品。
2. 用户化状态、当前/最终阶段、模式。
3. 一条核心证据：生成标题、选题、发布结果、关键指标或失败后的可理解结论。
4. 更新时间、关键步骤数、是否有完整回放。
5. 唯一主动作“查看过程回放”。

要求：

- 卡片使用真实 `<a>` / `RouterLink`，支持新标签、复制链接、Tab 和 Enter。
- 卡片正文最小 14px，元信息最小 12px；禁止用户关键信息使用 9–11px。
- `trend` → `趋势模式`，`brief` → `Brief 模式`；`P1` → `优先建议` 或不展示。
- `viral`、`views`、`likes` 必须本地化并提供含义；无上下文指标不单独出现。
- 只展示一个最强证据，其他字段进入回放，避免卡片成为缩小版详情页。
- 卡片预览加载前后保持稳定高度；预览失败不影响标题、状态和回放入口。
- 缺失、部分成功、失败、私有化下线使用不同提示。

### SHOW-07 统计与可信信息

- 取消大面积四宫格运维统计。
- 只有样本足够且指标有解释时才显示公开统计，推荐：
  - 已公开完整案例数；
  - 可查看关键步骤数；
  - 含最终发布/分析结果的案例数。
- 少于 5 个公开案例时，统计替换为静态信任说明：`真实工作流`、`只读脱敏`、
  `完整过程可回放`，不强调小样本数字。
- 任何统计都必须标明数据范围，不将生成预测描述为实际效果。

### SHOW-08 流程解释与品牌视觉

- 六步流程移动到案例之后，作为“如何工作”辅助说明。
- 桌面使用紧凑横向流程；移动使用 2×3 或折叠面板，不能裁切节点。
- 同一时刻持续运行的品牌动画不超过 2 组；优先保留一个轨道/信号识别。
- 移动端默认静态背景，桌面背景在首个案例绘制后再激活。
- 不使用比正文更高对比度的背景线、光球或扫光。

### SHOW-09 状态模型

| 状态 | 表现 | 用户动作 |
| --- | --- | --- |
| 首次加载 | Hero 与 CTA 立即可用；案例区同结构 skeleton | 等待；不阻塞 CTA |
| 新鲜 cache + 后台刷新 | 立即展示缓存，显示非打扰“正在更新” | 正常浏览 |
| 列表成功 | 精选 + 工具栏 + 案例列表 | 筛选、打开回放 |
| 列表失败且有 cache | 保留案例，显示“最新数据暂不可用” | 重试刷新 |
| 列表失败且无 cache | Hero 保留，案例区错误说明 | 重试 / 开始创作 |
| 无公开案例 | 说明尚无公开案例，不显示筛选和零统计 | 开始创作 |
| 筛选为空 | 显示当前条件、结果 0 | 重置筛选 |
| 预览加载 | 卡片标题/状态稳定，证据区 skeleton | 可直接开回放 |
| 预览失败 | 列表字段降级 + 预览重试 | 重试 / 开回放 |
| 案例下线 | 当前列表移除；旧链接显示专用状态 | 返回案例列表 |

### SHOW-10 Showcase 性能要求

- 保留列表优先；首屏列表请求不得等待 status/detail。
- 建议公共 cases API 直接返回脱敏 preview，避免首屏为每张卡请求完整 status。
- 若仍保留详情请求：精选 + 首 2 张立即加载，并发 ≤ 3；其余接近视口或 idle 时加载。
- 常规移动网络下首个可识别案例目标 ≤ 2.5s；warm cache ≤ 500ms。
- 路由 chunk（不含共享 vendor）目标 ≤ 60KB minified；不新增同步图表/动画依赖。
- 背景 DOM 节点、定时器和 rAF 在离开页面时全部清理。

---

## 9. P0/P1：WorkflowReplay 需求

### REPLAY-01 明确公开视图与认证高级视图

- 公开默认视图：只读、关键步骤、用户化结果、稳定最终摘要、创作 CTA。
- 认证高级视图：可切换全部技术步骤、显示安全的 checkpoint 元信息、返回业务工作台。
- 切换高级视图不改变 checkpoint 数据，只改变导航密度和技术字段展示。
- 公开视图禁止出现账号 ID、完整 threadId、原始 error/trace/tool output、cookie、profile 路径、
  seed、未经白名单的 URL 或任意 JSON dump。

### REPLAY-02 顶部身份与状态

顶部固定回答四件事：

1. 这是什么案例（公开标题）。
2. 使用什么模式（趋势/Brief）。
3. 工作流当前或最终状态（来自 live/final summary，不随选择改变）。
4. 当前页面是只读过程回放。

要求：

- 不默认展示完整 threadId；高级视图可复制短 reference。
- 已选择 checkpoint 时显示独立“正在查看：步骤 N · 名称 · 时间”。
- 未登录主 CTA“开始创作”；已登录主 CTA“用此流程开始创作”或“进入工作台”。
- 不自动复制案例正文或启动工作流；只携带 `source=replay` 和可公开的 mode。
- 移动端标题最多两行，动作进入更多菜单，不挤出主题切换或返回按钮。

### REPLAY-03 阶段导航

- 阶段导航表达：已完成、所选、失败/中断、未到达、无可查看步骤。
- 状态同时使用图标/文本/形状，不能只靠颜色。
- 点击阶段选择该阶段最近一个有业务数据的关键 checkpoint。
- 无关键 checkpoint 时按钮禁用并有可理解说明。
- 移动端阶段条自动把所选项滚入视口；两侧渐隐提示可横滑。
- 键盘采用 roving tabindex：左右键移动阶段，Enter/Space 选择；不使用全局快捷键抢占正文。

### REPLAY-04 关键步骤 manifest 与全部步骤

- 默认 rail 仅显示 `has_business_data=true` 或 `is_decision=true` 的关键步骤。
- 页面显示 `关键步骤 12 / 全部步骤 49`，让用户理解筛选而非误以为数据丢失。
- 已登录用户可切换“全部技术步骤”；公开用户不显示无业务数据的系统 checkpoint。
- 每个 manifest item 只含：
  - 公共 checkpoint ID；
  - step、phase、用户化 agent key；
  - created_at；
  - result kinds；
  - has_business_data / is_decision；
  - 安全 status/error category。
- 分组按用户阶段，不按底层 source；加载更多保持当前选择和 rail 滚动位置。

### REPLAY-05 检查点导航语义与无障碍

- Rail 使用 `<ol>/<li><button>` 或等价原生语义，不在 button 上覆盖 `role=listitem`。
- 当前步骤使用 `aria-current="step"`；数据类型作为文本或可访问标签，不只用圆点。
- 选中后只更新 query（replace），不增加浏览器历史噪音。
- 键盘选择后将焦点移动到结果标题；指针选择保持当前焦点并更新轻量 live region。
- 移动端完整列表使用底部抽屉或全宽折叠区；Escape 关闭并把焦点还给触发按钮。

### REPLAY-06 结果画布与 presenter

每个关键步骤统一四层结构：

1. **这一步做了什么**：一行用户化摘要。
2. **核心产出**：标题、策略、文案、视觉、审核结论、发布结果或分析指标。
3. **为什么重要**：关键依据、风险或下一步影响。
4. **技术详情**：默认折叠，仅认证高级视图可见。

Presenter 映射：

| 内部节点 | 公开名称 | 默认首要内容 |
| --- | --- | --- |
| trend_scout | 趋势洞察 | 热点、机会、受众信号 |
| content_strategist | 内容策略 | 选题、角度、关键要点 |
| brief_analyzer / brief_gate | Brief 理解 | 品牌、产品、约束、待确认项 |
| copywriter / creator agents | 内容创作 | 标题、正文摘要、标签、版本选择 |
| visual_designer / shooting_planner | 视觉与拍摄 | 构图、镜头、色彩、图片计划 |
| review_gate / revise_content | 质量审核 | 结论、修改点、风险 |
| publisher / engagement | 发布结果 | 成功/失败类别、公开链接、后续动作 |
| analyst / Ripple | 表现分析 | 核心指标、置信度、风险和建议 |

要求：

- 所有 status、verdict、phase、score source 先经过 typed presenter 和 i18n map。
- 禁止在公开模板中 `JSON.stringify` 任意后端对象。
- `auth_failed` 映射为“发布授权已失效”；公开用户看到解释，认证用户可进入设置修复。
- 长文案默认展示有意义摘要，提供“展开全文”和“复制”；复制反馈不遮挡正文。
- 空字段不渲染空卡；未知字段只进入开发日志，不直接显示给用户。
- 预测值明确标记“预测”，实际值明确标记“实际”，两者不能共享模糊指标名。

### REPLAY-07 连续浏览（P0）

- 结果底部固定提供：`上一个关键步骤`、`当前 12 / 18`、`下一个关键步骤`。
- 首尾按钮正确 disabled，并说明已到起点/终点。
- 默认跳过无业务数据 checkpoint；高级视图开启后可按全部步骤浏览。
- 移动端选择下一步后把结果标题滚到 sticky header 下方，不使用平滑滚动于 reduced-motion。
- 支持 rail 内 Home/End 到首/尾关键步骤；不占用输入框按键。

### REPLAY-08 引导式播放（P2 实验）

- P0 不实现自动播放，不在进入页面后自动移动选择。
- P2 可实验“讲解模式”：手动开始、默认暂停、每步至少 6 秒、可暂停/前后跳转。
- 播放只切换 checkpoint，不朗读或动画展开正文；用户操作后立即暂停。
- reduced-motion 不禁止播放逻辑，但关闭位移动画和脉冲。
- 只有关键步骤 manifest 与性能预算稳定后才进入开发。

### REPLAY-09 稳定最终摘要

- 摘要数据源优先级：公共 final summary DTO → 最新有效最终 checkpoint → live state。
- 历史 checkpoint 切换不得改变最终摘要。
- 至少支持：最终标题/主题、品牌/产品、发布状态/链接、实际指标、预测指标、最终错误类别。
- 尚未生成结果时明确写“尚未生成”，不使用中间步骤冒充最终结果。
- 桌面摘要在中心结果宽度 ≥ 640px 时作为右栏；否则移到结果后。
- 移动端默认显示一行摘要和展开按钮，不在结果之前占据首屏。

### REPLAY-10 错误与部分数据

| 状态 | 表现 | 用户动作 |
| --- | --- | --- |
| manifest + detail 加载中 | 保留工作流身份，结果结构 skeleton | 等待 |
| live 成功、manifest 加载中 | 显示真实状态，步骤区局部加载 | 等待/重试 |
| live 失败、manifest 成功 | 继续回放，标明最新状态暂不可用 | 重试状态 |
| manifest 失败、live 成功 | 不显示“暂无步骤” | 重试历史 |
| selected detail 失败 | 保留步骤上下文和相邻导航 | 重试本步/下一步 |
| checkpoint 无业务数据 | 高级视图说明“系统步骤，无公开产出” | 上/下一关键步骤 |
| checkpoint query 失效 | 回退最近有效关键步骤并提示一次 | 正常浏览 |
| 案例私有/下线 | 专用状态，不泄露是否存在更多内部数据 | 返回公开案例 |
| thread 不存在/已删除 | 专用 404 | 返回案例列表 |
| 发布/授权失败 | 用户化错误类别和安全说明 | 公开：开始创作；认证：设置/工作台 |

### REPLAY-11 返回、分享与来源

- `returnTo` 只接受站内 allowlist 路径；`source` 只作为分类，不与返回路径复用。
- 从 Showcase 返回时恢复筛选、已加载数量、滚动和触发卡片焦点。
- 从 Dashboard/History/Review 进入时返回对应 thread 页面。
- 直接访问 fallback 到 Showcase。
- 支持复制“当前关键步骤链接”和“整个案例链接”；两者文案与埋点区分。
- 分享 URL 使用公共 ID，不包含账号 UUID、完整内部 threadId 或正文。
- 可选 P1：公共案例增加安全的 Open Graph 标题、摘要和预览图。

### REPLAY-12 转化动作

- 未登录：`开始我的内容工作流` → `/login?redirect=/start&source=replay`。
- 已登录：
  - 主 CTA `开始新创作` → `/start?source=replay&mode=<public mode>`；
  - 次动作 `进入此工作流管控台` 仅当前用户有权限时显示。
- CTA 在顶部和内容底部各可出现一次，但同一视口只有一个高权重主动作。
- 不复制公开案例正文、品牌或账号信息到新工作流；P2 若做模板化需另立隐私/版权 PRD。

### REPLAY-13 Replay 性能要求

当前样本首批 20 checkpoints 原始响应约 1,016,146 bytes。本轮目标：

- manifest 原始 JSON ≤ 100KB / 20 项；网络压缩后目标 ≤ 40KB。
- 首个 selected detail 原始 JSON 目标 ≤ 250KB；超出时拆分大媒体/长列表。
- 冷启动首个真实结果 p75 ≤ 2.5s；warm session cache ≤ 500ms。
- 选中已缓存步骤的交互到结果更新 ≤ 100ms；未缓存步骤接口成功后渲染 ≤ 300ms。
- 初始并发最多：live summary、manifest、selected detail 三个请求。
- 只在网络良好且浏览器 idle 时预取下一个关键步骤；Save-Data/慢网不预取。
- 路由离开、thread 变化和快速切换时取消或忽略 stale detail 响应。
- session cache 继续 ≤ 30 秒，按 publicId + checkpointId 版本化并限制总容量。

---

## 10. 公共数据与 API 契约

### DATA-01 显式公开案例模型

工作流增加或通过独立表维护：

```text
showcase_visibility: private | unlisted | public
public_id: opaque stable id
featured_rank: nullable integer
public_title: localized/sanitized title
public_summary: localized/sanitized summary
approved_at / approved_by
redaction_version
```

- 默认 `private`，不能因创建工作流自动公开。
- `unlisted` 仅持有链接可见，不进入 Showcase 列表。
- `public` 才可进入列表，并在变更后重新执行脱敏校验。
- 下线后公共接口统一返回安全状态，不泄露内部存在性。

### DATA-02 推荐公共只读接口

```text
GET /api/public/showcase/cases
GET /api/public/showcase/cases/:publicId
GET /api/public/replays/:publicId/manifest
GET /api/public/replays/:publicId/checkpoints/:checkpointPublicId
GET /api/public/replays/:publicId/final-summary
```

接口要求：

- 只返回 allowlist DTO，不直接序列化完整 workflow/checkpoint state。
- 支持 ETag / Last-Modified；列表与 manifest 可短时 public cache，详情按隐私策略缓存。
- 老 `/workflow/*` 接口保留一个版本周期；前端迁移后评估加认证或限制公共字段。
- DTO 需要后端 contract tests 与前端类型同步测试。

### DATA-03 ShowcaseCaseSummary DTO

允许字段：

- public_id、public_title、public_summary；
- mode、public_status、public_phase、progress（仅有意义时）；
- updated_at；
- evidence kind + sanitized preview；
- key_step_count、has_final_summary、has_publish_result；
- approved public media URL（可选）。

禁止字段：account_id、internal thread_id、raw error、next nodes、tool data、cookie/profile、
未批准正文、内部模型/seed/config。

### DATA-04 Replay manifest/detail DTO

- Manifest 只返回导航 metadata，不包含大正文、完整分析数组或媒体二进制。
- Detail 按 result kind 使用 typed union，未知类型不透传任意对象。
- Error 只返回枚举 category + public message key，不返回 stack、provider message 或 token。
- Final summary 为独立稳定 DTO，避免前端为得到摘要自动加载全部 checkpoints。

### DATA-05 脱敏与审核

- 服务端 allowlist 是唯一可信边界，前端隐藏不算脱敏。
- 自动扫描 URL、邮箱、手机号、cookie/token 形状、账号 UUID、文件路径和 provider 错误。
- 公共媒体必须来自允许域名或受控代理，并移除 EXIF/私有参数。
- 增加“公开预览”后台能力前，至少提供 CLI/管理接口确认和撤销公开。
- 审核日志记录 publicId、版本和操作者，不记录敏感正文到埋点。

---

## 11. 视觉、排版与交互系统

### 11.1 排版预算

| 用途 | 最小字号 | 建议字号 |
| --- | ---: | ---: |
| 页面主标题 | 28px mobile / 36px desktop | 32 / 44px |
| 区域标题 | 20px | 24px |
| 卡片标题 | 16px | 18px |
| 正文/结果 | 14px | 14–16px |
| 元信息/标签 | 12px | 12–13px |
| 纯装饰字样 | 10px | 仅 aria-hidden，不承载信息 |

- P0 消除两页用户可见 `text-[9px]`、`text-[10px]`；11px 只允许非关键短标签，目标归零。
- 中文正文不使用大写字母式宽 tracking；行高 ≥ 1.5，长文最大宽度 72ch。
- 通过分组和留白表达次级信息，不通过不断缩小和降低对比度表达。

### 11.2 表面与层级

- 页面同时最多三层 surface：page → workspace → content card。
- 相邻玻璃卡不得仅靠极淡阴影区分；使用明确边框、背景或间距。
- 主结果区对比度最高，背景装饰对比度最低。
- 浅色/暗色均使用 token，不为每个组件新增全局 wildcard dark selector。

### 11.3 动效预算

- 每页持续循环动画 ≤ 2 组；首屏业务内容不等待动画 ready。
- 按钮/筛选/选择反馈 120–180ms；布局大幅位移避免超过 240ms。
- 只动画 transform/opacity；不对大面积 blur、box-shadow 或颜色树做持续动画。
- reduced-motion：取消持续轨道、脉冲、扫光、平滑滚动和带 delay 的入场动画。
- 移动端默认静态背景；桌面装饰在首个真实内容绘制后启动。

### 11.4 暗黑模式

- 所有信息层级在 light/dark 下语义一致；不能靠亮色模式专属阴影表达选中。
- 文本、状态、边框和图表达到 WCAG AA 对比目标。
- 主题切换继续同步应用并使用 `theme-switching` guard，不引入全页慢过渡。
- 公共媒体、色板和图表在暗色背景下不得出现白底闪烁。

---

## 12. 响应式规则

| 宽度 | Showcase | Replay |
| --- | --- | --- |
| 320–479 | 单列；Hero + mini case；chips 横滑 | 单列；阶段横滑；checkpoint 抽屉；结果优先 |
| 480–767 | 单列宽卡；工具栏分两行 | 单列；结果 + 折叠摘要 |
| 768–1023 | 两列案例；Hero 可双栏 | 两列：结果 + 摘要；checkpoint 抽屉 |
| 1024–1279 | 两列案例；完整工具栏 | 两列：rail + 结果；摘要移到下方 |
| ≥1280 | Hero 7/5；两列案例 | 三列：rail 220–240 / result ≥640 / summary 260–300 |

硬要求：

- 在 320、390、768、1024、1280、1440px 下无页面级水平滚动。
- 触控目标 ≥ 44×44px，相邻高频目标间距 ≥ 8px。
- Sticky header、阶段条、底部动作不得遮挡内容或 safe area。
- 200% zoom 下主动作和结果仍可访问，不依赖 hover。
- 容器查询可用于结果组件，但不得替代页面级阅读顺序。

---

## 13. 无障碍与国际化

### 13.1 语义与键盘

- 页面有唯一 `h1`，区域按 `h2/h3` 顺序；提供跳到案例/结果的 skip link。
- 卡片为链接；筛选为 button/radio/select；阶段导航使用一致的 tab/button 模型。
- checkpoint 使用列表 + 原生 button，保留按钮语义。
- 抽屉有 dialog 语义、焦点圈定、Escape 关闭和焦点恢复。
- 选择步骤后 live region 只播报“已选择第 N 步：名称”，不朗读整个结果。
- 所有 icon-only 按钮有可翻译 aria-label 和可见 focus ring。

### 13.2 感知

- 状态不只靠颜色；同时使用图标、文案和形状。
- 正文、控件和状态满足 AA；重要正文目标 4.5:1。
- 支持 `prefers-reduced-motion`、`prefers-contrast` 基础策略和浏览器字体放大。
- 错误不只 Toast；可恢复问题保留在页面内。

### 13.3 国际化

- 所有用户可见字符串进入 `zh-CN.json` 与 `en.json`。
- 去除 `views`、`likes`、`viral`、raw status 等硬编码英文。
- 日期、数字、百分比、紧凑数值统一用 locale formatter；不在组件各自实现不同规则。
- 中文、英文 30% 文案膨胀下主标题、状态、CTA 不截断。
- 内部 agent key 永不作为 fallback 用户文案；未知 key 使用本地化“未知步骤”。

### 13.4 自动化门槛

- 新增公共路由 Playwright + axe 检查，阻断 serious/critical violations。
- 键盘路径至少覆盖：导航 → CTA → 筛选 → 案例 → 阶段 → checkpoint → 结果 → 分享 → 返回。
- 读屏手动验收至少覆盖一个成功案例、一个部分失败案例和空/下线案例。

---

## 14. 埋点、漏斗与性能观测

### 14.1 现有事件保留

- `showcase_view`
- `showcase_filter_change`
- `showcase_workflow_open`
- `showcase_detail_retry`
- `showcase_primary_cta_click`
- `replay_view`
- `replay_checkpoint_select`
- `replay_phase_select`
- `replay_checkpoint_link_copy`
- `replay_back`
- `replay_primary_cta_click`
- `replay_load_error`

### 14.2 新增事件

| 事件 | 触发 |
| --- | --- |
| `showcase_case_impression` | 卡片 ≥50% 可见并持续 ≥1s，每会话/案例一次 |
| `showcase_featured_open` | 打开精选案例 |
| `replay_first_result_visible` | 首个真实结果进入视口，每次 page view 一次 |
| `replay_view_mode_change` | 关键步骤/全部步骤切换 |
| `replay_step_navigate` | 上一步/下一步/rail/phase，记录 method |
| `replay_result_expand` | 展开全文、依据、技术详情 |
| `replay_result_copy` | 复制标题/正文/摘要，记录 result kind |
| `replay_share` | 分享整个案例或当前步骤 |
| `replay_cta_click` | 登录/开始创作/工作台，记录 auth state |

### 14.3 允许属性

- source、viewport、auth_state、mode、public_status、phase、result_kind、method；
- cached、partial、error_category；
- latency_bucket、payload_bucket、experiment_variant；
- event_version。

禁止属性：正文、标题、品牌/产品、publicId/internal ID、account ID、checkpoint ID、URL query
原文、错误原文、token/cookie/provider 响应。

### 14.4 漏斗

```text
showcase_view
  → showcase_case_impression
  → showcase_workflow_open
  → replay_view
  → replay_first_result_visible
  → replay_step_navigate / replay_result_expand
  → replay_cta_click
  → login_success / workflow_start（由对应页面既有事件承接）
```

### 14.5 性能观测

- 记录 Showcase first-case-visible、Replay first-result-visible、checkpoint-select-to-render。
- 记录 cache hit、manifest/detail payload bucket 和错误类别，不记录 ID。
- 上线前确认 `VITE_TELEMETRY_ENDPOINT` 或 host adapter 真实接收事件；仅 dispatch 浏览器事件不算完成。
- 建立按 mobile/desktop、cold/warm、trend/brief 的仪表盘。

---

## 15. 技术架构与组件拆分

### 15.1 Showcase 建议拆分

```text
Showcase.vue                    路由编排、页面级状态、SEO
components/showcase/
  ShowcaseNav.vue              公共导航与认证 CTA
  ShowcaseHero.vue             价值主张 + 精选 mini case
  ShowcaseCaseToolbar.vue      筛选、搜索、排序、结果数
  ShowcaseCaseCard.vue         统一案例 presenter
  ShowcaseCaseGrid.vue         列表/分页/局部状态
  ShowcaseProcessExplainer.vue 六步辅助说明
composables/useShowcaseCases.ts 查询、URL、cache、返回上下文、请求队列
presenters/showcaseCase.ts      DTO → 用户化 view model
```

目标：`Showcase.vue` 降到约 350 行以内；装饰 CSS 可保留 route scoped 文件，但不与查询逻辑混写。

### 15.2 Replay 建议拆分

```text
WorkflowReplay.vue             路由编排与状态组合
components/replay/
  ReplayHeader.vue             身份、状态、返回、CTA、分享
  ReplayPhaseNav.vue           阶段导航
  ReplayCheckpointRail.vue     桌面关键步骤 rail
  ReplayCheckpointDrawer.vue   移动/中屏步骤选择
  ReplayResultCanvas.vue       结果标题、presenter、loading/error
  ReplaySequenceControls.vue   上一/下一关键步骤
  ReplayFinalSummary.vue       稳定最终摘要
  ReplayTechnicalDetails.vue   认证高级技术层
composables/useReplayManifest.ts manifest/detail/cache/prefetch
presenters/replayResult.ts      typed result union → view model
presenters/replayError.ts       error/status → 用户化文案与动作
```

目标：`WorkflowReplay.vue` 降到约 400 行以内；已有 `AgentResult*` 可逐个迁移，不要求一次重写全部。

### 15.3 状态边界

- `workflowStore.liveWorkflowState` 继续表示实时/最终状态。
- 新增公开 replay store slice 或独立 composable：manifest、detailById、selectedId、detailLoading/error。
- summary 和 detail 分开缓存；manifest 刷新不清除仍有效的 selected detail。
- 所有请求带 publicId/checkpointId stale guard；路由切换取消 AbortController。
- UI 只消费 presenter view model，不在模板读取任意 `as any` 深层字段。

### 15.4 共享基础

按至少三个真实复用点再抽取：

- `PublicPrimaryAction`：未登录/已登录分流。
- `AsyncStatePanel`：加载、部分、错误、空态和重试。
- `PublicStatusBadge`：公共状态枚举与图标。
- locale number/date formatter。

不要先建立大型设计系统；以两页真实复用为边界。

---

## 16. 实施计划与 PR 拆分

### 16.1 开工前治理（PR-0 / 0.5–1 人日）

- 将 11 个重叠 `07-15-*` Showcase/Replay 任务标注为已纳入本 PRD、暂停或归档。
- 记录当前 320/390/768/1024/1440 light/dark 截图和请求/payload 基线。
- 固化真实数据的脱敏 fixtures：成功、进行中、发布失败、部分数据、无 checkpoint、下线。
- 确认公共案例负责人和首批 public allowlist。

完成标准：只有本总任务及其子任务继续修改 Showcase/Replay。

### 16.2 PR-1：公共数据契约（后端 2–3 人日）

- 增加 public visibility/publicId/脱敏规则。
- 增加 cases、manifest、checkpoint detail、final summary 只读接口。
- 增加 contract、权限、下线、字段 allowlist、payload budget 测试。
- 保持旧接口兼容，不先改 UI。

完成标准：公开接口不返回禁止字段；manifest 样本 ≤ 100KB/20 项。

### 16.3 PR-2：Presenter 与共享基础（前端 1.5–2.5 人日）

- 新增公共 DTO 类型、API client、status/error/result presenter。
- 统一 locale formatter、公共 CTA、状态面板。
- 去除公开 UI 的 raw status、JSON fallback 和硬编码英文。
- 增加 presenter 单元测试。

完成标准：未知后端字段不会直接进入 DOM。

### 16.4 PR-3：Showcase UX V2（前端 3–4 人日）

- 拆分 route component。
- 实现结果优先 Hero、精选 mini case、公共案例工具栏、统一卡片和辅助流程说明。
- 迁移现有 cache/query/返回上下文，不回退已有行为。
- 完成移动、暗色、reduced-motion、空/错/部分状态和埋点。

完成标准：390×844 前 620px 出现真实案例标题；首个案例 cold p75 ≤2.5s。

### 16.5 PR-4：Replay 数据加载与导航（前后端 2–3 人日）

- 前端切换 manifest + selected detail 模型。
- 关键步骤/全部步骤、阶段选择、上一/下一、深链、缓存和 stale guard。
- 保留 live state 与 stable final summary 分离。
- payload 与首次结果性能测试。

完成标准：默认不下载 20 个完整 checkpoint；首次只加载 manifest + 选中详情。

### 16.6 PR-5：Replay 结果体验与转化（前端 3–4 人日）

- 实现 ReplayHeader、ResultCanvas、SequenceControls、FinalSummary、移动抽屉。
- 按 presenter 四层结构迁移 AgentResult 组件。
- 增加未登录 CTA、已登录工作台动作、分享整个案例/当前步骤。
- 技术详情只在认证高级视图出现。

完成标准：公开页面无 raw 技术字段；移动首屏看到结果标题和下一步入口。

### 16.7 PR-6：质量、埋点与收尾（1.5–2.5 人日）

- 补 Playwright/axe、截图、键盘、深链、真实服务 smoke。
- 接通漏斗与性能事件，建立 7 天基线仪表盘。
- 处理 P0/P1 验收问题，删除已无引用的 legacy UI/CSS。
- 更新 frontend/backend spec 和任务记录。

完成标准：全部质量门槛通过，旧 UI 可安全回滚一个版本。

### 16.8 总投入与依赖

| 工作包 | 前端 | 后端 | QA/设计 | 依赖 |
| --- | ---: | ---: | ---: | --- |
| 治理与基线 | 0.5 | 0 | 0.5 | 无 |
| 公共契约 | 0.5 | 2–3 | 0.5 | 公共案例决策 |
| Presenter/基础 | 1.5–2.5 | 0 | 0.5 | DTO 草案 |
| Showcase | 3–4 | 0–0.5 | 1 | PR-1/2 |
| Replay 数据/导航 | 2–3 | 1–2 | 1 | PR-1/2 |
| Replay 结果/转化 | 3–4 | 0–0.5 | 1 | PR-4 |
| QA/埋点/收尾 | 1.5–2.5 | 0.5 | 1–2 | 全部 |

总计约 15–22 人日。若不做公共接口和 manifest/detail 拆分，开发会缩短，但不能满足本 PRD
的隐私与首次 Replay 性能硬门槛，因此不建议作为正式 V2 方案。

---

## 17. 测试与验收矩阵

### 17.1 后端/契约

- public/private/unlisted 可见性。
- publicId 不暴露 internal ID。
- DTO allowlist 与敏感字段扫描。
- manifest pagination、detail not found、下线和版本兼容。
- final summary 稳定性。
- 20 项 manifest payload budget。

### 17.2 前端单元与组件

- Showcase query 归一化、筛选、搜索、推荐 fallback、cache/refresh、返回恢复。
- Case presenter 对 trend/brief/completed/failed/partial/unknown 的映射。
- Replay default selection、关键/全部过滤、阶段 → 最近有效步骤、上一/下一边界。
- detail request dedupe、stale guard、cache、失败重试。
- raw status/error/unknown object 不进入公开 DOM。
- CTA 未登录/已登录路由。
- i18n key 双语存在。

### 17.3 E2E 路径

1. 未登录 Showcase → 精选案例 → Replay → 下一关键步骤 → 开始创作 → 登录 redirect。
2. Showcase 筛选/滚动 → Replay → 返回 → 恢复列表和焦点。
3. Replay deep link checkpoint → 刷新 → 恢复同一步。
4. 已登录 Replay → 全部技术步骤 → 返回 Dashboard/History。
5. live 失败 + history 成功；history 失败 + live 成功；detail 单步失败重试。
6. 私有/下线/删除/无 checkpoint/无业务数据。
7. 分享整个案例与当前步骤。

### 17.4 视觉与响应式

矩阵：

- 宽度：320、390、768、1024、1280、1440。
- 主题：light、dark。
- 动效：normal、reduced-motion。
- 语言：zh-CN、en。
- 数据：完整、长标题、空、部分失败、50 checkpoints。

检查：无横向溢出、无截断主动作、首屏证据/结果位置、sticky 不遮挡、200% zoom。

### 17.5 无障碍

- axe serious/critical = 0。
- 完整键盘路径、可见 focus、抽屉焦点恢复。
- 读屏阶段/checkpoint/状态播报不重复。
- 状态在灰度截图中仍可区分。

### 17.6 性能

- Lighthouse/Web Vitals：LCP、CLS、INP。
- Showcase first-case-visible。
- Replay first-result-visible、select-to-render。
- cases/manifest/detail payload 和请求数。
- slow 4G、Save-Data、cache hit/miss。
- 快速连续 checkpoint 选择的竞态和取消。

### 17.7 质量命令

```bash
npm -C frontend run type-check
npm -C frontend run test:run
npm -C frontend run build
python -m pytest -q
python -m mypy backend
ruff check backend tests
ruff format --check .
git diff --check
```

### 17.8 本次实现验收证据

以下命令已在基线分支 `feat/showcase-replay-ux-v2` 运行并通过：

- `python -m pytest -q`：1657 passed，2 个既有 warning。
- `python -m mypy backend`：169 source files 无问题。
- `ruff check backend tests`、`ruff format --check backend tests`：通过。
- `npm -C frontend run test:run`：42 files、539 tests passed。
- `npm -C frontend run type-check`、`npm -C frontend run build`：通过；仅保留既有 chunk/dynamic-import warning。
- OpenAPI 已包含 `/api/public/showcase/cases`、详情、manifest、checkpoint detail、final summary 五个只读路由。
- `tests/unit/api/test_public_showcase.py` 覆盖 allowlist 脱敏、关键步骤去重、private 排除、manifest 和详情安全投影。

本次验收延伸 `feat/showcase-replay-acceptance` 已补齐并通过：

- `python -m pytest -q`：1664 passed，3 个既有 warning；`python -m mypy backend`、`ruff check backend tests`、`ruff format --check` 和 `git diff --check` 通过。
- `npm -C frontend run test:run`：42 files、540 tests passed；`npm -C frontend run type-check` 和 `npm -C frontend run build` 通过。
- 增加认证治理接口：公开审批/精选/展示文案更新、撤销及 `approved_at/approved_by/redaction_version` 持久化；默认仍为 private。
- 增加脱敏状态 fixture：成功、进行中、发布失败、部分产出、无 checkpoint、离线、下线；覆盖 PII、URL 和 CSS palette 白名单。
- Manifest 增加 key/all 计数、offset/limit/has_more、ETag/Last-Modified；Replay 增加 30 秒详情缓存、stale guard、阶段 roving tabindex、深链分页和加载更多失败重试。
- Showcase 回放入口改为可复制/新标签使用的真实链接，公开页改为直接引入 auth store，避免公共入口加载无关 store barrel。
- 当前分支 OpenAPI 已包含上述五个只读路由及两个认证治理路由；公开案例仍为 0，未在无 owner 授权时发布真实案例。
- 部署后浏览器 smoke 已覆盖真实空态接口与脱敏 mock 案例：320/390/768/1024/1280/1440px × light/dark 共 12 组合；检查无页面级横向滚动、主题 class、390px reduced-motion、Showcase/Replay 首屏、真实回放链接和阶段 ArrowRight 键盘导航均通过。390px dark 截图复核确认主题按钮不再遮挡主 CTA。
- 线上 smoke：`/api/system/health` 正常，Postgres/Ripple 正常；公开列表返回 `total=0` 且无私有案例泄露；列表 ETag 条件请求返回 `304`；OpenAPI 暴露五个只读路由和两个认证治理路由。
- 埋点接收：`POST /api/public/telemetry` 已接入同源默认地址，服务端执行事件/分类白名单、120 次/分钟来源限流、30 天保留和匿名降级；`GET /api/public/admin/telemetry/summary` 只返回聚合数量与 p50/p75 耗时，供目标监控面板接入。
- 目标部署 `main@aed6414b` 已执行 `python scripts/acceptance/public_ux_audit.py --base-url http://127.0.0.1:8889 --output /tmp/public-ux-audit-final.json`：真实空态 Showcase 1 页 + 合成无敏感数据 fixture 的 Showcase/Replay 96 页，共 97 页记录；无失败、无页面级横向溢出、阶段 ArrowRight 键盘导航通过，axe serious/critical violations 为 0。
- 同次审计覆盖 320/390/768/1024/1280/1440px、zh-CN/en、light/dark、normal/reduced-motion；wall-clock p50/p75/p95 为 631.55/885.34/1327.74ms，CLS p50/p75/p95 均为 0。该耗时只代表当前部署 + 合成 fixture 的导航到首个结果可见，不替代真实公开案例的 cold/warm、慢 4G、Save-Data 或 Lighthouse 证据。
- 新增可重复审计入口 `scripts/acceptance/public_ux_audit.py` 与 `@axe-core/playwright` 依赖；脚本默认保留 live private-by-default 检查和 96 页矩阵，支持 `--base-url`、`--output`、`--screenshot-dir` 和快速 smoke 的 `--max-combinations`。

### 17.9 性能与监控补齐（本轮）

- Replay 步骤选择先更新结果状态并开始 checkpoint 读取，再等待 URL deep-link 同步；这样慢路由更新不会阻塞用户先看到已返回的结果。新增回归测试覆盖“URL 更新未完成时结果已渲染”。
- 审计脚本新增 Largest Contentful Paint（LCP）观察器、warm reload、cached select-to-render 计时和 100ms 缓存回选门槛；新增 `--network-profile slow-4g` 与 `--save-data` 代表性采样入口。默认 online 全矩阵行为不变。
- Settings 新增认证后的“公开页体验监控”面板，消费现有匿名聚合 summary 接口，支持 1/7/14/30 天、取消过期请求、失败重试和 p50/p75 展示；面板不渲染原始案例 ID、账号、正文或错误原文。
- 本轮改动的前端全量回归已通过：43 个测试文件、544 个测试；新增面板 3 个测试和 Replay 性能回归测试 1 个。生产构建及发布后审计仍需在合并部署后记录最终证据。

以下项目仍需要真实案例目标环境或人工证据，不把合成 fixture 的自动化结果冒充完成：真实公共案例
owner 授权后的 390×844/320–1440px 双主题截图矩阵、真实案例 Lighthouse/Web Vitals、慢
4G/Save-Data 采样、监控面板基线接入、灰度回滚演练，以及中文/英文 Hero、CTA、错误与状态文案
的业务确认。线上健康、私有空态、缓存条件请求、OpenAPI、自动化响应式/键盘矩阵和 live 空态/mock
axe smoke 已完成。

---

## 18. Definition of Ready

- [ ] 旧 11 个重叠任务已完成治理，不再并行修改同一页面。
- [ ] 首批公开案例 owner、授权和下线流程已确认。
- [ ] 公共 DTO allowlist 和禁止字段已评审。
- [ ] 中文/英文 Hero、CTA、错误与状态文案已确认。
- [x] 成功/失败/部分/空/长内容 fixtures 已准备。
- [ ] 埋点接收端和基线仪表盘可用。
- [ ] PR-1 至 PR-6 负责人和依赖顺序明确。

### 18.1 PR 拆分、角色 Owner 与依赖

具体姓名由项目负责人填入发布单；在姓名未确认前，角色 Owner 不能视为业务签字完成。

| PR | 交付物 | 角色 Owner | 前置依赖 | 发布门槛 |
|---|---|---|---|---|
| PR-1 | 公共 DTO、脱敏、private-by-default 和治理 API | Backend/API owner | DTO allowlist 评审 | 禁止字段测试、OpenAPI、未授权 smoke |
| PR-2 | Showcase V2 展示、筛选、空态和回放入口 | Frontend public-surface owner | PR-1 | 320–1440px、双语、主题、键盘、axe |
| PR-3 | Replay V2 manifest/detail、缓存、深链和结果呈现 | Frontend replay owner | PR-1 | 首结果、步骤切换、竞态取消、响应式 |
| PR-4 | 匿名 telemetry 接收、聚合查询和基线面板 | Backend observability owner + Settings UI owner | PR-1、事件白名单评审 | 不含 ID/内容、p50/p75、认证保护、失败恢复 |
| PR-5 | 自动化矩阵、视觉审查、性能和无障碍验收 | QA/Design owner | PR-2、PR-3、PR-4 | 合成门禁全绿；真实案例证据齐全 |
| PR-6 | 灰度、观察、回滚和生产部署 | DevOps/release owner | PR-5、owner 授权、文案签字 | health、ETag、告警、回滚演练 |

---

## 19. Definition of Done

### 19.1 Showcase

- [x] 页面默认只展示明确公开的案例，不再暴露全部内部工作流。
- [ ] 390×844 前 620px 出现真实案例标题和回放入口（合成 fixture 自动检查通过，仍需目标环境真实公开案例截图验收）。
- [x] Hero 只有一个主 CTA；登录/已登录分流正确。
- [x] 案例卡无 `trend`、`P1`、`viral`、硬编码 views/likes 等未解释内部表达。
- [x] 筛选、搜索、排序、URL、返回滚动与焦点恢复可用。
- [x] 加载、cache refresh、列表失败、无公开案例、筛选空、预览失败可区分和恢复。
- [ ] 首个案例 cold p75 ≤2.5s，warm ≤500ms，CLS ≤0.1（合成 fixture wall-clock p75 885.34ms、CLS p75 0；真实案例 cold/warm 仍待采样）。

### 19.2 Replay

- [x] 默认只显示关键步骤；认证用户可查看全部技术步骤。
- [x] manifest/detail 拆分生效，20 项 manifest ≤100KB raw（契约限制与按需 detail 已实现，需线上 payload 采样确认）。
- [x] 公开 DOM/响应无禁止字段、raw error、JSON fallback 或完整内部 ID。
- [x] 阶段、rail、上一/下一和 checkpoint deep link 一致。
- [x] 每个结果回答“做了什么、产出、为什么重要”，技术详情默认折叠。
- [x] 最终摘要不随历史选择变化；预测与实际明确区分。
- [x] 未登录和已登录用户均有正确主 CTA。
- [ ] 390×844 首屏可见结果标题；无页面级横向滚动（合成 fixture 自动检查通过，仍需目标环境真实公开案例截图验收）。
- [ ] first-result cold p75 ≤2.5s，warm ≤500ms，cached select-to-render ≤100ms（合成 fixture wall-clock p75 885.34ms；真实案例与缓存选择采样仍待补齐）。

### 19.3 全局质量

- [x] 用户可见正文 ≥14px、元信息 ≥12px；9/10px 信息文本归零（新 V2 页面）。
- [ ] light/dark、zh/en、normal/reduced-motion、320–1440px 通过视觉验收（96 页自动矩阵、无溢出和代表性截图已完成；真实案例完整截图矩阵仍待签字）。
- [ ] 主要交互键盘可完成；axe serious/critical = 0（live 空态 + 96 页合成 fixture 目标审计为 0；真实公开案例目标审计仍待补齐）。
- [x] 所有新文案双语，日期/数字/百分比 locale 化。
- [x] 埋点形成完整漏斗且不上传 ID、内容或错误原文。
- [x] 自动化、构建、类型、lint、diff、真实后端 smoke 以及 live 空态/mock 的响应式、键盘、axe 目标审计全部通过（真实案例视觉/性能与业务授权门槛仍按上方保留）。
- [x] spec、API 文档、任务和回滚说明已更新。

---

## 20. 发布、观察与回滚

### 20.1 发布顺序

1. 先部署 additive public API，旧 UI 不切换。
2. 采集旧 UI 7 天基线，同时用内部 query/feature config 验收 V2。
3. 切换 Showcase V2，观察 24 小时错误、性能和公共字段。
4. 切换 Replay V2，观察 first-result、payload、错误和 CTA。
5. 7 天后评估效果指标；稳定后删除 legacy API/UI 和临时 flag。

### 20.2 监控告警

- public API 4xx/5xx、字段脱敏失败、manifest/detail p75/p95。
- Showcase first-case-visible、Replay first-result-visible、JS error、retry rate。
- 公共案例数异常变为 0、未授权案例被返回、下线仍可访问。
- CTA redirect 失败、分享链接 404、dark/reduced 关键回归。

### 20.3 回滚

- API 为 additive，前端可单独回滚到旧接口。
- 旧 UI 保留一个版本，不与新 presenter/store 共享不可逆状态。
- 发生隐私/字段事故时优先关闭公共案例接口并显示安全维护态，而不是继续展示缓存正文。
- session cache key 带版本，回滚后不会读取不兼容 V2 数据。

---

## 21. 风险与对策

| 风险 | 影响 | 对策 |
| --- | --- | --- |
| 旧任务继续并行 | 同文件冲突、视觉反复 | PR-0 强制任务收敛；本 PRD 为唯一总入口 |
| 公共案例授权不清 | 隐私与信任风险 | 默认 private、服务端 allowlist、审核/撤销日志 |
| API 拆分扩大范围 | 延迟前端交付 | additive API 先行；明确 manifest/detail 最小字段 |
| Route component 拆分过度 | 组件跳转复杂 | 以职责和三个复用点为边界，不建通用大框架 |
| 结果字段异构 | presenter 分支膨胀 | typed result union + unknown 安全降级 + contract tests |
| 真实数据经常缺字段 | 页面空洞 | 状态矩阵、逐字段渲染、稳定 fallback，不伪造内容 |
| 降低装饰被认为品牌弱化 | 视觉争议 | 保留一个核心轨道识别，把品牌放在内容之后和背景层 |
| 数据量低导致指标波动 | 无法判断效果 | 先看方向与定性反馈，性能/质量硬门槛独立验收 |
| 英文文案变长 | CTA/状态截断 | 双语截图矩阵和 30% 膨胀测试 |
| 暗色兼容回归 | 切换慢、对比不足 | token/组件 scoped 样式，禁止 broad class substring selector |

---

## 22. 产品决策记录

### 决策 1：Showcase 不再兼任公开运维看板

公开访客需要案例和结果，不需要内部异常队列。运营状态留在认证工作台；Showcase 只展示
经过授权、可解释、有回放价值的案例。

### 决策 2：公共数据必须是独立契约

前端隐藏字段不是安全边界。公共页面使用独立 DTO、publicId 和 allowlist，避免 UI 被内部
state 结构绑架，并为性能拆分提供清晰接口。

### 决策 3：关键步骤是默认，全部 checkpoint 是高级能力

大多数用户想理解过程，不是审计每个系统 tick。关键步骤降低认知和 payload；认证运营者
仍可进入全部技术步骤，不牺牲审计能力。

### 决策 4：先做顺序浏览，不做默认自动播放

上一/下一关键步骤解决核心叙事问题，成本与可控性优于自动播放。自动播放必须在内容、
性能和无障碍稳定后作为独立实验。

### 决策 5：技术字段不得作为 fallback 文案

未知 agent/status/object 不直接显示。公共体验宁可显示安全的“该步骤暂无可展示详情”，
也不输出 raw key、JSON 或 provider error。

### 决策 6：完成定义从“页面更漂亮”改为“用户路径和指标通过”

每个 PR 都必须关联需求 ID、状态 fixture、响应式截图、性能预算和可执行验收；没有这些证据
的视觉微调不算本 PRD 的完成项。

---

## 23. 后续 P2 机会（不阻塞本轮）

- 引导式播放/讲解模式。
- 已授权案例的视觉缩略图和 Open Graph 预览。
- 关键步骤之间的差异视图（“本步新增/修改了什么”）。
- 公开案例收藏/分享渠道统计。
- 按行业/内容类型的案例集合页。
- 在获得明确授权和版权规则后，将公开案例作为“模板参考”，但不复制正文。

这些机会必须在 P0 公共契约、结果 presenter、性能和漏斗稳定后另立 PRD。
