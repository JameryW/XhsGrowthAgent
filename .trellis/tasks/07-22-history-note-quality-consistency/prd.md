# 历史笔记与质量评估数据一致性优化 PRD

状态：Implemented / Verification complete（2026-07-22）
优先级：P0（停止误导）+ P1（统一契约与可追溯）
涉及页面：`/analytics`、`/evaluation`、历史笔记详情抽屉
涉及数据：Creator Center 导入笔记、工作流评估、RQGM 历史笔记评估

## 1. 一句话结论

当前两页“不一致”的根因不是单一计算错误，而是产品把不同账号范围、不同记录集合、不同时间窗口和两套不可直接比较的评分体系都称为“质量”；同时还存在工作流数据跨账号混入、列表隐式截断、历史 RQGM 不持久化、缺失上下文补默认分以及超时伪装成 100 分等实现缺陷。

本方案采用“**一套原始笔记事实 + 两类明确命名的评估**”：同一账号、同一筛选、同一数据时点下，两页的历史笔记 ID 与原始指标必须完全一致；“发布后表现分”和“RQGM 内容评审分”保留各自价值，但必须携带范围、输入覆盖、版本和评估时点，禁止再以无边界的“综合质量分”混用。

## 2. 背景与问题

### 2.1 用户看到的现象

* 数据分析页能看到的历史笔记数量、顺序或互动数据，与质量评估页不同。
* 质量页切换到某个账号后，仍可能看到其他账号的工作流评估和趋势。
* 同一篇历史笔记同时出现“历史质量分”和“RQGM 分”，数值与维度不同，却都被描述为质量评分。
* 手动运行历史笔记 RQGM 后，切换笔记或刷新页面结果消失；再次运行可能得到不同结果。
* 账户质量报告显示的样本数可能大于质量页可见历史笔记数。

### 2.2 当前口径差异

| 位置 | 当前口径 | 导致的差异 |
| --- | --- | --- |
| 数据分析主表 | 当前活动账号；daily/weekly/monthly；已完成工作流帖子与导入笔记合并；最近 20 篇 | 不是“全部历史笔记”，包含工作流数据并受时间窗口限制 |
| 数据分析历史笔记表 | 当前活动账号；拉取 100；compact 只显示互动率最高的 8 篇 | 与按发布时间浏览的质量页首屏不同，且有隐式截断 |
| 质量页历史笔记流 | 当前选择账号；拉取最多 200；按发布时间与工作流评估混排 | 超过 200 篇不可见；混入不同事件时间 |
| 质量页账户历史分 | 当前选择账号；读取全部持久化笔记 | 样本数可能大于页面列表数 |
| 质量页工作流列表/趋势 | 前端未传 `account_id`，实际为全部账号 | 账号选择器未形成真正的数据边界 |

完整代码链路与证据见 [`research/data-lineage-audit.md`](research/data-lineage-audit.md)。

## 3. 根因与优先级

| 编号 | 根因 | 类型 | 优先级 |
| --- | --- | --- | --- |
| RC-01 | 质量页账号选择只作用于历史笔记/账户报告，工作流列表、趋势和已评估总数仍为全账号 | 真实数据错误 / 隔离缺陷 | P0 |
| RC-02 | 8、20、100、200、500、全量等读取上限分散在组件和接口中，且未显示已加载范围 | 数据集合不一致 | P0 |
| RC-03 | Analytics 使用活动账号，Evaluation 使用页面本地账号；两页没有共享、可见的查询上下文 | 上下文漂移 | P0 |
| RC-04 | “发布后表现信号”和“发布前/内容 RQGM 评审”共用“质量分”名称与 0–100 视觉 | 语义误导 | P0 |
| RC-05 | 历史笔记、工作流和评估趋势分别按发布时间、工作流更新时间、评估创建时间排序，却混成一条时间流 | 时间语义不一致 | P1 |
| RC-06 | 历史笔记 RQGM 结果仅存在组件内存，无评估 ID、内容快照、模型/prompt/权重版本 | 不可追溯 / 不可复现 | P1 |
| RC-07 | 缺赛道静默回退“母婴”；缺维补 70；文本模型未看图片但视觉分仍进入总分 | 输入覆盖失真 | P0 |
| RC-08 | LLM 超时返回 `100/approved/degraded=true`，前端不识别 degraded | 严重误导 | P0 |
| RC-09 | 页面请求没有共同 `data_as_of/snapshot_id`，Analytics 还可能保留旧缓存 | 新鲜度不透明 | P1 |
| RC-10 | 工作流帖子与导入笔记只按偶然相等的 post ID 去重，没有显式发布关联 | 重复或错配 | P2 |

