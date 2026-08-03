# 历史笔记数据一致性续优化 PRD

状态：Implemented（2026-07-22）
关联任务：`07-22-history-quality-consistency-followup`

## 1. 背景与问题

上一轮已经完成 canonical cursor reader、账号隔离、评估来源分栏和基础快照字段，但
跨部署/旧数据场景仍可能出现“同一批数据被识别为不同批次”，以及原始互动率单位漂移。
本 PRD 只处理数据事实和快照契约，不调整业务评分模型。

## 2. 目标

### 2.1 快照是导入事实的版本，而不只是时间提示

- 每次账户级 Creator Stats 原子导入生成一个 opaque `snapshot_id`。
- 快照 ID 由账号范围、导入时间和稳定 note 版本摘要生成；响应不得暴露正文或明文业务 ID。
- 同一次导入的 account、canonical list、Analytics 和质量报告必须返回同一个快照 ID。
- 老数据没有持久化快照时，存储层按完整 note 集合的 ID、同步时间和原始指标稳定推导，
  不得只取当前页。

### 2.2 原始互动率只有一个单位

- Creator Stats、canonical notes、Analytics report/performance/dashboard 的原始
  `engagement_rate` 统一为 fraction（0–1）。
- 所有相关响应增加 `engagement_rate_unit: "fraction"`；百分比仅由前端 formatter 转换。
- 现有报表的展示数值保持不变，兼容客户端可通过单位字段判断转换方式。

### 2.3 存储层成为快照元数据唯一来源

新增/复用 `get_creator_stats_snapshot(account_id)`（名称可按实现调整），负责：

- 读取账户行和完整 note 集合的版本边界；
- 返回 `data_as_of`、`snapshot_id`、完整 note count；
- 处理内存 fallback、Postgres 旧数据、空账户和异常降级；
- 不触发同步、不写入数据库。

API 路由不得再各自拼接不同的时间/快照算法。

## 3. API 契约

### 3.1 Canonical 历史列表

`GET /api/analytics/creator-stats/{account_id}/notes`

- 每一页的 `snapshot_id`、`data_as_of`、`engagement_rate_unit` 与同一账号其他页稳定一致。
- cursor 仍是 `(published_at DESC, note_id DESC)`，`total` 仍为完整过滤总数。
- 任何同批次指标覆盖都必须改变 `snapshot_id`，让前端拒绝混页。

### 3.2 Analytics 响应

`/dashboard/{account_id}`、`/report/{account_id}`、`/performance/{account_id}`：

- 顶层及 `performance.posts` 使用 fraction；
- `report.metrics.avg_engagement_rate` 与 `period_summary.*.avg_engagement_rate` 使用 fraction；
- 增加 `engagement_rate_unit`，并保留现有字段名以兼容旧客户端；
- 不改变计数、排序、窗口或“发布后表现分”的语义。

## 4. 前端行为

- API 类型显式携带 `engagement_rate_unit`，边界 formatter 按单位处理，不再使用“数值小于等于 1
  就猜单位”的隐式规则作为主路径。
- Analytics store、历史表、CSV、质量抽屉和 Evaluation 历史列表继续显示相同的百分比格式，
  但内部事实保持 fraction。
- snapshot mismatch 继续阻止 cursor 追加；提示中区分“快照变化”和“请求失败”。

## 5. 验收标准

- [x] 无 `creator_account_stats` 行但有 600 条 note 的 Postgres reader，任意分页返回同一
   `snapshot_id`，无重复/漏项。
- [x] 同一 `synced_at` 下修改 note 指标会产生不同 `snapshot_id`，旧 cursor 不会追加新批次。
- [x] canonical、dashboard、report、performance 和 quality report 的快照元数据一致。
- [x] Analytics 所有原始互动率响应均为 fraction 并携带单位字段；前端展示仍为正确百分比。
- [x] 账号隔离、空数据、legacy fallback、旧客户端字段和异常降级保持兼容。
- [x] 后端/前端全量测试、静态检查、类型检查、i18n 和构建通过。

## 6. 灰度与回滚

继续使用 `QUALITY_CONSISTENCY_V2`。新增字段为 additive；关闭开关时保留旧响应读取，
但存储层快照值不删除。若发现外部客户端依赖百分比，可先通过单位适配器兼容，不回退
数据库快照写入。

## 7. Definition of Done

- [x] 研究审计、实现记录和测试证据写入本任务目录。
- [x] 相关后端/frontend spec 继续遵守 canonical reader、单位和 stale guard 契约。
- [x] 自动化验证通过；无浏览器 harness 时保留人工双账号验收项。

## 8. 实现记录与验证证据

### 已实现

1. `creator_stats` 存储层新增 `get_creator_stats_snapshot` 和稳定版本摘要：完整账号
   note 集合（canonical 指标、同步时间、note ID）参与 opaque digest；原子 bundle 导入把
   `snapshot_id` 写入账户 `raw_json`。旧 Postgres 数据、无账户行、无同步时间但有内容摘要时
   仍可只读推导，不触发同步或写入。
2. canonical 分页、账户概览、Analytics 三条入口、账户/单篇质量和详情统一读取该快照；
   同时间戳指标覆盖会改变 ID，分页不会用当前页的局部数据生成版本。
3. Analytics API 的帖子、报表均值和 period summary 在边界统一为 fraction，并增加
   `engagement_rate_unit="fraction"`；Vue store/view、CSV、OMP bridge 和 xhsagent-ext
   使用显式单位适配百分比展示，保留无单位旧响应的兼容回退。
4. 更新数据库/跨层规范，补充 Postgres legacy、快照摘要和 Analytics 单位契约。

### 自动化验证

| 检查 | 结果 |
| --- | --- |
| `python3 -m pytest -q tests/unit` | 1449 passed，2 个既有异步资源 warning |
| `pnpm --dir frontend test:run` | 48 个文件 / 588 tests passed；happy-dom 本地连接 warning 不影响断言 |
| `ruff check backend tests/unit` + `ruff format --check backend tests/unit` | 通过 |
| `python3 -m mypy backend` + `python3 -m compileall -q backend` | 173 个源文件通过；编译通过 |
| `pnpm --dir frontend type-check` + `pnpm --dir frontend i18n:check` + `pnpm --dir frontend build` | 全部通过（build 仅保留既有 chunk 大小提示） |
| `npm run typecheck --prefix backend/omp/extensions/xhsagent-ext` | 通过 |
