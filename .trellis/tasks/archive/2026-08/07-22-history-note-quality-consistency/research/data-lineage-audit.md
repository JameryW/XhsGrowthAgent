# 历史笔记与质量评估数据链路审计

审计日期：2026-07-22
范围：`/analytics`、`/evaluation`、历史笔记导入、确定性质量分析、RQGM 评估及相关数据库读取。

## 结论摘要

当前“不一致”不是一个字段格式问题，而是 UI 把不同账号范围、不同样本集合、不同时间语义和两套不可直接比较的评分体系放在了同一个“质量”叙事里。同时存在若干实现缺陷，会把原本可解释的差异放大为真实错误：

1. 质量页选择了某个账号，但工作流列表与趋势仍请求“全部账号”。
2. 数据分析页、质量页和账户质量报告分别读取最多 8/20、100、200、500 或全量历史，且排序/时间窗口不同。
3. 历史表现分析与 RQGM 内容评审都叫“质量分”，但前者由真实互动数据确定性计算，后者由 LLM 对内容做多维评审。
4. 历史笔记 RQGM 结果不持久化；刷新或切换笔记后丢失，重跑可能变化，也没有可追溯的内容快照与评估版本。
5. 历史笔记缺少上下文时会静默使用“母婴”赛道，缺失维度会补 70 分；LLM 超时还会返回 `100/approved/degraded=true`，而当前前端不识别 `degraded`。

因此，优化目标不应是强行让两套分数相等，而应做到：同一查询上下文下原始笔记集合和指标完全一致；不同评分明确标注其问题、范围、输入、版本和时点；不可用结果不得伪装成正常分数。

## 1. 当前数据集合对比

| 位置 | 账号范围 | 数据来源 | 时间范围 | 数量上限 / 可见数量 | 默认排序 |
| --- | --- | --- | --- | --- | --- |
| 数据分析页主帖子表 | `accountsStore.activeAccountId`，无活动账号时回退 `default` | 已完成工作流帖子 + `creator_note_stats` 导入笔记，按 `id` 尝试去重 | daily / weekly / monthly | 后端合并最多 500 篇导入笔记，返回最近 20 篇；前端默认显示 10 篇 | `published_at DESC` |
| 数据分析页“创作者中心历史笔记”表 | 当前活动账号 | `GET /analytics/creator-stats/{account_id}?limit=100` | 已持久化全历史，不受页面 daily/weekly/monthly 选择器控制 | 拉取 100，compact 模式只展示前 8 | `engagement_rate DESC, views DESC` |
| 质量页历史笔记流 | 质量页本地选择账号 | 同一 creator-stats 接口，`limit=200` | 全历史 | 最多 200，未展示 `total`/截断状态 | 接口先按互动率，前端再按 `published_at` 混排 |
| 质量页账户历史分 | 质量页本地选择账号 | `list_all_note_stats` | 完整持久化历史 | 全量 | 聚合计算，无列表排序 |
| 质量页工作流评估列表 | **全部账号**（前端传 `undefined`） | 工作流表 + LangGraph checkpoint 中的 `evaluation_result` | 全历史 | 20/页 | DB 工作流顺序；前端按 `updated_at` 与笔记混排 |
| 质量页 RQGM 趋势 | **全部账号**（前端传 `undefined`） | `evaluator_samples` | 全历史 | 100；DB 当前为 `created_at ASC LIMIT 100`，取得最早 100 条 | 评估创建时间升序 |

### 直接后果

* 同一个账号有 250 篇笔记时，账户质量报告会写“分析 250 篇”，质量页列表最多出现 200 篇，数据分析历史表只拉 100 且只显示 8 篇。
* 数据分析页主表是“本周期内的真实导入笔记 + 工作流帖子”，质量页历史流是“全历史导入笔记 + 全账号工作流评估”；两者本来就不会得到相同记录数。
* 数据分析历史表的前 8 篇是互动率最高的笔记，质量页流的前几篇是最近发布的笔记；即使底层记录相同，用户看到的首屏也不同。
* 质量页账号选择器只约束历史笔记与账户报告，未约束工作流列表、趋势和“已评估”总数，存在跨账号混入。

## 2. 当前评分语义对比

| 评分 | 目标问题 | 输入 | 维度 | 特性 |
| --- | --- | --- | --- | --- |
| 账户历史质量 `analyze_historical_quality` | 这个账号已发布内容的表现信号如何？ | 全量已导入互动指标与标题 | engagement、save_value、title_craft、consistency | 确定性、可重复、全量、发布后 |
| 单篇历史质量 `analyze_note_quality` | 这篇已发布笔记的可观测表现信号如何？ | 单篇互动指标与标题 | 同上，但 consistency 不可用 | 确定性、低置信度、发布后 |
| 工作流 RQGM | 这篇待发布内容是否达到发布门槛？ | 工作流的文案、内容计划、视觉计划、账号上下文 | 9 个加权维度 + bias_check | LLM judge、可配置权重/阈值、发布前 |
| 历史笔记 RQGM | 仅基于已导入内容，对历史笔记做内容评审 | 标题、正文、标签、封面 URL 文本、账号赛道 | 与工作流 RQGM 相同 | LLM judge，但生成侧上下文与真实图像缺失 |

两套分数均使用 0–100，但测量对象不同：历史分析是“发布后的真实表现证据”，RQGM 是“内容与风险的评审判断”。数值不应相等，也不应进入同一条趋势线或共用无限定词的“综合质量分”标签。

## 3. 放大差异的实现缺陷

### 3.1 账号上下文未贯通

