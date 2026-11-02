# fix(eval): 复核两处高危——artifact ref 内容解析 + 第二批真实 schema 脱敏（票 5cm）

> 第二轮独立复核（验证 5cj/5ck 的修复）发现：之前修的 15 条里多数已 VERIFIED，但仍有
> **2 个新高危**和若干残留。本票全部修复，不靠文档绕过。

## 1. 高危修复

### H1 真实语料可能完全没有内容（pre-existing，最严重）
每个 graph 节点都被 `artifact_seam` 包了一层，`refify_updates` 把 `copy_content`/
`visual_plan`/`draft_content`/`shooting_plan`/`trend_data`/`viral_posts` 移进
**Artifact Store**（`artifacts` 映射里只留 ref）。抽取器此前只读 checkpoint 的
`channel_values` → 真实语料里没有标题/正文，E4 裁判拿到的是空内容。

修复：
- 新增 `--store-uri`（与 graph 同一个 Postgres），用 `resolve_state` 解析每个 ref；
- 无 store 或解析后仍有字段缺失 → **跳过该记录并计入 `unresolved_artifacts`**，
  CLI 打印警告；绝不写出"看起来合法但没内容"的 fixture；
- `artifacts` 引用映射本身在脱敏阶段丢弃（对评测无用）；
- 测试：无 store 时跳过并计数；有 `InMemoryStore` + `put_artifact` 时解析出真实标题、
  且 fixture 里没有 `artifacts` 键。

### H2 第二批真实 schema 身份字段仍泄漏
`platform_post_id`（真实笔记 id，可还原 URL）、`run_id`、`engagement_actions[].target_id`、
`blogger_notes_meta.ids`、`publish_confirmation.confirmer`、`publish_options.confirmed_by`、
内联 `user_viral_links`、复数 `*_urls`/`*_links`、UNC `\\fileserver\...`、`/data/...`、
`file://...` 全部原样保留，且计数为 0。

修复：新增假名键（post/run/target/id/user）；URL 后缀加复数；绝对路径正则覆盖 UNC、
`file://` 与更多根；回归用例播种这些真实字段并断言无明文、计数非零。

## 2. 残留中危修复

| 问题 | 修复 |
|---|---|
| `manifest.sha256` 可选：删掉它就能改 manifest 而不被发现 | 缺失即红；给了 `--expect-manifest-sha256` 时以该值为准 |
| `extractor_version` 写入但 gate 不校验 | gate 校验；`EXTRACTOR_VERSION` 升到 3 |
| `describe()` 不采样逐 phase 预算，阶段专属变体在 diff 里不可见 | `describe` 增加 `context_budgets`（覆盖全部 WorkflowPhase + 空 phase）；gate 校验并计入 diff |
| policy 类型检查仍宽松（`("",)` escalation、空 capability、负并发） | 逐项收紧并加回归 |
| `JudgeBudget(used=-1)` 可绕过、`max_calls` 可改 | `used` 边界校验、`max_calls` 构造后只读、`consume` 检查计数器 |
| `judge=human` 时 `XHS_EVAL_LIVE` 不需要 | 任何 live 运行都要武装（工作流同样花模型调用） |
| 计划里的 `estimated_total_calls` 被当成"上限" | CLI/JSON 明确标注是**估算**（F7 无 run 级预算），要求记录实测数 |
| phase 过滤前就 `seen.add`，线程的最新 checkpoint 不在目标 phase 时整个线程被丢 | 只在接受 fixture 后标记 seen；新增"跨 phase 找最新"用例 |
| Postgres 驱动错误（`psycopg.InterfaceError`）不走 `ConnectionError` → 直接 traceback | `_is_source_error` 识别 psycopg/asyncpg/aiosqlite 模块并干净退出 1 |

## 3. 文档同步

- §6.5：artifact 解析要求、第二批字段、复数 URL、UNC/file://、`unresolved_artifacts`、
  HMAC 是"声明不可验证"、指纹必需；
- §6.7：extractor 版本校验、`context_budgets`、测试数 29；
- §6.9：`used` 边界与 `max_calls` 只读；
- §6.10：任何 live 运行都要武装、估算不是上限；
- runbook：`--store-uri`、`unresolved_artifacts` 警告处理、人审也需武装、预算口径改为总量估算。

## 4. 验证

- fixtures 21、gate 29、judge 14、plan_l3 15、policy 9；`tests/unit/scripts` 全量、
  mypy、全量 pytest、CI 见 journal。

## 5. 不做什么

- 不接线生产默认；不实现 run 级预算字段（F7，仍是记录在案的 SKIP）；
- 不把 hmac 模式做成可验证（密钥不能进语料，文档写明这是声明）。