## 4. 产品目标

### 4.1 目标

1. **原始数据一致**：同一 `account_id + filters + data_as_of` 下，Analytics 历史笔记与 Evaluation 历史笔记的 `note_id` 集合及原始指标 100% 一致。
2. **账号隔离一致**：账号切换后，历史笔记、账户报告、工作流评估、趋势和 KPI 全部使用同一账号；只有用户显式选择“全部账号”时才聚合。
3. **评分语义清晰**：用户能直接分辨“发布后表现分”与“RQGM 内容评审分”，理解它们为何可能不同。
4. **结果可追溯**：任一分数都能回答“评了谁、基于哪版数据、何时评、由哪版算法/模型评、哪些维度缺失”。
5. **失败不伪装**：上下文不足、维度不可用、超时或模型失败时显示不可用/部分结果，绝不显示伪 0 分、伪 70 分或伪 100 分。
6. **大数据量正确**：超过 100/200/500 篇时可完整分页，报告样本数、列表总数与已加载数的关系明确。

### 4.2 成功指标

* `note_set_mismatch_rate`：同查询上下文跨页面笔记集合差异率 = 0。
* `raw_metric_mismatch_rate`：同 `account_id + note_id + snapshot_id` 的 views/likes/comments/collects/shares/engagement_rate 差异率 = 0。
* `cross_account_row_rate`：选择单账号后出现其他账号记录的比例 = 0。
* 100% 的评分卡包含 `assessment_type`、`scope`、`data_as_of/evaluated_at` 与版本信息。
* 100% 的 degraded/failed RQGM 结果不进入成功分数、通过率或趋势聚合。
* 历史笔记 RQGM 完成后刷新页面可恢复同一 `evaluation_id` 的结果。

## 5. 非目标

* 不要求“发布后表现分”与“RQGM 内容评审分”数值相等；二者回答的问题不同。
* 本期不重新设计 RQGM 的业务权重，也不以真实互动数据反向修改现有评审权重。
* 本期不切换到多模态模型；模型无法查看真实图片时，相关维度应标记不可用。
* 不在打开页面时自动触发 Creator Center 浏览器同步或自动产生 LLM 费用。
* 不删除现有历史质量分析器，也不删除工作流 checkpoint 中已有的评估结果。
* 不在本 PRD 阶段直接实现代码。

## 6. 统一概念与命名

### 6.1 两类评估

| 稳定标识 | 中文名称 | 回答的问题 | 输入 | 可比较范围 |
| --- | --- | --- | --- | --- |
| `historical_performance` | **发布后表现分** | 已发布内容从真实互动、收藏、标题和稳定性看表现如何？ | Creator Center 持久化指标 | 同算法版本、相近数据窗口内可比较 |
| `rqgm_content_review` | **RQGM 内容评审分** | 当前内容快照在文案、合规、受众、视觉计划等方面是否达到评审门槛？ | 内容快照 + 账号上下文 + evaluator | 同 evaluator fingerprint 与相同覆盖范围内可比较 |

产品文案禁止单独使用“综合质量分”指代上述任一结果。账户级结果显示“历史发布表现”，工作流/历史内容评审显示“RQGM 内容评审”。

