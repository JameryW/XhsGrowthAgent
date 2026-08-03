# 第三轮一致性审计记录

## 审计范围

沿着 `Creator Stats import → backend/db/creator_stats.py → analytics API → Analytics/Evaluation
分页与质量报告` 追踪同一账号的事实流，重点检查前两轮之后仍可能造成 snapshot 混批的边界。

## 发现

`list_note_stats_page` 的 Postgres 分支原来在连接 A 中执行：

1. 完整过滤 `COUNT(*)`；
2. 当前 cursor 页 `SELECT ... LIMIT`；
3. 退出连接 A。

随后它调用 `get_creator_stats_snapshot`，由连接 B 分别读取 `creator_account_stats` 与完整
`creator_note_stats`。在 2 和 3 之间发生一次 bundle import 时，响应中的 items 可能来自
旧提交，而 `snapshot_id`/`data_as_of` 来自新提交。默认 READ COMMITTED 即使复用一条连接，
每条 SQL 也可能取得不同 statement snapshot，因此必须显式使用 transaction-level
`REPEATABLE READ`。

## 方案

- 抽取 `_fetch_account_stats`、`_fetch_all_note_stats` 和共享 SELECT/parser helper。
- canonical page 与 snapshot reader 均打开显式 `REPEATABLE READ` transaction，并在首次
  SELECT 前设置隔离级别。
- page 在同一 cursor 上完成 count、selected rows、account/full population 读取，然后用
  `build_creator_stats_snapshot_metadata` 计算 metadata；不再调用另一个连接的 public
  snapshot reader。
- memory fallback 与 legacy tuple/dict row parser 保持原路径。

## 验证证据计划

- Postgres mock 断言 page 与 snapshot 各自进入事务，且 page 的完整集合读取发生在同一连接；
- 600 条无账户 legacy rows 的 total/cursor/snapshot 回归；
- 同时间戳指标覆盖仍改变 snapshot；
- `pytest tests/unit/api/test_quality_consistency_backend.py`、Ruff、mypy、compileall。
