# P2：主链发布策略门禁（复用 `creator_agent.policy` 同一规则）（票 5bd）

> 上下文：P1（5ba/5bb/5bc）让主链产出 intent；P2 要求主链在**提交任何效果之前**
> 用**同一份**发布策略做评估，拒绝时返回 typed 结果且不写回执。
> 禁止复制规则表，禁止为了让主链能用而伪造 `ActionIntentRequest`（伪造 `decision_id`
> 就是发明身份）。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 策略引擎是纯函数 + 快照 | `backend/creator_agent/policy.py`（`evaluate_action_policy`） |
| 引擎按 capability 收集快照；PUBLISH 才咨询风险 gate | `build_action_policy_snapshot` / `_SIDE_EFFECTING_CAPABILITIES` |
| checkpoint → 策略上下文已有单一投影 | `policy_context.py`（`_stamped_eligibility` / `_niche_from_values` / `_auto_publish_from_values` / `_extra_from_values` / `state_is_commercial`） |
| 主链已有 resolved state 与显式 principal | `run_publish`（P1a） |
| 现有拒绝形状：typed `error_type` + 结构化 `recovery` | `_missing_publish_credential` / `_missing_cdp_endpoint` |
| 现有 blocked 事件是 kind:"action" 遥测，不是回执 | `_record_publish_blocked` → `emit_events` |

## 2. 决定（locked）

1. 在 `policy.py` 提取 `build_policy_snapshot_for_capability(capability, account_id, ...)`，
   `build_action_policy_snapshot` 委托它 —— 两条调用方共用同一条收集路径，主链不伪造 request。
2. 在 `policy_context.py` 提取公开的 `action_policy_context_from_values(values)`，
   checkpoint loader 复用它 —— 主链已有 state，不需要重读 checkpoint，也不复制投影规则。
3. `run_publish` 在 **grant 检查之后、PREPARED/账本之前**运行策略：
   `build_policy_snapshot_for_capability(PUBLISH, principal.account_id, policy_context=...)`
   → `evaluate_action_policy`。拒绝：typed `publish_result`
   （`error_type="publish_policy_denied"`、verdict 的 `policy_id`/`retry_after_seconds`、
   结构化 recovery）+ 一条 `publish_blocked` 事件（`reason="publish_policy_denied"`），
   **不写 PREPARED、不 claim 账本、不产 intent、不写回执、不调 Gateway**。
4. 部署本体（无 account）不进入该策略：引擎按契约为 account-scoped，没有 account 就没有
   可评估的账号级判定；该路径仍由人工 review 审批把关，也不构造 account-scoped intent
   （与 P1b-2 同一条边界）。**不为通过门禁而发明账号 id。**
5. claim 不变：直调仍 3、构造点仍 2、生产者仍 1。

## 3. 要求

1. `backend/creator_agent/policy.py`、`policy_context.py`、`__init__.py` 导出新共享函数。
2. `backend/state/events.py`：新增 `BLOCKED_PUBLISH_POLICY = "publish_policy_denied"`，
   `tests/unit/state/test_events.py` 的封闭词表同步（五因 → 六因）。
3. `backend/agents/publisher.py`：gate + `_evaluate_mainline_publish_policy` +
   `_publish_policy_denied`；错误类型常量 `_PUBLISH_POLICY_DENIED`。
4. 测试：策略拒绝（stamped eligibility）、风险冷静期（typed + retry hint）、拒绝时零副作用
   （无 PREPARED/无 Gateway 调用）、部署主体边界、capability 快照 == request 快照、
   非副作用 capability 不咨询 gate、values 投影字段/缺省语义。
5. 文档：`docs/publish-action-protocol.md` P2 段落记录落地与边界；claim 不变。
6. 验证：定向 + 全量 + doc claim 重算 + ruff 绿。

## 4. 结果（2026-11-01）

- [x] 共享快照/投影函数；主链 gate 位于任何持久副作用之前
- [x] 拒绝：typed result + blocked 事件；无 PREPARED/账本/intent/回执/Gateway
- [x] 部署主体边界有测试并有文档
- [x] 定向：run_publish 58 passed（含 3 个新门禁用例）；新用例 46 passed；见 notes 全量
- [x] claim 未变（直调 3 / 构造点 2 / 生产者 1）

## 5. 不做什么

- 不切执行器（P3）、不改 `ActionIntentRequest`/公开 API、不改幂等语义。
- 不覆盖部署本体发布的策略评估（引擎契约所限，文档化为边界）。