### 6.2 必备上下文字段

所有列表与详情响应至少携带：

* `account_id`
* `subject_type`: `imported_note | workflow_draft`
* `subject_id`: 对应 `note_id | thread_id`
* `scope`: `account_history | single_note | workflow_draft`
* `assessment_type`: `historical_performance | rqgm_content_review`
* `data_as_of`，单篇同时提供 `note_synced_at`
* `algorithm_version`（确定性分析）或 `evaluation_id + evaluator_fingerprint`（RQGM）
* `status`: `ready | partial | unavailable | running | degraded | failed`
* `coverage`: 可用维度、不可用维度、加权覆盖率

`evaluator_fingerprint` 由 model、prompt version/epoch、weights hash、thresholds hash 组成，不能只返回模型名。

## 7. 目标用户体验

### 7.1 页面级账号上下文

* `/analytics` 与 `/evaluation` 的默认账号都取活动账号；没有活动账号时选择账号列表第一项并明确显示。
* 质量页账号选择是该页唯一账号来源，必须同时驱动账户报告、历史笔记、工作流评估、趋势与 KPI。
* “全部账号”作为显式选项，默认不选；选择后只展示支持聚合的工作流视图，不计算跨账号历史表现分。
* 页面标题区显示当前账号、数据截至时间和刷新入口；切换账号时旧账号数据立即进入 loading/stale-guard，不得短暂混入新账号页面。

### 7.2 质量页不再默认混排不可比对象

质量页列表区域拆为两个明确来源页签：

1. **已发布历史笔记**：基于 `creator_note_stats`，按 `published_at` 排序；显示真实指标、发布后表现状态、最新 RQGM 内容评审状态。
2. **工作流内容评审**：基于 workflow/checkpoint，按 `evaluated_at` 排序；显示 RQGM 分数与 decision。

“全部活动”混排不属于 MVP。若未来恢复，必须分别展示“发布时间”和“评估时间”，不能用一个无说明的时间字段排序。

### 7.3 历史笔记详情

详情页/抽屉按以下顺序展示：

1. 原始事实：标题、正文/封面可用性、互动指标、发布时间、数据同步时间。
2. 发布后表现分：确定性维度、证据、置信度、算法版本。
3. RQGM 内容评审：最新持久化结果或“尚未评审”；明确评审输入覆盖、评审时间、版本与费用提示。
4. 两类分数之间显示固定说明：“两者分别衡量发布后表现与内容评审，不直接比较高低”。

### 7.4 数量与分页

* 列表头同时显示 `已加载 x / 共 y`；任何截断都必须可见。
* 默认按 `published_at DESC, note_id DESC` 稳定排序，支持 cursor 分页。
* Analytics 的 compact 历史表可只展示前 8，但必须标注“显示 8 / 共 y”并提供“查看全部”，跳转时保留账号和筛选上下文。
* 账户报告若分析全量 600 篇，而当前只加载 50 篇，应显示“报告分析 600 篇；列表已加载 50 篇”，不得让用户误以为缺数。

## 8. 功能需求

### 8.1 P0：停止展示错误或误导信息

#### CTX-01 账号过滤贯通

* `EvaluationView.loadList` 必须传当前 `selectedAccountId`，账号变化时重置分页并重载。
* `EvaluationOverview` 的趋势请求必须传当前账号并 watch 账号变化。
* `evaluatedTotal`、趋势、工作流列表、账户报告和历史笔记必须声明同一 account scope。
* 后端仍保留不传 `account_id` 的管理员/全局兼容行为，但产品 UI 默认不得使用。

#### SEM-01 评分命名与来源拆分

* 全部“质量分/综合质量”文案按第 6 节改为稳定名称。
* 质量页默认分开呈现历史笔记和工作流评估，不再按 `published_at × updated_at` 混排。
* 趋势图只聚合 `rqgm_content_review`，且必须限定账号；账户历史表现另用聚合卡，不进入同一折线。

