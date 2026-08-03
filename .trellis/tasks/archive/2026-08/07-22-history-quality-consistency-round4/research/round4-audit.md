# 第四轮一致性审计记录

## 数据链路

```
creator_stats bundle import
  → creator_stats.list_all_note_stats / get_creator_stats_snapshot
  → analytics _merge_imported_posts + report/performance/dashboard
  → frontend Analytics/Evaluation canonical reader
  → quality report and OMP tools
```

第三轮只修复了 canonical page 内部的跨连接竞态。代码图和 route tracing 发现报告类接口
仍有如下顺序：

```
notes = await list_all_note_stats(account_id)
report = analyze/build(notes)
snapshot = await get_creator_stats_snapshot(account_id)
```

导入在两个 await 之间提交时，报告的 `notes_analyzed`、均值、top note 与 response
`snapshot_id` 不属于同一次导入。质量 endpoint 的问题最直接；dashboard/report/performance
通过 `_merge_imported_posts` 也复现同样窗口。

## 前端审计

`frontend/src/api/analytics.ts:getCreatorNotes` 的两个 legacy fallback 都映射了
`data_as_of`，但只有 feature flag 关闭的分支映射 `snapshot_id`；canonical 404/network
fallback 分支遗漏它，也没有传 `engagement_rate_unit`。这会让 `hasSnapshotMismatch` 在旧
服务灰度期间失效，并让百分比适配退回数值猜测。

`Analytics.vue` 和 `EvaluationView.vue` 自己的 `getCreatorStats` fallback 已包含
`snapshot_id`，因此应统一 API client helper，避免第三份映射继续漂移。

## OMP 审计

`xhs_creator_stats` 当前始终使用 `rate <= 1 ? rate * 100 : rate`。当前 API 已声明
`engagement_rate_unit="fraction"`，显式读取该字段可以消除 `1.0` 边界的歧义，同时保留
无单位旧服务的 compatibility fallback。

## 验证计划

- DB bundle memory/legacy Postgres transaction 回归；
- quality route 用同 bundle 的 notes + metadata 断言；
- dashboard/report/performance 断言注入 notes 与 snapshot metadata 不重复读取；
- frontend API fallback 断言 snapshot/unit 保留，OMP typecheck 与 formatter 边界测试；
- 全量后端单测、前端测试/type-check/build、OMP typecheck。
