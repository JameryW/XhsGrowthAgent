# chore(ci): 对齐 ruff format（本轮迁移改动文件）（票 5bj）

> CI 的 `lint-format` 作业在 clean checkout 上跑 `ruff check .` 与 `ruff format --check .`。
> 本轮迁移（票 5ba–5bi）改动了 69 个 `.py` 文件；用 ruff 0.16.1 在 LF 归一化后复核，
> 其中 5 个存在**真实格式偏差**（其余 3 个只是本地 CRLF/mixed-ending 噪声）。
> 本票只做格式化对齐，不改任何语义。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| CI 运行 `ruff format --check .`（Python 3.11，依赖按 pyproject 解析） | `.github/workflows/ci.yml` 的 lint-format 作业 |
| 本轮改动包含 69 个 `.py` 文件 | `git diff --name-only origin/main..HEAD` + 工作树 |
| LF 归一化后 5 个改动文件 would-reformat | `ruff format --check` on LF copies |
| 其余 6 个未改动文件只是本地行尾产物（LF 副本已 formatted） | 同法复核 `origin/main` 内容 + LF 副本 |
| 所有 69 个改动 `.py` 文件在 LF 下 format-clean（格式化后） | 本轮复核输出 |

## 2. 决定（locked）

1. 只格式化**本轮改动过的**文件；未改动的上游文件不动（本地行尾差异不入 diff）。
2. 不改变任何语义/测试断言；仅行的合并/拆分。
3. 复核方法：把每个改动文件按 LF 写出到临时目录再 `ruff format --check`，
   排除 Windows CRLF/mixed-ending 的假阳性。

## 3. 结果（2026-11-01）

- [x] 8 个改动文件 `ruff format`；其中 5 个有真实 diff（+6/−15），3 个仅行尾归一
- [x] 69 个改动 `.py` 文件在 LF 下全部 format-clean
- [x] `ruff check` 全绿
- [x] 未改动上游文件的 6 条本地 format 提示确认是行尾假阳性（LF 副本通过）
- [x] 定向 344 passed；全量结果见 notes

## 4. 不做什么

- 不格式化未改动文件（避免无关 diff 噪音）；不改 CI 配置或 ruff 版本。