#### SAFE-01 degraded/failed 不得成为通过分

* RQGM 超时或模型失败返回 `status=degraded|failed`、`overall_score=null`、`decision=null`，附可重试错误；不得返回可消费的 `100/approved`。
* 为兼容旧后端，前端只要收到 `degraded=true`，即忽略随附 score/decision，显示“评估未完成”。
* degraded/failed 不进入评估列表成功数、通过率、趋势和维度均值。

#### SAFE-02 缺失上下文诚实降级

* 历史笔记缺账号赛道时，复用现有赛道解析结果并返回 `niche_source`；若仍为 cold start，audience/reach 标记不可用，禁止静默写入“母婴”。
* 文本模型未实际读取图片时，历史笔记的 visual/image_quality 标记 `available=false`，不补参考分。
* evaluator 漏返维度时标记不可用，不再自动补 70 分。
* 综合分仅对可用加权维度归一化；必须包含 copywriting 与 compliance，且加权覆盖率达到后端单一常量 `MIN_EVALUATION_COVERAGE`（建议初值 60%）。不足则 `overall_score=null, status=partial`。

#### API-01 阈值与状态契约完整

* 历史笔记 `evaluateNote` 前端类型保留后端 `thresholds`、`status/degraded` 与 coverage。
* 所有颜色档位使用响应中的账号有效阈值；没有阈值时才使用同一前端默认常量。
* `overall_score=null` 使用中性色 `—`，不可映射为 0。

### 8.2 P1：统一历史笔记事实与可追溯结果

#### DATA-01 统一历史笔记列表接口

新增或等价实现：

```text
GET /api/analytics/creator-stats/{account_id}/notes
  ?cursor=<opaque>
  &limit=50
  &sort=published_at_desc
  &published_from=<iso>
  &published_to=<iso>
```

响应：

```json
{
  "account_id": "acc-1",
  "items": [],
  "total": 250,
  "limit": 50,
  "next_cursor": "opaque-or-null",
  "data_as_of": "2026-07-22T10:00:00Z",
  "query": {
    "sort": "published_at_desc",
    "published_from": null,
    "published_to": null
  }
}
```

* Analytics 历史表和 Evaluation 历史页签必须复用该接口，不再各自传 100/200 后二次隐式截断。
* `total` 是过滤后的完整数量；cursor 使用稳定 `(published_at, note_id)`，避免同步期间 offset 漂移。
* 原始 DTO 中的 engagement rate 只保留一个规范单位；推荐 API 输出 fraction（0–1）并在 schema 中声明，展示层统一格式化。
* 现有 `GET /creator-stats/{account_id}` 保留兼容，但标记为 overview + bounded preview，不再作为完整列表契约。

#### DATA-02 数据时点可见

* 历史列表、账户报告和详情返回 `data_as_of`；单篇返回 `note_synced_at`。
* 前端显示“数据截至 …”；Analytics 使用旧缓存时显示“展示上次数据”。
* 同一页面并行响应的 `data_as_of` 不一致时，保留最新共同快照或提示刷新，不静默拼装不同批次。
* 后续可为导入事务增加 `snapshot_id/import_run_id`；MVP 可先用账户快照时间 + 单篇 synced_at，但字段命名需为未来 ID 预留。

#### EVAL-01 持久化历史笔记 RQGM

新增独立 `quality_evaluation_runs`（名称可按数据库规范调整），不直接把手动历史评审混入训练样本表。最少字段：

* `evaluation_id`
* `account_id`
* `subject_type` / `subject_id`
* `assessment_type`
* `source_content_hash` / `source_data_as_of`
* `context_hash`（含赛道来源与可用字段）
* `evaluator_fingerprint`
* `status`
* `result_json` / `coverage_json` / `thresholds_json`
* `created_at` / `completed_at`

