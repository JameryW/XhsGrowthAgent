# PR 草稿 — P1a: Kernel 最小骨架 + State 三层拆分

> 开 PR 时复制以下内容。分支 `feat/p1a-state-layers`（10 提交，基于 main tip e4fd5b52，
> 零冲突可直接 merge）。

## 标题

```
P1a: Kernel minimal skeleton + State three-layer split (ArtifactStore / EventStore / hydration)
```

## 正文

### Summary

LangGraph Workflow 承担了过多 Kernel 职责（父任务 09-11-runtime-upgrade 架构评估）。
本 PR 落地 P1a 收敛后的 3+2 件（2026-09-13 拍板）：**ArtifactRef + ArtifactStore**
（LangGraph BaseStore + façade，ns `("artifacts", thread_id, kind)`）+ **EventStore**
（workflow_events 表，PG/内存双后端）+ **RuntimeState 字段矩阵** + **hydration 层**。

- 大业务体（copy/visual/trend/brief/ripple 向量/笔记/版本/爆款等 15 字段）外置
  ArtifactStore，checkpoint 只留 `artifact://` 引用与路由 meta
  （versions_meta / blogger_notes_meta / trend_summary）。
- 遥测（performance_log）出 checkpoint，落 workflow_events 表。
- 死字段（messages、state content_history）删除。
- 6 个读面（/status live+history-file、/history、recover、showcase、realtime）收口
  hydration；/status 契约不变（D4），前端零改动。
- 迁移 = 一刀切：新 run 新 schema，存量 checkpoint 不重写，旧线程透传零 store 往返（D1）。

### 效果（research/checkpoint-size-bench.md）

| 指标 | pre | post | 变化 |
|---|---:|---:|---|
| 最终 superstep 序列化体积 | 23,908 B | 5,418 B | **-77.3%** |
| 累计写放大（15 superstep） | 157,422 B | 38,768 B | **-75.4%** |
| 净持久化（含 ArtifactStore 20,516 B） | 157,422 B | 59,284 B | **-62.3%** |

### 提交（10）

| commit | 内容 |
|---|---|
| 04e951fa | S1 死字段删除 + 六读面收口 hydration 层 |
| 65987f69 | S2 遥测外置 workflow_events |
| 1c361712 | S3 ArtifactStore 骨架 + 写/读接缝 + meta 摘要 |
| 1131fef3 | S4-0 路由读写缝补齐（~15 读面 resolve、4 写面 refify） |
| 7515d7cc | S4-1 trend_data 外置 + trend_summary 路由 meta |
| 4bc63c9b | S4-2 ripple 向量外置 + ripple-retry 路由缝（修复 ref'd 线程 retry 永远 skipped 的真 bug） |
| bb7b02b5 | S4-3 brief_content 外置 + /status label/history/init/upload 四缝 |
| cbeb32be | S4-4 P0 契约等价测试（publish_id 双跑同值 / dry-run / fail-closed） |
| 554f7aef | S4-5 legacy 线程四读面回归（零 store 往返钉成契约） |
| a5161b94 | S4-6 checkpoint 体积基准（脚本 + 报告） |

### 测试证据

- 全量 `pytest tests/unit tests/integration`：**2453 passed / 3 skipped**（基线零回归）。
- mypy strict 零错（`uv run mypy backend --python-version 3.12`）。
- ruff check / format 干净。
- 新增测试 9 个文件（route seams 672 行、legacy read faces 472 行、hydration 391 行、
  P0 契约等价 236 行、events 132 行、trend/brief seam 174 行等）。

### 红线核对

- 只增删 checkpoint 字段声明，未动 reducer 语义（artifacts/versions_meta/
  blogger_notes_meta/trend_summary 的 reducer 均为新增声明）。
- 未引入 RunContext/Task/ActionIntent（D5——分别留给 P1b/P1c/P2a）。
- /status 响应契约不变（D4）；spec 已更新（workflow-state.md 三层模型 + Artifact seams 契约段）。

## 用户操作（合并剩余步骤）

```bash
git push -u origin feat/p1a-state-layers
# GitHub: base main ← compare feat/p1a-state-layers → 开 PR（正文复制上文）→ merge
# 合并后如需同步本地：
git checkout main && git pull && git branch -d feat/p1a-state-layers
```

注：本地 main 领先 origin/main 2 个提交（journal 归档），push 分支时可一并 `git push origin main`。
