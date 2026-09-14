### Summary

P1b Context Compiler 的 S2 切片（task `09-11-p1-context-compiler`，决策 info.md D1'-D6'）。
基于 S1 骨架（随 P1a 快照入库），本 PR 让 recall 成为**一条可观测的管线步骤**。

> 堆叠 PR：base 为 `feat/p1a-state-layers`（S1 骨架所在），P1a 合入后请将 base 改为 `main`。

### 内容

- **`backend/context/retrieval.py`**：
  - `recall_namespaces()`：多 namespace **asyncio 并行** recall；每个结果强制携带
    D6' 降级信号——store 缺失 → `degraded("store_unavailable")`、异常 → `degraded`
    （error 摘要，**根治 base.py §十五"异常→warning+[]"的静默降级**）、
    空 → `empty`、命中 → `hit`。
  - `item_to_context_item()`：记忆记录 → ContextItem 确定性映射（body 键优先级
    insight/preference/content/summary/note/text + sorted-key JSON 兜底；
    ts 键优先级解析，失败安全置 None）。
  - 未知 namespace 在任何 store 调用前 fail-fast（P0-W2 延续）。
  - 事件面：`kind="context"` 遥测落 P1a workflow_events 通道
    （per-ns mode/count/error/elapsed_ms，best-effort，永不破坏 recall）。
  - `apply_freshness_decay()`：确定性新鲜度衰减
    （confidence *= 0.5**(age/half_life)，无 ts 不衰减，未来 ts 钳 0，纯函数）。
- **`backend/db/workflow_events.py`**：EVENT_KINDS 增补 `"context"`（纯增量，无校验面依赖）。
- **范围**：additive-only——agent 仍走 `BaseAgent._recall_memory`，S4 迁移按
  consumer-map 销号顺序逐个切换；本 PR 零行为变化。

### 测试证据

- 新增 `tests/unit/context/test_retrieval.py` ×15（FakeStore 脚本化：
  hit/empty/双 degraded/并行调用数/未知 ns 零 store 调用/事件落库断言/
  默认不发事件/freshness 三例 + 非法 half_life）。
- 全量：**2492 passed / 3 skipped**（P1a 基线 2477 + 15，零回归）。
- mypy strict 零错（187 文件）；ruff check 干净。

### 红线核对

- 不动 agent 现有路径（S4 才迁移）；不动 /status 契约；不引入 LLM rerank。
- RunContext 不进 checkpoint；checkpoint 字段零变化。
