# 第三轮历史笔记数据一致性优化 PRD

状态：Implemented（2026-07-22）
关联任务：`07-22-history-quality-consistency-round3`

## 1. 背景与问题

前两轮已经统一了 Creator Stats 的 canonical cursor、完整 note 集合快照摘要、
Analytics/质量评估的 `snapshot_id`，并把原始互动率固定为 fraction。第三轮代码审计发现
Postgres canonical 分页仍有一个跨语句竞态：分页函数先在一个连接读取 `total` 和当前页，
连接释放后再通过另外的连接读取账户行与完整 note 集合生成快照。导入恰好发生在两次读取
之间时，响应可能把旧页数据和新快照 ID 配在一起；后续请求会因此错误地拒绝或接受 cursor。

这不是前端格式问题，而是数据库读快照边界没有覆盖“页数据 + 完整版本元数据”全部事实。

## 2. 目标

1. Postgres canonical 分页的过滤总数、选中行、账户行和完整 note 集合在同一个
   `REPEATABLE READ` 只读事务中读取，并由同一个快照摘要函数生成响应 metadata。
2. `get_creator_stats_snapshot` 也在同一可重复读事务内读取账户与完整 note 集合，避免
   质量评估/Analytics 单次响应内部看到不同提交批次。
3. 抽取账户/note 行读取与解析 helper，避免分页、完整 reader 和 snapshot reader 复制 SQL
   或字段映射；保留 memory fallback、旧 Postgres（无账户行）和旧 DTO 字段兼容。
4. 用回归测试证明分页不会跨连接拼接快照，并继续覆盖 600 条 legacy notes、完整 total、
   tied cursor 和 snapshot 稳定性。

## 3. 非目标

- 不修改质量评估算法、RQGM 维度、阈值或历史评分语义。
- 不改变 cursor 编码、排序、API 路径、字段名称或已有 fraction 展示值。
- 不在读取路径写入数据库，也不引入新的缓存或浏览器同步。

## 4. 数据与接口契约

### 4.1 Canonical 历史分页

`list_note_stats_page(account_id, cursor, limit, published_from, published_to)` 仍按
`(published_at DESC, note_id DESC)` 排序；`total` 是完整过滤集合的数量，与 cursor remainder
无关。每一页的 `snapshot_id`、`data_as_of`、`note_count` 和 note facts 必须来自同一次
数据库事务。`engagement_rate_unit` 继续为 `fraction`。

### 4.2 Snapshot reader

`get_creator_stats_snapshot(account_id)` 是 Analytics、质量评估和详情接口的存储层来源；
Postgres 路径在一条 `REPEATABLE READ` 事务内读取账户和完整 note 集合。无账户行时仍以完整
note 集合推导快照，不得只使用当前页或触发同步。

### 4.3 降级与兼容

没有 Postgres 时沿用进程内 memory reader；空账号返回空快照；tuple/dict 两种 psycopg
row 形态、历史 `raw_json` 字段和旧客户端 additive metadata 保持兼容。

## 5. 验收标准

- [x] canonical Postgres page 的 count、selected rows、account row、full notes 共享同一
  连接与 `REPEATABLE READ` transaction；不再在读页后调用另一个连接的 snapshot reader。
- [x] legacy Postgres（无账户行、600 notes）仍返回完整 total，跨页无重复/漏项，page 与
  snapshot metadata 一致。
- [x] 同步时间相同但 note 指标被覆盖时 snapshot 仍变化；页内不会出现旧 rows + 新 ID。
- [x] memory fallback、旧 tuple rows、空账号和 API additive 字段的既有测试保持通过。
- [x] 后端单测、Ruff、格式、mypy、compileall 通过；研究、实现和验证证据写入任务目录。

## 6. 实现记录与验证证据

### 已实现

1. `backend/db/creator_stats.py` 抽取账户/note SELECT 与 row parser；Postgres
   `get_creator_stats_snapshot` 和 `list_note_stats_page` 使用显式 `REPEATABLE READ`
   事务，并由同一 cursor 读取完整 population，分页不再调用第二连接拼接 snapshot。
2. `tests/unit/api/test_quality_consistency_backend.py` 为 600 条无账户 legacy rows 增加
   事务进入次数及隔离级别断言，同时保留 cursor、同时间戳覆盖和 memory fallback 回归。
3. `.trellis/spec/backend/database-guidelines.md` 固化“同事务读取 page + snapshot”的
   规范，防止未来重新引入跨连接竞态。

### 自动化验证

| 检查 | 结果 |
| --- | --- |
| `python3 -m pytest -q tests/unit` | 1449 passed，2 个既有 warning |
| `python3 -m ruff check backend tests/unit` | 通过 |
| `python3 -m ruff format --check backend tests/unit` | 307 个文件已格式化 |
| `python3 -m mypy backend` | 173 个源文件通过 |
| `python3 -m compileall -q backend` | 通过 |

## 7. 灰度与回滚

改动只收紧数据库读取边界，不需要 feature flag 或数据迁移。若线上数据库不支持
`REPEATABLE READ`，可回滚本次 reader 代码到上一稳定版本；不会删除已持久化的 snapshot_id，
旧客户端仍可读取既有字段。

## 8. Definition of Done

- [x] PRD、研究审计、`implement.jsonl`、`check.jsonl` 完整。
- [x] canonical page 与 snapshot reader 复用同一 SQL/parser helper。
- [x] 回归测试覆盖事务边界和 legacy 分页场景，且无 lockfile 等无关文件被提交。