唯一性建议：`account_id + subject_type + subject_id + source_content_hash + context_hash + evaluator_fingerprint`。

#### EVAL-02 幂等与重评估

* 默认点击“评估”时，若内容、上下文和 evaluator fingerprint 未变，返回最近成功记录，不重复付费调用。
* “重新评估”显式传 `force=true`，创建新的 evaluation run，并保留历史版本。
* 指标更新但内容 hash 未变时，只影响发布后表现分，不强制重跑 RQGM。
* 标题、正文、标签、封面可用性或赛道上下文变化时，旧 RQGM 标记 stale，用户可重评。
* 新增 `GET /evaluation/note/{account_id}/{note_id}/latest`（或等价详情聚合）供页面刷新后恢复结果。

#### EVAL-03 评估响应示例

```json
{
  "evaluation_id": "eval_...",
  "account_id": "acc-1",
  "subject_type": "imported_note",
  "subject_id": "note-1",
  "assessment_type": "rqgm_content_review",
  "status": "partial",
  "overall_score": 76.4,
  "decision": "approved",
  "coverage": {
    "weighted_ratio": 0.72,
    "available": ["copywriting", "compliance", "audience"],
    "unavailable": ["visual", "image_quality"]
  },
  "source": {
    "content_hash": "sha256:...",
    "data_as_of": "2026-07-22T10:00:00Z",
    "niche": "穿搭",
    "niche_source": "account_bound"
  },
  "evaluator_fingerprint": "rqgm:prompt-epoch:weights-hash:model",
  "evaluated_at": "2026-07-22T10:02:00Z"
}
```

### 8.3 P2：工作流与发布笔记显式关联

#### LINK-01 规范身份

* 历史笔记的唯一标识始终为 `(account_id, note_id)`；禁止标题匹配。
* 发布成功时持久化 `thread_id -> platform_post_id`；Creator Center 导入后以规范化 platform ID 关联到 `note_id`。
* 关联状态为 `linked | unmatched | ambiguous`，不能用静默去重掩盖冲突。
* Analytics 合并视图只在 `linked` 时折叠为一条；无法关联时分别显示来源。

#### LINK-02 发布前后对照（后续能力）

当 workflow 与 imported note 明确关联后，可在详情中并排展示“发布前 RQGM 内容评审”与“发布后真实表现”，用于解释而非训练或自动归因。本期只保留数据结构扩展点。

## 9. API 与兼容策略

### 9.1 保留接口

* `GET /analytics/creator-stats/{account_id}`：保留账户 overview 与 bounded preview。
* `GET /analytics/creator-stats/{account_id}/quality`：继续返回全量账户发布后表现报告，新增算法版本和 data_as_of。
* `GET /analytics/creator-stats/{account_id}/notes/{note_id}` 与 `/quality`：保持只读，补充来源元数据。
* `GET /evaluation/list`、`GET /evaluation/trend`：保留，前端开始正确传 `account_id`；响应增加 scope/时间字段。
* `POST /evaluation/note`：保持路径兼容，从“临时返回”升级为“持久化、幂等返回”。

### 9.2 兼容原则

* 新字段全部先 additive；旧客户端可忽略。
* `decision` 新增不可用状态时优先通过外层 `status` 表达，避免立即破坏既有枚举；`status != ready|partial` 时 score/decision 必须为 null。
* 已有临时历史 RQGM 结果从未持久化，无可靠数据可回填，不制造历史记录。
* 旧 workflow checkpoint 继续按现有方式读取；只在新响应适配层补充 scope 与 evaluator metadata（能推导多少返回多少）。

## 10. 边界与异常场景