* `EvaluationView.loadList` 调用 `getEvaluationList(undefined, ...)`，后端其实已经支持 `account_id`。
* `EvaluationOverview.loadTrend` 调用 `getEvaluationTrend(undefined, 100, ...)`，只在 mount 时加载，不随所选账号刷新。
* `evaluatedTotal` 来自全账号工作流总数，但旁边的 `notes_analyzed` 来自当前账号，两个 KPI 的范围不一致。

### 3.2 隐式截断与排序漂移

* `getCreatorStats` 只有 `limit`，没有 offset/cursor；不同组件自行传 100 或 200。
* `CreatorStatsPanel` compact 表再执行 `notes.slice(0, 8)`，没有“仅展示 8/总数”的明确说明或翻页。
* 账户历史质量绕过列表上限读取全量，这是正确的分析设计，却导致“报告样本数”和“页面可见列表数”不一致。
* Analytics dashboard 注释声称合并“full imported snapshot”，实现仍受 500 条上限约束。

### 3.3 时间字段不是同一个事件

* 历史笔记使用 `published_at`。
* 工作流评估列表使用工作流 `updated_at`，不等于发布时间，也不一定等于评估时间。
* RQGM 趋势使用 `evaluator_samples.created_at`。
* 三种事件被放入一个时间流后，排序看似统一，语义实际不同。

### 3.4 历史笔记 RQGM 不可追溯

* `POST /evaluation/note` 为 thread-less 调用，只返回结果，不写 checkpoint，也没有独立评估记录。
* 前端在切换账号/笔记、刷新页面或重新加载详情时清空 `rqgmResult`。
* 响应没有 `evaluation_id`、内容 hash、导入快照、prompt/model/weights 版本；同一笔记重跑得到不同结果时无法解释。
* 后端返回了账号有效阈值，前端 `evaluateNote` 类型没有保留 `thresholds`，历史笔记组件仍按硬编码 70/50 着色。

### 3.5 缺失输入被伪装成有效判断

* 历史笔记账号没有赛道时，`_build_note_eval_state` 静默回退“母婴”，会污染 audience/reach 等维度。
* 当前模型仅把封面 URL 当文本，无法真正查看图片，但 visual/image_quality 仍进入综合分。
* RQGM 漏返必需维度时，`_build_evaluation_result` 自动补 70 分，而不是标记 `available=false`。
* LLM 60 秒超时时返回 `overall_score=100`、`decision=approved`、`degraded=true`。`EvaluationResult` 前端类型没有 `degraded`，组件会把它当真实通过展示。

### 3.6 身份关联是机会式的

Analytics 通过工作流 `publish_result.post_id` 与历史笔记 `note_id` 相等来去重。若发布结果缺 ID、使用 session ID，或平台同步后的 ID 格式不同，同一篇内容会同时出现为“工作流帖子”和“导入笔记”。系统没有显式 `thread_id -> published_note_id` 关联与匹配状态。

## 4. 刷新与数据时点

* Creator Center 导入在后端以事务方式写入账户与笔记快照，这是现有正确基础。
* 各页面随后分别请求 dashboard、creator stats、账户质量和评估列表，没有共同 `snapshot_id/as_of`。
* Analytics 刷新失败时会保留旧 store 数据并显示 stale 提示；质量页重新读取数据库，因而两页可能在短时间内展示不同同步批次。
* 单篇确定性质量每次读取最新指标重新计算；历史笔记 RQGM 则只存在当前组件内存。两者都没有向用户展示“基于哪次导入/哪版内容”。

## 5. 既有设计决策

* `07-13-historical-note-quality-analysis` 明确要求账户历史分读取全量持久化笔记，且不复用工作流 RQGM。
* `07-13-historical-note-detail-quality-evaluation` 明确将单篇历史质量定义为确定性互动信号，不修改工作流 RQGM。
* `07-15-rqgm` 又将 RQGM 作为历史笔记的补充 section 并排加入，且有意不持久化。
* `07-17-frontend-ux-optimization-v3` 将工作流评估与历史笔记融合为一个时间流，但账号过滤、评估持久化与分数语义并未同步收敛。

这些决策各自在局部成立；问题来自它们叠加后缺少统一查询上下文、评分分类和可追溯契约。

## 6. 关键代码证据

* `frontend/src/views/Analytics.vue`：主表使用 active account、页面周期和 dashboard 20 条；历史导入面板以 compact 模式挂载。
* `frontend/src/components/settings/CreatorStatsPanel.vue:157-180,613-647`：拉 100、展示前 8。
* `frontend/src/views/EvaluationView.vue:84-106,119-148,213-238`：历史笔记拉 200；工作流列表未传账号；使用不同时间字段混排。
* `frontend/src/components/evaluation/EvaluationOverview.vue:43-67,98-112`：账户报告跟账号刷新，RQGM 趋势不跟账号且请求全局。
* `backend/api/routes/analytics.py:511-618,705-730,784-798`：dashboard 合并/周期过滤；列表有界；账户质量读取全量。
* `backend/db/creator_stats.py:574-615`：列表默认按互动率排序且有 limit。
* `backend/api/routes/evaluation.py:92-188,271-355,438-489`：工作流列表账号可筛但前端未使用；历史笔记 RQGM 无持久化；趋势可筛但前端未使用。
* `backend/agents/evaluator.py:112-199,226-303`：超时降级为 100/approved；缺维补 70；所有加权维度进入总分。
* `.trellis/spec/backend/database-guidelines.md:243-331`：导入快照事务性、历史质量全量读取和单篇只读分析约束。
