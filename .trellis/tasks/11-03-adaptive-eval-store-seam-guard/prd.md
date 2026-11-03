# feat(eval): artifact 写缝回归 + `--store-uri` 入口契约 + 扫描上限（票 5cp）

> 5cm 修的 H1（artifact ref 内容解析）只用手写的 `put_artifact` 测过，**没有证明
> 与 graph 真实写缝一致**；`--postgres-uri`/`--store-uri` 依赖 langgraph 的
> `from_conn_string` 入口，升级后静默消失不会被发现；`alist` 默认读取**全部**
> checkpoint，繁忙部署上是一次全表扫描。本票把这三处补上。

## 1. 交付

| 位置 | 变化 |
|---|---|
| `tests/unit/scripts/test_eval_fixtures.py` | +3 用例：① 用 `refify_updates`（graph 的真实写缝）写入 store 再抽取，断言内容被解析、`artifacts` 被丢弃；② 断言 `AsyncPostgresSaver.from_conn_string` 与 `AsyncPostgresStore.from_conn_string` 存在（CLI 依赖的契约）；③ `--scan-limit` 命中时只读 N 条并记 `skipped.scan_capped=1` |
| `scripts/eval/extract_fixtures.py` | 新增 `--scan-limit`：作为 `alist(limit=...)` 传入，限制**读取**的 checkpoint 数（不是 fixture 数）；命中时记 `scan_capped` 并打印"语料可能不完整"警告；docstring 说明这与 `--limit` 的区别 |
| `docs/adaptive-harness-eval-plan.md` §6.5 | 真实来源/预算行补 `--scan-limit` 与全表扫描说明；fixtures 用例数 21→24 |
| `docs/adaptive-harness-runbook.md` | 抽取命令补 `--scan-limit` 建议与 `scan_capped` 警告处理 |

## 2. 为什么重要

- **写缝一致**：graph 的节点更新经 `artifact_seam` → `refify_updates` 写入
  `("artifacts", thread_id, kind)` 命名空间；抽取器读的是同一个 BaseStore 接口。
  如果只用 `put_artifact` 直写测试，两者的 ref 形状/命名空间一旦分叉就测不出来。
- **入口契约**：`from_conn_string` 是 langgraph 的公开入口；依赖升级若移除/改名，
  我们要在测试里立刻知道，而不是在部署现场发现 live 抽取打不开库。
- **扫描边界**：`alist` 无 limit 时会加载所有线程所有 checkpoint；`--limit` 只限制
  写出的 fixture 数。生产库需要显式的扫描上限，并且"可能不完整"必须写进产物
  （`scan_capped`），不能静默。

## 3. 验证

- `test_eval_fixtures.py`：24 passed（新增 3 个）
- `tests/unit/scripts` 全量、ruff、全量 pytest、CI 见 journal

## 4. 不做什么

- 不改 graph 的写缝、不改 store 命名空间；
- 不把 `--scan-limit` 设成默认值（默认仍读全部，避免悄悄丢线程）。