| 场景 | 期望行为 |
| --- | --- |
| 无账号 | 显示创建/导入账号引导，不请求 `default` 伪账号的历史质量 |
| 账号切换中 | 清空或冻结旧账号列表并展示 loading；迟到响应不得覆盖新账号 |
| 账号无赛道 | 尝试既有解析；仍 cold start 时标记受众/触达维度不可用，不默认母婴 |
| 历史笔记无正文 | 只评可用内容；coverage 明确，低于门槛不出总分 |
| 文本模型无法看封面 | visual/image_quality 不可用，不给参考分 |
| LLM 超时/解析失败 | `status=degraded|failed`、无分、可重试；不计入趋势 |
| 导入数据刷新 | 原始指标切到新 data_as_of；发布后表现重算；内容未变则 RQGM 可复用 |
| 超过 600 篇 | cursor 可遍历完整集合；账户报告样本数与列表 total 一致 |
| 同发布时间 | 以 `note_id` 作为稳定次排序键，不重复/跳过 |
| 工作流 ID 与 note ID 不一致 | 标记 unmatched，分别展示，不按标题去重 |
| Analytics 使用旧缓存 | 明示 stale 和上次 data_as_of；不得与质量页最新数据声称同一时点 |
| 旧 RQGM 记录缺版本 | 显示“旧版/版本未知”，不与新版趋势默认聚合 |

## 11. 验收标准

### 11.1 数据一致性

* [x] 给定账号 A、相同发布时间筛选和同一 `data_as_of`，Analytics 历史表与 Evaluation 历史页签复用 canonical reader，遍历分页后的 `note_id` 集合完全相同。
* [x] 任取同一 `(account_id, note_id, data_as_of)`，两页使用同一规范 DTO，views/likes/comments/collects/shares/engagement_rate 完全一致。
* [x] 账号 A/B 均有数据时，选择 A 后列表、趋势、KPI 和报告均经过同一账号边界过滤。
* [x] 250、600 篇数据通过 cursor 遍历，UI 同时显示已加载数与总数，不再隐式截断。
* [x] 默认排序固定为 `published_at DESC, note_id DESC`，游标测试验证无重复、无漏项。

### 11.2 评分语义与安全

* [x] UI 全面区分“发布后表现分”与“RQGM 内容评审分”，不再使用无限定“综合质量分”。
* [x] 两类分数不进入同一趋势或通过率统计；详情明确“不直接比较”。
* [x] 缺赛道不会静默使用母婴；缺视觉输入不会产生 visual/image_quality 伪分。
* [x] evaluator 漏维、LLM 超时、解析失败不会展示 70/100 或 approved；结果为 partial/unavailable/degraded/failed。
* [x] 历史笔记组件使用账号有效阈值，后端阈值覆盖测试证明颜色与 decision 契约一致。

### 11.3 持久化与版本

* [x] 历史笔记 RQGM 成功后刷新页面仍返回同一 evaluation ID 和结果。
* [x] 内容/上下文/evaluator fingerprint 未变化时默认命中幂等结果，不重复调用模型。
* [x] `force=true` 产生新版本，旧版本可追溯。
* [x] 内容/上下文变化会将旧评估标记 stale；只有指标变化不会无故重跑内容评审。
* [x] 每个成功/部分结果都有 coverage、source hash、data_as_of、evaluated_at 和 evaluator fingerprint。

### 11.4 质量门槛

* [x] 后端单元/API 测试覆盖账号过滤、cursor、大于 500 篇、缺失上下文、degraded、持久化幂等和旧数据兼容。
* [x] 前端视图/组件测试覆盖账号切换、来源页签、数量/截断、双分数文案、stale、degraded 与阈值。
* [~] 双账号 E2E 闭环：当前仓库没有可运行的浏览器 E2E harness，已由 API/组件契约测试覆盖；部署环境需按第 10 节手工验收。
* [x] Ruff、Mypy、前端 type-check/build/i18n 与相关测试通过。

## 12. 埋点与监控

仅记录 ID hash、范围、状态与计数，不采集标题、正文、账号名或原始内容。

