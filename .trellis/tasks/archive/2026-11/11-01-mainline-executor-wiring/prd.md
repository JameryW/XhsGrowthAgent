# P4 分支 B slice3：mainline 执行段切到 execute_action（票 5bs）

> 分支 B 的主切换：有 durable mainline intent 时，dispatch 由控制面执行器完成，
> 主链保留 identity / 内容解析 / PREPARED / 自己的账本 claim 与后续结果处理。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 主链在 `EffectLedger.begin` 之后才 dispatch | `backend/agents/publisher.py` `_run_publish_attempt` |
| B2 已把 intent 提前到 claim 之前，且 producer 返回 `ActionIntent \| None` | 票 5bo |
| executor 可接 caller-supplied request（含生成封面），并逐字段绑定校验 | 票 5br |
| executor 的 receipt 可映射平台审计字段（published_at/error_type/recovery/result_known） | 票 5bn |
| receipt 为 attempt 级，FAILED 可无 force 重试、force 强制新 attempt | 票 5bq |

## 2. 决定（locked）

1. `intent is not None` → `_execute_publish_via_executor(...)`：
   - `CreatorAdvisor(DurableCreatorAgentRepository(), artifact_store=None,
     publish=gateway_publish_dispatcher(gateway=runtime.tools, granted_scopes=granted))`；
   - `execute_action(intent.account_id, intent.action_id, force=force_publish,
     request=publish_request)`；
   - `_result_from_receipt(receipt)` 映射回 `publish_result` 的既有键。
2. `artifact_store=None` 是刻意的：主链已经用 `publish_id` 账本 claim 过，executor 不再
   重复 claim（一次发布只有一个账本；两个 namespace 的 claim 崩溃后可能互相看不见）。
3. 无 intent（无审批决策/部署 principal 等）→ 保持原直调 `runtime.tools.invoke` 路径，
   行为逐字节不变（这也覆盖"此刻无法铸造身份"的合法场景）。
4. dispatch 之后的一切（unknown 判定、错误分类、ContentHistory、ledger 结算、force
   一次性清理）继续留在主链，不进入执行器。
5. executor 抛出的异常沿用主链现有 except 语义（timeout → unknown，其它 → failed）。

## 3. 要求

1. `backend/agents/publisher.py`：producer 返回值捕获、执行分支、`_execute_publish_via_executor`、
   `_result_from_receipt`。
2. 测试：
   - approved publish 走执行器：1 条 receipt（attempt=1、SUCCEEDED、note_id=p_grant）、
     Gateway 只调一次、publish_result 从 receipt 读回；
   - 被账本拦截的重复发布：第二条不产生新 receipt（执行器在 claim 之后）。
3. `docs/publish-action-protocol.md`：记录 B3 落地与剩余 B4。
4. 验证：定向 + 全量 + ruff。

## 4. B4（同票收口）

1. claim 表新增：`mainline_direct_publish_invocations = 1`（只剩无 intent 回退直调）与
   `mainline_executor_dispatch_sites = 1`（唯一交付点），均带区分性阳性对照
   （docstring/注释提到不算调用）。
2. `docs/agent-os-upgrade-2026q4.md` 接入边界行同步 B3 切换。
3. 文档末尾记录 B1–B4 全部落地。

## 5. 结果（2026-11-01）

- [x] 执行段切换（有 intent 时）
- [x] 两个新用例通过；全量结果见 notes
- [x] 无 intent 路径不变（既有 63 个 run_publish 用例全绿）

## 5. 不做什么

- 不把 executor 的账本再叠一层（见决定 2）；不改 HTTP 接口；不改无 intent 路径。
