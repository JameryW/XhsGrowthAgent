# 第五轮历史质量数据一致性优化 PRD

状态：Implemented（2026-07-22）
关联任务：`07-22-history-quality-consistency-round5`

## 1. 背景与问题

第四轮已经让 Analytics、账户级历史质量和单篇详情从同一个 Creator Stats
snapshot bundle 读取，但审计发现仍有两个跨层边界：

1. `POST /api/evaluation/note` 及历史评估恢复接口仍通过 `get_note_stats` 单独读取
   一篇笔记，并以 `account_id + synced_at` 临时生成 `snapshot_id`。该 ID 不是完整
   Creator Stats population 的 canonical digest；在指标覆盖、同一时间戳覆写或并发导入
   后，质量评估可能带着旧评估结果，却被展示为当前 Analytics 快照。
2. `frontend/src/stores/analytics.ts` 的 `fetchReport`、`fetchPerformance` 仍直接提交
   异步结果，没有记录请求代际和请求账号。用户切换账号或周期时，迟到响应可能覆盖
   dashboard 已经加载的新账号数据，造成页面内报表、历史笔记与质量数据混批。

## 2. 目标

1. 历史 RQGM 评估在创建、缓存命中和恢复时都携带 Creator Stats canonical
   `snapshot_id`；评估结果的 source metadata 与分析/质量报告使用同一快照身份。
2. 当当前 bundle 快照与持久化评估来源不一致时，恢复接口将该评估标记为 stale，不能
   把旧结果冒充当前批次；历史审计记录仍保留，可显式重新评估生成新版本。
3. Analytics store 的 report/performance 独立 action 使用和 dashboard 相同的账号、周期
   与 request generation guard；空账号、账号切换和错误状态不能恢复旧响应。
4. 用最小新增字段保持旧数据库和旧客户端兼容：旧评估没有 canonical snapshot 时
   继续返回兼容的时间戳 ID，但新建/更新数据不得再丢失 bundle snapshot metadata。

## 3. 非目标

- 不改变 RQGM 维度、权重、阈值、评分算法或历史报告文案。
- 不把指标变化写入内容 hash 或改变评分维度；只把其视为 Creator Stats snapshot
  版本变化。latest 读取标记旧结果 stale，用户再次提交评估时才生成新版本。
- 不改变 API 路径、分页排序、旧字段名或 `frontend/pnpm-lock.yaml`。
- 不引入新的客户端缓存；不把完整笔记正文写入日志或 telemetry。

## 4. 一致性契约

### 4.1 Historical evaluation source

- `POST /api/evaluation/note` 从一个 `get_creator_stats_snapshot_bundle(account_id)`
  选择目标 note，并用该 bundle 的 notes/account 计算 `snapshot_id`、`data_as_of`。
- 评估持久化的 `result_json.source.snapshot_id` 是 canonical ID；`_evaluation_run_data`
  顶层 `snapshot_id` 优先复用该值。旧 run 没有该字段时才使用 timestamp-compatible
  fallback。
- 缓存命中必须保留同一 source metadata；恢复 latest 时重新读取当前 bundle，只要
  snapshot 不同就标记 stale，禁止静默复用旧评估。

### 4.2 Analytics request ownership

- `fetchReport` / `fetchPerformance` 在发起时捕获 account、period、generation；只有
  generation、active account 和 period 仍匹配时才提交 response。
- 无 active account 时清空对应数据和 snapshot metadata，不发请求；异常只更新当前
  request，不能把旧账号 loading/error 状态覆盖到新请求。
- 独立 action 写入的 report/performance snapshot metadata 与 dashboard 使用相同 API
  contract，前端不自行重算 snapshot。

## 5. 验收标准

- [x] 新建历史评估的 `source.snapshot_id` 与同时读取的 Creator Stats bundle 一致。
- [x] cache hit、latest restore 和旧 run fallback 的 snapshot/data_as_of 字段契约稳定；
  当前 bundle 变化会返回 `stale=true`，不误报 fresh。
- [x] report/performance 在账号或周期切换后的迟到响应被丢弃；空账号不发请求并清空状态。
- [x] 新增 backend/frontend 回归测试覆盖上述边界，既有持久化表和内存 fallback 均不破坏。
- [x] 相关后端单测、前端测试、类型检查、lint/format 通过；lockfile 改动保持未提交。

## 6. 实施方案

1. 在 evaluation route 增加 bundle-owned note reader 和 snapshot 提取 helper；创建评估
   时将 canonical snapshot 写入现有 `result_json.source`，不新增强制数据库列。
2. 抽取 run snapshot 解析逻辑，让 cache/latest/detail 统一输出 canonical ID；latest
   恢复将当前 bundle 与 run source ID 比对并调用现有 `mark_subject_stale`。
3. 为 Analytics store 的独立 report/performance action 复用 generation/account/period
   guard，保持 `fetchAllData` 的行为不变并补充空账号清理。
4. 补充 route、quality persistence 和 Pinia action 的回归测试，并更新跨层规范/研究记录。

## 7. 回滚与兼容

实现只使用现有 JSONB `result_json` 的 additive source 字段；旧表无需迁移。若旧服务返回
没有 `source.snapshot_id` 的 run，读取端保留旧 timestamp fallback；回滚 route/store
改动不会删除历史评估。无关的 `frontend/pnpm-lock.yaml` 不纳入提交。

## 8. 实现记录与验证证据

### 已实现

1. `evaluation.py` 新增 bundle-owned historical note reader；新建 RQGM run 将
   `result_json.source.snapshot_id` 与完整 Creator Stats digest 一起持久化，统一
   `_evaluation_run_data`、cache hit 和 latest restore 的 snapshot 输出。当前 bundle
   变更（包括同 timestamp 指标覆写）会通过现有 stale 审计机制阻断旧结果冒充 fresh。
2. Analytics store 增加跨 dashboard/report/performance 的 scoped request generation，
   独立 action 捕获 account+period，空账号短路并清空 account-scoped data，迟到响应和
   并发单端点响应均不能混合快照。
3. 更新数据库、质量、前端状态和跨层规范；新增 evaluation route/latest stale 测试与
   Analytics store account/period/concurrent response 测试。`frontend/pnpm-lock.yaml`
   的用户已有改动未纳入本任务。

### 自动化验证

| 检查 | 结果 |
| --- | --- |
| `python3 -m pytest -q tests/unit` | 1454 passed，2 个既有 warning |
| `pnpm --dir frontend test:run` | 50 个文件 / 594 tests passed |
| `pnpm --dir frontend type-check` | 通过 |
| `pnpm --dir frontend i18n:check` | 1944 keys consistent |
| `pnpm --dir frontend build` | 通过（保留既有 chunk 大小提示） |
| `python3 -m ruff check backend tests/unit` | 通过 |
| `python3 -m ruff format --check backend tests/unit` | 307 个文件已格式化 |
| `python3 -m mypy backend` | 173 个源文件通过 |
| `python3 -m compileall -q backend` | 通过 |
| `npm run typecheck --prefix backend/omp/extensions/xhsagent-ext` | 通过 |

## 9. Definition of Done

- [x] PRD、研究审计、context JSONL 和必要规范更新完成。
- [x] evaluation 与 Analytics 的 canonical snapshot contract 只有一个实现来源。
- [x] 自动化验证证据和提交记录写入任务目录，用户已有 lockfile 改动保持未提交。