* `quality_note_set_mismatch_total`
* `quality_raw_metric_mismatch_total`
* `quality_cross_account_row_total`
* `quality_list_truncated_total`
* `quality_evaluation_degraded_total`
* `quality_evaluation_cache_hit_total`
* `quality_snapshot_lag_seconds`
* `workflow_note_link_rate`

日志必须包含 request ID、account ID（按现有日志规范处理）、subject type/ID、data_as_of、evaluation ID 与 status，禁止输出 content snapshot 正文。

## 13. 灰度、迁移与回滚

### 13.1 分阶段上线

1. **PR1 / P0 停止误导**：账号过滤贯通；评分改名/分栏；degraded、缺上下文与阈值契约修复；补测试。
2. **PR2 / 统一事实列表**：新增 cursor 历史笔记接口；两页切到同一 reader；显示 total、data_as_of 与 stale；用影子比对记录集合差异。
3. **PR3 / 评估可追溯**：新增 evaluation run 表；`POST /evaluation/note` 幂等持久化；latest 查询、版本与 stale 状态。
4. **PR4 / 身份关联**：发布时写 platform post ID；导入后显式 link；改造 Analytics 合并去重。

### 13.2 灰度方式

* 使用 `QUALITY_CONSISTENCY_V2`（最终名称由实现规范决定）控制新列表与新评估读取。
* 先内部账号影子读取 V1/V2，仅比较 note IDs/原始指标，不比较两类分数。
* 指标无差异后按 10% → 50% → 100% 开启；跨账号混入或原始指标差异任一非零即停止扩量。

### 13.3 回滚

* 新接口、新字段与 evaluation run 表均为 additive；关闭 feature flag 即回到旧读取路径。
* 回滚不删除新表或评估历史，避免数据不可恢复；恢复上线后继续读取。
* 数据库迁移必须有独立 down/compat 方案，但回滚应用时不依赖立即删列/删表。

## 14. 方案对比与决策（ADR-lite）

### 方案 A：只修前端筛选和文案

* 优点：改动小，可快速解决跨账号列表和明显文案问题。
* 缺点：100/200/全量仍分裂，历史 RQGM 仍不可追溯，无法证明同一数据时点。

### 方案 B：统一事实 reader + 双评估分类 + 评估版本化（推荐）

* 优点：从数据集合、语义和生命周期三层解决；保留确定性表现分析和 RQGM 的各自价值；支持未来发布前后对照。
* 缺点：需要新分页契约和持久化表，涉及前后端及迁移。

### 方案 C：强制全部页面只保留一套分数

* 优点：表面数值统一。
* 缺点：把真实发布表现与内容评审混为一谈，丢失业务信息；无法科学保证同分，不采用。

**Context**：现有多个局部需求分别引入了全量历史分析、单篇确定性分析、历史笔记 RQGM 和融合时间流，缺少统一边界。

**Decision**：采用方案 B。原始历史笔记由一个 canonical reader 提供；两类评估使用稳定类型和独立趋势；历史 RQGM 持久化并携带输入/评估版本。

**Consequences**：短期增加接口和存储复杂度，但能消除跨账号与截断错误，解释合理的分数差异，并为发布前后效果分析提供可靠基础。两类分数将继续可能不同，这是正确且可解释的产品行为。

## 15. Definition of Done

* PRD 中 P0/P1 验收项全部可由自动化测试或明确人工步骤验证。
* 数据契约、数据库迁移、前端状态、i18n、监控和回滚均有实现记录。
* 相关后端/前端 spec 更新，明确 canonical note reader、assessment taxonomy、degraded 语义和版本字段。
* 上线前完成双账号、超过 500 篇、缺赛道、缺正文/图片、LLM 超时、同步中和旧记录兼容演练。

### 15.1 本次实现记录

