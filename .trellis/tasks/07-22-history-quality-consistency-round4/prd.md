# 第四轮历史质量数据一致性优化 PRD

状态：Implemented（2026-07-22）
关联任务：`07-22-history-quality-consistency-round4`

## 1. 背景与问题

第三轮已经把 canonical 历史分页的数据库读取收敛到同一 `REPEATABLE READ` 事务，但
跨层审计发现仍有两个混批窗口：

1. `/creator-stats/{account_id}/quality`、`/report`、`/performance` 和 `/dashboard`
   先读取完整 imported notes，再通过另一个调用读取 `snapshot_id`。并发导入时，报告
   计算的 note facts 可能属于旧批次，响应 metadata 却属于新批次。
2. 前端 `getCreatorNotes` 在 canonical endpoint 不可用时回退到旧 overview，构造的
   `CreatorNotesPayload` 漏掉 `snapshot_id`；Evaluation/Analytics 因而无法阻止旧服务
   数据与新 dashboard 混页。回退路径也没有显式传递 `engagement_rate_unit`。

这两类问题会让“数据分析页历史笔记”和“质量评估”在刷新、导入并发或旧服务灰度期间
再次出现数量、指标和快照不一致。

## 2. 目标

1. 在存储层提供只读 `Creator Stats snapshot bundle`，在一个一致性事务中返回
   `account`、完整 `notes`、`note_count`、`data_as_of` 和 `snapshot_id`；已有
   `get_creator_stats_snapshot` 复用它，避免重复 SQL/parser。
2. Analytics 的 report/performance/dashboard 和账户级 quality 使用同一个 bundle 的
   notes 计算，同时从该 bundle 取 snapshot metadata；同一响应内不再跨调用拼接两批事实。
3. 保留 `_merge_imported_posts` 的旧调用兼容性，但支持调用方注入已读取的 notes，避免
   report/dashboard 再打开独立 reader。
4. 前端 canonical reader 的 legacy fallback 始终保留 `snapshot_id`、`data_as_of` 和
   `engagement_rate_unit`；旧服务仍可用，但 UI 能继续执行 stale guard 和显式单位适配。
5. OMP Creator Stats 工具优先使用服务端显式单位字段，只有旧响应缺字段时才启用 heuristic
   fallback。

## 3. 非目标

- 不修改质量评分维度、阈值、RQGM 语义或历史报告文案。
- 不改变 cursor 排序、API 路径、旧字段名、页面展示百分比或导入写入事务。
- 不把完整 note 正文写入日志、缓存或客户端 telemetry。

## 4. 一致性契约

### 4.1 Storage bundle

`get_creator_stats_snapshot_bundle(account_id)`（名称可按实现调整）是同账号历史事实
的只读来源。Postgres 路径使用一个 `REPEATABLE READ` transaction；memory/legacy
fallback 返回同样的字段形状。bundle 内的 `notes` 是完整账号集合，`snapshot_id` 必须
由这组 notes/account 推导，不能在 bundle 之后重新读取。

### 4.2 Analytics 与质量

- `report.metrics`、`performance.posts`、`period_summary` 和 quality report 的输入
  notes 与响应 `snapshot_id` 来自同一 bundle。
- 工作流帖子仍可合并展示，但 Creator Center imported facts 对同 note 的指标保持权威；
  若 imported reader 降级为空，响应不能伪造新的 Creator Stats snapshot。
- 质量报告 `total_notes`/`notes_analyzed` 与 bundle 的完整 notes 一致。

### 4.3 Frontend/OMP compatibility

- 所有 `CreatorNotesPayload` fallback 都携带 `snapshot_id`（没有时为 `null`）并保留
  服务端显式的 `engagement_rate_unit`；旧服务缺失单位时保留 `undefined`，让已有
  heuristic 兼容逻辑接管，不能把未知的百分比误标成 fraction。
- OMP 读取当前显式单位；无单位旧响应沿用数值 heuristic，避免破坏旧服务。

## 5. 验收标准

- [x] bundle 的 account、完整 notes、snapshot metadata 在同一 Postgres 事务内读取；旧
  `get_creator_stats_snapshot` 仍保持兼容。
- [x] quality/report/performance/dashboard 的输入 notes 与 snapshot metadata 来源一致，
  并发导入不会返回旧报告 + 新 snapshot。
- [x] legacy frontend fallback 保留 snapshot/unit，snapshot mismatch 仍会阻止追加。
- [x] OMP 当前 fraction 响应在 `engagement_rate=1.0` 等边界仍显示 100%，percent 旧响应
  显示原百分比。
- [x] 后端/前端/OMP 测试、lint、类型检查、构建通过；lockfile 等无关改动不提交。

## 6. 实现记录与验证证据

### 已实现

1. `creator_stats` 新增 `get_creator_stats_snapshot_bundle`，Postgres 使用既有
   `REPEATABLE READ` 事务同时读取 account/full notes，旧 snapshot API 复用 bundle。
2. Analytics report/performance/dashboard、legacy overview、质量报告和单篇详情/质量
   使用 bundle 的 notes 与 metadata；`_merge_imported_posts` 支持注入 bundle-owned notes。
3. `getCreatorNotes`、Analytics/Evaluation view fallback 保留 snapshot/unit；未知旧单位
   不强制标成 fraction，继续交给已有兼容 formatter。OMP Creator Stats 按显式单位格式化。
4. 更新 backend/frontend/cross-layer 规范与 bundle/fallback/单位回归测试。

### 自动化验证

| 检查 | 结果 |
| --- | --- |
| `python3 -m pytest -q tests/unit` | 1453 passed，2 个既有 warning |
| `pnpm --dir frontend test:run` | 49 个文件 / 590 tests passed |
| `pnpm --dir frontend type-check` | 通过 |
| `pnpm --dir frontend i18n:check` | 1944 keys 一致 |
| `pnpm --dir frontend build` | 通过（保留既有 chunk 大小提示） |
| `python3 -m ruff check backend tests/unit` | 通过 |
| `python3 -m ruff format --check backend tests/unit` | 307 个文件已格式化 |
| `python3 -m mypy backend` | 173 个源文件通过 |
| `python3 -m compileall -q backend` | 通过 |
| `npm run typecheck --prefix backend/omp/extensions/xhsagent-ext` | 通过 |

## 7. 实施与回滚

本轮仅增加读取 bundle 和 additive metadata，不需要迁移或 feature flag。若旧部署不支持
bundle API，前端继续使用 overview fallback；后端可回滚 route 注入参数而不影响已有
snapshot 数据。

## 8. Definition of Done

- [x] PRD、研究审计、context jsonl 和规范更新完成。
- [x] 关键接口均复用一个 bundle/单位适配器，无跨调用重复读取。
- [x] 自动化证据和提交记录写入任务目录，用户已有 lockfile 改动保持未提交。
