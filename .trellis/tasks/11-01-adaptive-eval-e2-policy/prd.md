# feat(harness): P3/E2 可注入策略接口——默认即现行行为（票 5ce）

> 提案 E2 的定义是「把四个决策点抽成可注入策略对象，默认实现 = 现行行为，**无行为变化**」。
> 本票只交付接口与默认实现，**不接线任何生产调用点**——接线（默认值是否允许被变体替换）
> 依赖提案第 6 节问题 5/6 的拍板。

## 1. 四个决策点与默认答案（逐项委托，不复制字面量）

| 决策点 | `DefaultHarnessPolicy` 的答案 | 委托对象 |
|---|---|---|
| 模型路由 | `route_model(task_type)` | `backend.config.models.resolve_model_id` |
| 上下文预算 | `context_budget()` → `None` | 现行 agents 调 `compile_prompt` 不传 budget |
| 工具并发/超时 | `tool_limits(capability)` | 工具目录 `ToolSpec.max_concurrency` / `effective_timeout_s` |
| 升级/降级触发 | `escalation_targets()` → `()` | 今天只有 `MODEL_FALLBACKS` 兜底，没有升级路径 |

## 2. 交付

- `backend/harness/policy.py`：`HarnessPolicy`（runtime_checkable Protocol）、
  `ToolLimits`、`DefaultHarnessPolicy`、`default_policy()`、`describe(policy)`；
- `backend/harness/__init__.py`：公开导出；
- `tests/unit/harness/test_policy.py`：8 个用例。

`describe()` 输出 `models` / `context_budget` / `escalation` / `tool_limits` 的 JSON 快照，
E3 用它做 baseline 与 variant 的 diff（快照相等 = 变体没改东西；差异点直接命名决策）。

## 3. 测试（8 个）

1. 默认策略满足 Protocol；
2. 每个 `TaskType` 的路由都等于 `resolve_model_id`；
3. 上下文预算为 `None`（带/不带 phase）；
4. 升级列表对所有 TaskType 为空；
5. `xhs.publish` 的 limits 等于目录 spec；
6. 未知名能力抛 `UnknownCapabilityError`（不编造）；
7. `describe` JSON 可序列化且与直接调用一致；
8. 子类化变体改路由后，snapshot 的 models 不同、tool_limits 相同。

## 4. 验证

- `tests/unit/harness` 8 passed；mypy `backend`（3.12 target）264 files 0 issues；
- `tests/unit/scripts` 门禁与全量 pytest 见 notes；
- 未接线 → 默认行为零变化（生产代码不存在对该接口的引用）。

## 5. 不做什么

- 不接线 router/compiler/gateway；不提供任何变体实现；不改默认模型表；
- 不做 E3 门禁脚本、不做 L3 端到端。