* 后端新增 cursor 历史笔记 canonical reader、fraction 互动率 DTO、账号隔离元数据、显式 workflow/imported-note 关联状态，以及 `quality_evaluation_runs` 持久化/幂等/stale/latest 契约。
* Evaluator 对缺失维度、赛道、图片输入和超时统一诚实降级；不可消费结果不进入列表成功数、样本、通过率或趋势。
* Analytics 与 Evaluation 共用历史笔记 reader，按来源页签分离，增加加载数/总数、数据时点、账号切换 stale guard 和双评分说明。
* 已更新 9 份 Trellis backend/frontend/guides spec，补充 canonical reader、评估 taxonomy、降级语义和跨层验收场景。
* 本轮收口补充：新增 `quality_consistency.v2` 共享契约与 `QUALITY_CONSISTENCY_V2` 灰度开关；canonical reader、Analytics dashboard、Evaluation 列表/趋势/单篇结果统一返回可协调的 `data_as_of + snapshot_id`，并阻止跨快照 cursor 页拼接。全账号作为显式 `ALL_ACCOUNTS_ID` 范围，仅展示工作流内容评审，历史发布表现不做跨账号聚合。
* 本轮收口补充：Analytics 的 workflow/imported note 关联只接受规范 platform ID；关联后 Creator Center 导入指标为发布后事实权威源，响应补充 `subject_type/subject_id/scope/assessment_type/status` 等主体元数据，并暴露 link rate。
* 本轮收口补充：质量一致性埋点事件已加入前后端 allowlist（集合差异、原始指标差异、跨账号行、截断、降级/缓存、快照滞后、关联率），仅保留范围、状态和计数；前端历史评估详情展示 evaluation ID、evaluator fingerprint 与 snapshot ID。
* 验证结果：`pytest -q tests/unit`（1443 passed）、前端 Vitest（48 files / 588 tests passed）、Ruff、Mypy、compileall、type-check、build、i18n check 均通过；仅保留既有测试环境 warning。浏览器双账号 E2E 仍因仓库没有可运行的浏览器 harness 保留为 `[~]`，需按第 10 节手工验收。

## 16. Technical Notes

### 主要影响文件

* 前端：`frontend/src/views/Analytics.vue`、`frontend/src/views/EvaluationView.vue`、`frontend/src/components/evaluation/EvaluationOverview.vue`、`frontend/src/components/settings/CreatorStatsPanel.vue`、`frontend/src/components/settings/CreatorNoteQualityPanel.vue`、`frontend/src/api/{analytics,evaluation}.ts`、`frontend/src/types/evaluation.ts`。
* 后端：`backend/api/routes/{analytics,evaluation}.py`、`backend/db/{creator_stats,evaluator_config}.py`、新增 evaluation run 存储模块、`backend/services/creator_stats/quality.py`、`backend/agents/evaluator.py`。
* 测试：`frontend/tests/views/EvaluationView.spec.ts`、`frontend/tests/components/CreatorNoteQualityPanel.spec.ts`、`tests/unit/api/test_evaluation_note.py`、creator stats/quality API 与数据库测试。

### 现有约束

* Creator Center 导入必须继续以事务写入持久化快照，不允许页面读取触发浏览器同步。
* 账户历史表现继续读取全量 `list_all_note_stats`，不能被列表分页上限污染。
* 单篇详情和确定性质量接口继续只读，不写数据库或 Creative Memory。
* `evaluator_samples` 是训练/趋势数据，不默认承担用户可见评估记录的审计职责。

### 参考

* [`research/data-lineage-audit.md`](research/data-lineage-audit.md)
* `.trellis/tasks/archive/2026-07/07-13-historical-note-quality-analysis/prd.md`
* `.trellis/tasks/archive/2026-07/07-13-historical-note-detail-quality-evaluation/prd.md`
* `.trellis/tasks/archive/2026-07/07-15-rqgm/prd.md`
* `.trellis/tasks/07-17-frontend-ux-optimization-v3/prd.md`
* `.trellis/spec/backend/database-guidelines.md`
* `.trellis/spec/backend/free-creation.md`
* `.trellis/spec/frontend/component-patterns.md`
