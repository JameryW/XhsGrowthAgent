# P2a — Creator Action 模型融入主链

## Background

父任务 `09-11-runtime-upgrade` 的 P2a：

> Publisher 改造为 Generate → PublishIntent(artifact_id + content_hash + account) → Policy Engine
> → Human Confirm → Action Executor → Tool Gateway → ExecutionReceipt；复用 creator_agent 的
> ActionIntent/Receipt 实现为全局执行协议；重要 Decision 一律产 immutable DecisionRecord。

依赖 P1a ArtifactRef + P0/P1c，均已合入。

## 现状侦察（2026-09-15，逐条对代码核实）

**结论先行：控制面已经存在，缺的不是"建协议"，而是四件具体的事** —— `PUBLISH` 能力、
Policy Engine、能产生外部副作用的执行器、主链接线。

| 既有资产 | 位置 | 状态 | 对 P2a 的含义 |
|---|---|---|---|
| `ActionIntent` / `ActionResolution` / `ActionExecution` | `creator_agent/models.py:553-598` | **已有** | 全局执行协议**不用新建** |
| `ActionExecutionReceipt` | 同上 `:604` | **已是** `ActionExecution` 的别名 | 不新建第二个 schema（红线） |
| `ActionCapability` | 同上 `:51-56` | 只有 3 个**非交易性**取值（`COMPARE_OPTIONS`/`SAVE_SHORTLIST`/`REQUEST_MORE_EVIDENCE`）；docstring 写着 "a **future** action executor may support" | 需加 `PUBLISH`；且它是**第一个有副作用**的能力，破了原协议的 "non-transactional" 前提 |
| `CreatorAdvisor.plan_action/resolve_action/execute_action` | `creator_agent/advisor.py:261/321/329` | **已有**，生命周期齐全 | 但 `execute_action` 是**纯确定性本地执行器**：只从 Decision Record 快照造 receipt，**不产生外部副作用** |
| 控制面 API | `api/routes/creator_agent.py:318/348/368/388` | **已有**：`POST /actions`、`/actions/{id}/resolve`（人类确认/取消）、`/actions/{id}/execute`、`GET .../execution` | Human Confirm 不用新建 UI/路由，只需接内容侧 |
| `content_hash(body)` / `ArtifactRef.content_hash` | `state/artifacts.py:37/85` | **已有**；注释已预告 "S4 publish `content_hash` equivalence" | PublishIntent 的 `content_hash` 有现成来源 |
| `compute_publish_id` + publish record + 重复防护 | `agents/publisher.py:95/132/157/186/232` | **已有**（本地幂等） | 缺的是把它接进 Action 协议 |
| `xhs.publish` capability | `tools/runtime/catalog.py:600` | **无调用者** —— tool runtime 门禁唯一的 orphan；`audit.py:393` 明写 "no caller until P2a" | P2a 就是给它接上调用者 |
| `xhs.publish` 的 `RetryPolicy()` | `catalog.py:608-613` | **空**，注释：*"publishing is not idempotent until P2a gives it an idempotency key (Action Executor + Receipt). Enabling retry without that key would double-publish — and ToolSpec refuses to let us do that by accident."* | P2a 解锁 retry 的**前置条件是幂等键真的接上**，不是"打开开关" |
| Policy Engine | —— | **不存在**。`DecisionPolicy` 是**创作模型层**策略（signal weights/标签），不是执行 gate | 需新建 |
| `xhs_risk_gate.py`（1075 行，含 `publish_cooldown_seconds`） | `services/` | **已有** | Policy Engine 的既有素材（冷却/风控），避免另起一套判据 |
| 账号凭据 | `services/xhs_login.py` / `deploy.sh` 的 `account_credentials` | P1c 记录："读路径**结构性未鉴权** → 凭据整备归 P2a" | 凭据归属与可用性校验归本任务 |

补充事实（影响红线）：`backend/api/generated/models.py` **全仓无运行期引用**（只有自身
`__init__.py` 再导出，以及 `models/outputs.py` 一句 docstring 提及），是陈旧生成物 →
红线照旧"不改"，但**不要**把它当契约来源。

## 切片计划（每片独立 PR）

| 切片 | 内容 | 风险 |
|---|---|---|
| **S1（本片）** | **Action 协议扩展**：`ActionCapability.PUBLISH` + publish 专属载荷（`artifact_ref` + `content_hash`）+ 校验分支；`execute_action` 对 PUBLISH 显式"未接线"报错。**不产生任何副作用** | 中（改既有协议） |
| S2 | **Policy Engine**（新模块，deterministic 无 LLM）：输入 publish 意图 + 账号/内容快照 → `PolicyVerdict(allow/deny, policy_id, reason)`；复用 `xhs_risk_gate` 既有判据；**fail-closed（读不懂 = 拒绝）**。插在 `plan_action` 之后、人类确认之前 | 中 |
| S3 | **Action Executor 接 Tool Gateway**：PUBLISH 分支经 `ToolGateway` 调 `xhs.publish`（`PassStyle.INVOKE`）；幂等键接上后**解锁 catalog 的 `RetryPolicy`**；receipt 落 `note_id`/`url`。**这是第一次让 Action 产生外部副作用** | 高 |
| S4a ✅ | **主链提交接入 Tool Gateway**：`run_publish` 不再自己构造 `XHSClient`，改为 `self.tools.invoke("xhs.publish", …)`；**`xhs.publish` orphan 消失** → 门禁那条"唯一 orphan 是 xhs.publish"断言会红，**同 PR 更新**。**不改时序**（既不产 intent，也不等确认）：`run_publish` 的调用点、返回形状、下游 8 处消费逐字段不变 | 高 |
| S4b ✅ | **主链等人类确认**：`WorkflowStatus.AWAITING_PUBLISH` + `machine.py` **两条** gate 识别路径 + 动态 `interrupt`/`Command(resume=…)` + `publish_gate` 节点与路由 + `/resume` **无默认值**分支 + `auto_publish` 从「无人读的键」变成真开关 + 前端可见性。**不产 PublishIntent**（与 S4a 同：主链仍直接 `run_publish`）→ **待决问题 1 未裁决**，理由见 §S4b 的「修订」 | 高 |
| **S5a（本片）** | **凭据整备**：`services/xhs_credentials.py` 成为"哪个账号的凭据、从哪来"的**唯一所有者**（账号行 → 部署级 `XHS_COOKIE` → 无），可用性 fail-closed；读路径把 cookie 交给 `XHSClient`（P1c 写着"today this guard fires on every call"）；`granted_scopes` 从**恒 `None`（=unchecked）**变成真解析 → `xhs.publish` 的 `auth_scope` 第一次真的生效；executor 加**第四道 Gateway 之前的拒绝**（409）。**拆片理由见 §S5a 的「修订」** | 中-高 |
| S5b ✅ | **记录的忠实性**：`DecisionRecord` 的判据冻结（唯一写入者）+ 持久化"被拒"审计（`kind="action"`，人类拒绝与策略拒绝各一条） | 中 |
| S5c | **契约的表述**：`docs/publish-action-protocol.md` + 501 兜底（穷举 match 的 fail-closed 默认）+ **待决问题 1/3 的票面裁决** | 小 |

切片顺序的判据：先把**纯数据面**（S1）落定，再落**纯判定**（S2），然后才跨"产生副作用"
这道坎（S3），最后才动主链（S4）。S3 之前任何一片都不改变生产行为。

**S4 → S4a / S4b 的拆分理由**（S4a 侦察时定）："接 Gateway"与"等人类确认"正交 —— 前者
只改提交路径（返回形状逐字段不变、下游 8 处消费零影响），后者改控制流（新增状态 + 中断/恢复）。
合成一片会让"迁移不改契约"这条红线**无法单独验证**（提交没变但控制流变了时，红了不知道是谁的错）。

## 红线

- **不改 `backend/api/generated/`**（生成物）。
- **不引入新依赖**；Policy Engine deterministic，**不新增 LLM Agent**（父任务克制原则：
  能用 deterministic mechanism 解决的不放 Agent）。
- **不新建第二个 receipt schema**：沿用 `ActionExecution` / `ActionExecutionReceipt` 别名。
- **协议扩展必须键级三态**（P1d-S3 的纪律）：非 publish 动作的既有 payload **逐字节不变**。
- **人类确认不可绕过**：未 `CONFIRMED` 的 publish intent 必须无法被 execute（既有
  `ActionExecutionNotAllowedError` 已保证，S3 要证明它对新能力同样成立）。
- 执行副作用只经 **Tool Gateway**（P1c 纪律：`backend/agents/**` 不得直调 `backend.tools`）。

## 验收

- 全链：Generate → PublishIntent → Policy(allow) → Human Confirm → Execute → Receipt（带 note_id）
- 拒绝路径三条：Policy deny → **不产生 intent**；未确认 → execute 抛错；重复 execute → **同一 receipt**
- `xhs.publish` 不再是 orphan，且其 `RetryPolicy` 在幂等键就位后才开
- L0-L5 prompt 逐字节不变（P1b 基线漂移 0）；全量 `tests/unit` + `tests/integration`、ruff、mypy 干净

## 待决问题（S1 侦察时定，先把假设写下来）

1. **`audience_id` 对 publish 是必填但语义不成立**：`ActionIntent` 要求
   `account_id`/`creator_id`/`audience_id`/`decision_id` 全部必填，而**发布是账号级、不是受众级**。
   两个选项：(a) 给 publish 放宽 `audience_id`（键级三态 + 校验器）；(b) publish 沿用 decision 的
   audience（要求 publish 必须挂在一条 DecisionRecord 上）。倾向 (b) —— 与"重要 Decision 一律产
   immutable DecisionRecord"一致，且不动既有必填性。**S1 用现有测试确认 (b) 不产生空 audience。**
2. **Policy 拒绝时是否留痕**：拒绝若不产生 intent，则"被策略拦下"这件事在哪可见？
   倾向：拒绝写进 session 的 evidence/telemetry，而不是造一个永远无法确认的 intent。
3. **幂等键的分层**：本地 `compute_publish_id` 是"内容级"幂等，`ActionIntent.idempotency_key`
   是"请求级"。S3 要明确两者的关系（谁是权威、重复执行时以谁判定），避免出现两套幂等。

## 执行记录

### S1 — Action 协议扩展（`feat/p2a-s1-action-protocol`）

**范围**：只落**数据面**，不产生任何副作用。P2a 的三道坎（Policy / 副作用 / 主链）都没碰。

改动（5 改 1 新）：源文件 +143/−2，新测试文件 +292 行（30 用例）；另 `task.json` +19/−6、新建本 `prd.md`。
（初稿曾写 +310/−15，交付前按 `git diff --numstat` 复核更正 —— 门禁数字照实测填。）

| 文件 | 改动 |
|---|---|
| `creator_agent/models.py` | `ActionCapability.PUBLISH`；`_validate_publish_payload` 校验器；`ActionIntentRequest`/`ActionIntent` 各加 `artifact_ref`+`content_hash` + `model_validator(mode="after")`；`ActionIntent` 加**键级三态** `@model_serializer(mode="wrap")` |
| `creator_agent/repository.py` | `ActionCapabilityNotWiredError`（带 `action_id`/`action_kind`） |
| `creator_agent/advisor.py` | `plan_action` 的 PUBLISH 分支（candidate 规则不适用）+ 载荷透传；`execute_action` 在 CONFIRMED 之后对 PUBLISH **显式报"未接线"** |
| `api/errors.py` | `ErrorCode.CREATOR_ACTION_CAPABILITY_NOT_WIRED` + `CreatorActionCapabilityNotWiredError`（**501**） |
| `api/routes/creator_agent.py` | 异常映射 501 |
| `tests/unit/creator_agent/test_action_publish_payload.py` | **新建，30 用例** |

**三个设计决定（都写进代码注释了）**

1. **键级三态是承重的，不是洁癖**：`db/creator_agent._dumps` 走
   `model_dump(mode="json")`（**无 `exclude_none`**），所以普通 `None` 默认值会给**每一个非
   publish intent 的落库 payload** 加一个 `"artifact_ref": null` —— 那是与发布无关的能力的
   形状变更。用 `model_fields_set` 判"调用方真写过"，**unset 丢、显式 None 留**。
   （全仓首次使用 `model_serializer`，`grep` 已确认此前零使用。）
2. **领域模型层不 import 状态层**：`state/artifacts.py` 模块级 import
   `langgraph.store.base`，所以 `models.py` 用本地常量 `_ARTIFACT_REF_PREFIX = "artifact://"`
   而不是 `parse_ref`。两边的一致性**不是假设，是证明**：
   `TestTheLocalRefRuleAgreesWithTheStateLayer` 用 `make_ref`/`parse_ref` **双向**钉住
   （状态层造得出的 ref 本地必须收；状态层拒的本地必须也拒）。
3. **未接线必须吵**：S1 之后 PUBLISH 有 durable intent 但**没有执行器**。选 501 + 专属
   `ErrorCode` 而不是 200/静默造 receipt —— 后者会把"发布成功了"这件事**撒谎**，
   而且 `get_action_execution` 会留下一条假 receipt。

**待决问题 1 的裁决**：取 **(b)** —— publish 沿用 decision 的 `audience_id`，不动既有必填性。
测试用 `TestPlanAndExecutePublish::test_plan_action_persists_a_publish_intent_with_its_payload`
确认 publish intent 落库后 `audience_id` 非空（`advisor.plan_action` 从 DecisionRecord 快照取）。
放宽 `audience_id` 的键级三态留到确有账号级动作时再谈。

**门禁（四道全绿）**

| 门禁 | 结果 |
|---|---|
| `pytest -q` | **3095 passed / 3 skipped** —— S4 的 3065 + **30**，恰等于新测试文件用例数 → **零既有用例被改动** |
| `ruff check .` / `format --check` | **495 files**（S4 的 494 + 新文件 1）All checks passed |
| `uv run mypy backend --python-version 3.12` | **200 source files, no issues** |
| P1b 基线 | `drift within threshold`（`--drift-pct 5`） |
| `tool_runtime_gate.py` | OK；orphan 仍只有 `xhs.publish`（**符合 S1 范围**，它到 S4 才消失） |

**两条环境噪声（不是回归）**

- 全量 pytest 首轮有 1 条失败 `tests/integration/test_api_routes.py::TestWorkflowRoutes::test_delete_running_workflow_blocked`，
  报 `[safe-delete][SAFE_DELETE_BULK_GUARD_ERROR] ... timed out after 10 seconds` —— 是 WorkBuddy
  shim 的文件删除守卫超时。`CODEBUDDY_SAFE_DELETE_ENABLED=0` 单跑该用例 **1 passed**，
  确认与本次改动无关。
- 预计 mypy 会在 `model_validator(mode="after")` 返回 `self` 处报 `return-value`（返回基类 vs
  声明的具体类），**实测没有**：mypy 的 pydantic 插件正确处理了，因此**没加**任何
  `# type: ignore` —— 不写没有作用的抑制注释。

**突变自检：11/11 killed**，每条都从原始字节起算、每条都被**具名断言**杀掉：

| # | 突变 | 被谁杀 |
|---|---|---|
| M1 | 去掉 `ActionCapability.PUBLISH` | `test_publish_is_a_capability`（钝刀：测试模块 helper 一起崩） |
| M2 | 非 publish 能力静默忽略 publish 载荷 | `test_a_non_publish_capability_refuses_a_publish_payload` |
| M3 | publish 不再拒绝 candidate IDs | `test_a_malformed_publish_request_is_refused` |
| M4 | `content_hash` 只查 alnum（放过大写 / `z`） | 同上 |
| M5 | 去掉键级三态 serializer | `test_a_non_publish_intent_does_not_gain_the_publish_keys` + `..._byte_identical` |
| M6 | serializer 退化成 `exclude_none`（显式 None 也丢） | `test_an_explicitly_set_none_is_still_honoured` |
| M7 | `execute_action` 的 PUBLISH guard 不再 fire | `test_a_confirmed_publish_intent_fails_loudly_instead_of_minting_a_receipt` |
| M8 | 未接线能力返回 500 而不是 501 | `test_the_api_error_maps_to_501_with_its_own_code` |
| M9 | ref 形状不再检查 kind/id 非空 | `test_a_malformed_publish_request_is_refused` 等 3 条 |
| M10 | `plan_action` 不再透传 publish 载荷 | `test_plan_action_persists_a_publish_intent_with_its_payload` |
| M11 | 本地 ref 前缀与状态层脱钩（`"artifact://"` → `"artifact:/"`） | `test_a_ref_built_by_the_state_layer_passes_validation` |

M5/M6 这一对是**故意成对的**：只测 M5 的话，一个"丢键"的实现就能全绿；M6 反过来证明
**不能把 unset 当成 None 处理**。两个方向都钉住了，三态才真的成立。

**交付前独立抽验**（本片提交前重跑，不只转述上表）：M2 / M5 / M7 各一条，覆盖三个设计决定（拒绝错配载荷 / 键级三态 / 未接线必吵），**3/3 killed**，击杀者与上表登记的具名断言**逐条一致** —— M2 → `test_a_non_publish_capability_refuses_a_publish_payload[compare_options]`、M5 → `test_a_non_publish_intent_does_not_gain_the_publish_keys`、M7 → `test_a_confirmed_publish_intent_fails_loudly_instead_of_minting_a_receipt`。抽验脚本放仓库外，每条突变前重写原始字节，跑完用 `git diff --numstat` 复核还原逐项一致。

**下一片（S2）的入口条件**：S1 的 `ActionCapabilityNotWiredError` 是**临时**的路障，
S3 接上 Tool Gateway 后它必须消失（`grep` 该异常在生产代码里的引用面 = `advisor.py` 一处 +
`routes` 的映射一处）。S2 的 Policy 判据要插在 `plan_action` 之后、`resolve_action` 之前 ——
这样拒绝路径**不产生 intent**（待决问题 2 的取向）。

### S2 — Policy Engine（`feat/p2a-s2-policy-engine`）

**范围**：新模块 `backend/creator_agent/policy.py` + 接线。S2 三件事里只做"判定"，**不产生副作用、不碰主链**。

改动（5 改 2 新）：

| 文件 | 改动 |
|---|---|
| `creator_agent/policy.py` | **新建**：`PolicyId` / `RiskVerdict` / `ActionPolicySnapshot` / `PolicyVerdict` + `evaluate_action_policy`（纯函数规则表）+ `build_action_policy_snapshot`（唯一服务接触面，checker 可注入）+ `_consult_checker`（fail-closed 边界）+ `_risk_gate_publish_verdict`（调用时解析真门禁） |
| `creator_agent/repository.py` | `ActionPolicyDeniedError`（带 `policy_id` / `reason` / `account_id` / `retry_after_seconds`） |
| `creator_agent/advisor.py` | `plan_action` 在**形状校验之后、`create_action` 之前**求值；拒绝则 warning + 抛出。新增模块 logger |
| `api/errors.py` | `ErrorCode.CREATOR_ACTION_POLICY_DENIED` + `CreatorActionPolicyDeniedError`（**403**） |
| `api/routes/creator_agent.py` | `POST /actions` 异常映射接上 403 |
| `creator_agent/__init__.py` | 导出策略面 |
| `tests/unit/creator_agent/test_action_policy.py` | **新建，20 用例** |

**四个设计决定**

1. **引擎是纯函数，服务接触面只有一处**：`evaluate_action_policy` 只吃 `ActionPolicySnapshot`，规则表可单测而不碰 `xhs_risk_gate` 的模块级全局态；与门禁的接触隔离成**可注入的 checker**（默认走真门禁）。注入缝是为了让测试**跑同一条代码路径**，而不是 patch 掉门禁换来一个"默认路径从未被测"的假绿（因此另有一条用例专门证明**默认 checker 就是真门禁**）。
2. **★ fail-closed 落在边界上，不落在某个实现里**（本片唯一一次被自己的测试推翻的设计）：初版把 `try/except` 写在默认 checker 内部，测试证明**注入的 checker 一抛就穿透** —— 保证只对生产实现成立、不对缝成立，任何替代 checker 都会静默丢掉这个性质。改成 `_consult_checker(checker, …)` 统一包裹：**任何** checker 抛异常都变成 `RISK_UNAVAILABLE` 拒绝。捕获宽 `Exception` 是刻意的（门禁只为"这次发布能不能过"被咨询；答不上来就没有理由放行），`CancelledError` 是 `BaseException`、仍会穿透。
3. **`risk=None` 只表示"查过且清"**：读不到门禁表达成 `RiskVerdict(RISK_UNAVAILABLE, …)`，**不折叠进 `None`** —— 否则第 2 条的 fail-closed 会被静默改写成 fail-open。
4. **只闸有副作用的能力**：`NOT_APPLICABLE` 是规则表第一条，且 **builder 里就不去咨询门禁**，所以三个非交易性能力的既有行为**逐字节不变**（专门用例把门禁换成"一碰就 raise"的哨兵来钉这条红线）。

**待决问题 2 的裁决**：**不落库** —— 走"可观测但不留痕"。理由：拒绝既然不产生 intent，那么造一条**永久无法确认的 intent** 就是拿一个死记录换可见性。可见性由 ① **403 响应体**（`policy_id` / `account_id` / `retry_after_seconds`）+ ② **advisor 的 warning 日志**（含 policy_id / kind / reason）承担。**持久化"被拒"审计**（供运营回看）留给 S5，与 immutable DecisionRecord 收尾同批 —— 本片不新造 schema。

**★ 本片发现的既有缺陷（非本片引入，已钉成断言，不修）**：**按账号的发布冷却在生产里不可达**。

`xhs_risk_gate._profile_key` 优先用 `account_id`（键 `account:<id>`），只有在没给 account_id 时才退到 CDP endpoint；而生产里**唯一的写入者**是 `services/xhs_publisher.publish_note`，它**只传 `cdp_endpoint`**（该层拿不到 account_id）→ `account:<id>` 这个桶**没有任何生产写入者**，`check_publish_allowed(account_id=…)` 对所有账号恒返回 `None`。

- 后果：S2 的 `RISK_COOLDOWN` 规则**已接线、已用真门禁测过，但在生产里目前不可达**。
- 处置：**不假装修好**。钉成 `test_the_intent_time_check_reads_a_key_the_runtime_never_writes` —— 断言"运行时只写 endpoint 键 ⇒ 意图层按账号的检查为空"，并写明 **S3 落地时这条断言必须改**（S3 的 executor 同时知道账号与发布事件，是记账的正确归属地）。
- **既有测试为什么没发现它**：`test_risk_gate_cooldowns.py` 直接 `note_publish(account_id="a1")` —— **替身比生产多写了一个键**，于是用例全绿而生产这条闸是死的（与 P1d 记录的"替身必须忠实于生产"同一族）。

**门禁（四道全绿，提交前实测）**

| 门禁 | 结果 |
|---|---|
| `pytest -q` | **3115 passed / 3 skipped** —— S1 的 3095 + **20**，恰等于新测试文件用例数 → **零既有用例被改动** |
| `ruff check .` / `format --check .` | **497 files**，All checks passed |
| `uv run mypy backend --python-version 3.12` | **201 source files, no issues** |
| P1b 基线 | `drift within threshold`（L0–L5 prompt 逐字节不变） |
| `tool_runtime_gate.py` | OK；orphan 仍只有 `xhs.publish`（S4 才消失） |

**突变自检：6/6 killed**，每条从原始字节起算、每条被**具名断言**杀掉，覆盖六个不同机制：M1 非 publish 落进发布闸（`…is_out_of_this_policy_scope[compare_options]`）/ M2 收集了风险判决却不看（`…a_risk_block_denies_and_carries_the_retry_hint`）/ M3 读不到门禁当成"清"（`…a_raising_gate_becomes_a_denial_not_an_allow`）/ M4 空 account 放行（`…a_missing_account_is_a_denial_not_an_allow`）/ M5 策略拒绝后仍然落库（`…a_denied_publish_never_becomes_a_durable_intent`）/ M6 拒绝报 400（`…maps_to_403_with_its_own_code_and_retry_hint`）。

**下一片（S3）的入口条件**：① PUBLISH 经 Tool Gateway 调 `xhs.publish`，`ActionCapabilityNotWiredError` 必须消失；② **记账必须用同一个 key** —— `note_publish` 要带上 account_id，否则 `RISK_COOLDOWN` 这条规则依旧是死的（见上面的钉法）；③ 幂等键就位**之后**才解锁 catalog 的 `RetryPolicy`。（**S3 实测后修订**：只满足 `ToolSpec` 的前置条件还不够 —— 见 S3 的设计决定 2，本片**没有**解锁。）

### S3 — Action Executor（`feat/p2a-s3-action-executor`）

**范围**：让 PUBLISH 第一次真的产生外部副作用。三件事 —— ① 新模块 `creator_agent/execution.py`（载荷构造 / 结论解析 / 两个默认即生产实现的可注入缝）；② `execute_action` 真执行 publish；③ 记账带上 `account_id`（关掉 S2 钉住的既有缺陷）。**不碰主链**（S4 才让 `PublisherAgent` 产 intent），也不新建控制面（`ActionIntent` / `ActionResolution` / `ActionExecution` / 4 条路由 / 人类确认在 S1 就已存在）。

改动（9 改 1 新）：

| 文件 | 改动 |
|---|---|
| `creator_agent/execution.py` | **新建，330 行**：`PublishContent` / `PublishRequest` / `PublishOutcome` / `PublishStatus` + `build_publish_payload`（8 键，每个键都必须是工具真的接受的参数）+ `load_publish_content` + `interpret_publish_result`（**Gateway 词汇 → 平台词汇的唯一映射点**）+ `artifact_store_content_reader` / `gateway_publish_dispatcher`（两个缝，默认值即生产实现） |
| `creator_agent/advisor.py` | `execute_action` 接上 publish：**删掉 `ActionCapabilityNotWiredError` 抛出**；`get_decision` 提前到副作用之前（副作用不许坐在一条即将失败的路上）；新增 `_execute_publish`（三道拒绝全在 Gateway 之前）；receipt 状态 `SUCCEEDED if publish_outcome is None or succeeded else FAILED`；构造器新增 `artifact_store` / `publish` 两个缝 |
| `creator_agent/models.py` | publish 载荷加 `thread_id`：**创建时必填 / 存量行可选**（`require_thread: bool = False` 故意不对称）；`plan_action` 透传 `thread_id` |
| `creator_agent/repository.py` | `ActionPublishContentUnavailableError`（带 `action_id` / `reason`） |
| `api/errors.py` | `ErrorCode.CREATOR_ACTION_PUBLISH_CONTENT_UNAVAILABLE`（**409**） |
| `api/routes/creator_agent.py` | `_advisor` 接上 `artifact_store`（取自 `app.state.graph.store`，与仓库既有通路一致）+ 409 映射 |
| `services/xhs_publisher.py` | `publish_note(..., account_id="")`；`check_publish_allowed` 与 `note_publish` **两处都传** —— 给 `account:<id>` 桶接上生产写入者 |
| `tools/xhs/publisher.py` | 签名加 `account_id` / `idempotency_key`；**拔掉 `except Exception: return {"status": "error"}`**；非 published 一律 `raise DomainOutcome(verdict, **payload)` |
| `tools/runtime/catalog.py` | `_PUBLISH_SAFETY_NET_S = 900.0`；`retry=RetryPolicy()` **保持 1 次**（见设计决定 2） |
| `creator_agent/__init__.py` | 导出执行面 |

**四个设计决定**

1. **★ `thread_id` 是"创建时必填、存量行可选"的不对称**：`get_artifact_body(store, thread_id, ref)` 需要 thread，而 `ActionIntent` / `DecisionRecord` / **整个 `creator_agent` 层此前零 thread 概念** → intent 定位不到自己的内容。修法是给 publish 载荷加 `thread_id`，并在**创建路径**必填（新行没有 thread 就是构造错误）、在**读取路径**可空（S1/S2 写的存量行必须仍可读，执行时**拒绝**而不是崩）。两个方向都有用例：`test_a_publish_request_must_say_which_thread_its_artifact_lives_in` + `test_a_stored_publish_row_written_before_s3_is_still_readable`。
2. **★ `RetryPolicy` 不按原计划解锁（对 S2 交接条件的修订）**：S2 写的是"幂等键就位**之后**才解锁"。实测后**修订**：幂等键满足的只是 `ToolSpec` 的前置条件（side-effecting + retryable 必须有键），而重试真正需要回答的那个问题它答不了 —— **"这次提交到底出去了吗？"**。Gateway 超时会**在浏览器流程提交途中**取消调用，调用方区分不了"提交前失败"和"答案丢了"；重试后者就是**双发一篇真笔记**。所以 `max_attempts` 保持 1，解锁条件是"执行器能在重发前 reconcile"（durable retry，P2b），**而不是"键存在"**。理由写进 `catalog.py` 的注释里，票面 subtask 的措辞（`RetryPolicy unlocked`）据此修订。
3. **归一化只在 Gateway 一个归属地（这条纪律迁移到了工具层）**：`tools/xhs/publisher.py` 以前把异常吞成 `{"status": "error"}`，于是 Gateway 只能看到"成功的一次调用"——工具层第二个安静的归一化器。本片拔掉它：**平台结论 → `DomainOutcome`（抛）；运行时失败 → 异常穿透**。同一条纪律也是本片顺手修掉一个真 bug 的原因（见下）。
4. **默认实现那一侧也要有"它真的是生产路径"的测试**：两个缝都可注入，但**默认值就是生产实现**，且各自有一条测试证明这点 —— 默认 dispatcher 经 `shared_gateway()` 打到**按名解析**的真工具（`catalog.bind` 每次调用重新解析，所以 rebind 模块属性会被尊重，测试才跑的是真代码路径而不是它的转述）；默认 reader 就是 Artifact Store 门面。只测注入缝会换来"默认路径从未被测"的假绿。

**★ 本片差点交付的真 bug（门禁前自我发现，已从读者一侧钉住错误形状）**：`DomainOutcome.__init__(reason, **payload)` 的 payload 是 `**kwargs`，**不是**关键字参数。写成 `DomainOutcome(reason=..., payload=dict(result))` 会把整个字典埋进一层，`interpret_publish_result` 读 `domain["status"]` 就 miss → **每一个平台结论都静默退化成"无法解释的失败"**（类型检查过、异常照抛、测试若只测注入缝也全绿）。两条用例显式钉住**错误形状**：`test_a_nested_verdict_would_be_an_unexplained_failure`（读者一侧）与 `test_the_domain_payload_keeps_the_verdict_at_the_top_level`（工具层，`assert "payload" not in excinfo.value.payload`）—— **钉错形状，"对形状"才有意义**。

**★ 既有缺陷已关闭（S2 钉的那条）**：**按账号的发布冷却在生产里不可达**。本片由**执行器把 `account_id` 一路交到 `services.xhs_publisher`**（`build_publish_payload` → 工具签名 → `publish_note` → `check_publish_allowed` / `note_publish` 两处），`account:<id>` 桶从此有生产写入者。S2 那条断言随之**改形**：`TestThePreExistingKeyGap` → `TestTheAccountKeyedCooldownIsReachableNow`，只留"两个桶互不共享冷却"；写入者那一半移到真正拥有它的两层去证（`test_action_publish_execution.py` 证执行器交了账号，`test_xhs_publisher.py` 证服务层收下并记账）。

**★ 新发现（不修，记录而不裁决）**：**501 路径现在没有生产者**。S3 删掉了 `advisor` 里最后一处 `ActionCapabilityNotWiredError` 抛出，于是 `CreatorActionCapabilityNotWiredError`（501）与路由映射**已不可达**，只剩一条"构造该错误看映射"的用例（它钉的是映射，不是行为）。**保留而不顺手删**的理由：`ActionCapability` 是协议的扩展点，而 `execute_action` 的 `else` 兜底会给一个**没有执行器的新能力**铸一张 receipt（静默成功）—— 比 501 更糟。**待决**：要么让兜底也改成拒绝，要么删掉这个错误类型；两条都超出本片范围。

**门禁（四道全绿，提交前实测）**

| 门禁 | 结果 |
|---|---|
| `pytest -q` | **3144 passed / 3 skipped** —— S2 的 3115 + **29**，恰等于本片新增用例数（新文件 **20** + 工具层重写 **+6**（1→7）+ payload **+3**（2 个新 def + 1 个新参数化用例））→ **零既有用例被删改** |
| `ruff check .` / `format --check .` | **499 files**，All checks passed |
| `uv run mypy backend --python-version 3.12` | **202 source files**（S2 的 201 + 1 = 新模块），no issues |
| P1b 基线 | `drift within threshold`（L0–L5 prompt 逐字节不变） |
| `tool_runtime_gate.py` | OK；orphan 仍只有 `xhs.publish` —— **主链未接，按设计要到 S4 才消失** |

**突变自检：9/9 killed**，每条**从原始字节起算**（不累积）、每条被**具名断言**杀掉，覆盖九个不同机制：

| # | 突变 | 被谁杀 |
|---|---|---|
| M1 | 请求侧 `thread_id` 降回可选（不对称被误用） | `test_a_publish_request_must_say_which_thread_its_artifact_lives_in` |
| M2 | `DomainOutcome` 的 verdict 埋进 `payload=` 一层 | `test_the_domain_payload_keeps_the_verdict_at_the_top_level` |
| M3 | 拔掉 `content_hash` 校验（发了没确认过的正文） | `test_a_body_that_does_not_match_the_confirmed_hash_is_refused` |
| M4 | 默认 dispatcher 变成壳（自己编一个 receipt） | `test_it_reaches_the_shared_gateway_and_the_lazily_resolved_tool` |
| M5 | `unknown`/`pending` 当成 FAILED（已发出的提交被读成可重跑） | `test_an_ambiguous_verdict_is_read_out_of_the_domain_payload` |
| M6 | 安全网退回通用 SLOW 默认（合法流程被 120s 砍断） | `test_the_publish_net_outlives_the_generic_slow_net` |
| M7 | `thread_id` 没被写进 intent | `test_plan_action_persists_a_publish_intent_with_its_payload` |
| M8 | 工具层装回第二个安静的归一化器 | `test_a_raised_failure_reaches_the_gateway_instead_of_being_swallowed` |
| M9 | capability 名写错（按名解析不再命中真工具） | 同 M4 |

M6 对应的那条 pin 是**本片补的**：`_PUBLISH_SAFETY_NET_S = 900.0` 初版只写了"必须严格高于工具自身预算"的注释，**没有任何断言**，于是"把 timeout 改回默认"这条突变会存活。补法是**推导而非复述字面量** —— 从 `ToolSpec(latency=SLOW).effective_timeout_s` 取通用网，断言 publish 的网严格高于它，这样下调通用网也不会把顺序悄悄倒过来。

**交付前独立抽验**（提交前重跑，不只转述上表）：M2 / M4 / M6 各一条，覆盖三个不同机制（结论被埋 / 默认路径是壳 / 预算倒挂），**3/3 killed**，且失败**原因**与登记一致 —— M2 → `assert 'payload' not in {...'payload': {...}}`、M4 → `assert 'stub' == 'note-9'`、M6 → `assert spec.timeout_s is not None, "publish must carry its own net"`。抽验脚本放仓库外，每条先重写原始字节、跑完还原，`git status` 与突变前**逐项一致**。

**下一片（S4）的入口条件**：① `PublisherAgent` 产 PublishIntent，`xhs.publish` 的 orphan 消失，`tool_runtime_gate.py` 那条 orphan 断言**同 PR 更新**；② `ActionIntentRequest.account_id` 目前**显式必填**，而主链里 `PublisherAgent` 只有隐式账号 → 落地时要显式传，或放宽为可推导（**待决问题 1**，S1 定、S4 必踩）；③ `compute_publish_id`（内容级去重）与 `ActionIntent.idempotency_key`（请求级）的关系要在票面写明（**待决问题 3**）；④ 501 兜底要么改成拒绝、要么删掉（见上面的新发现）。

### S4a — 主链提交接入 Tool Gateway（`feat/p2a-s4a-mainline-gateway`）

**范围**：让 `xhs.publish` 这个 orphan 消失 —— 主链的真实发布不再自己构造 `XHSClient`，改经 `PublisherAgent.tools.invoke("xhs.publish", …)`（P1c 纪律：副作用只经 Tool Gateway）。**刻意不碰时序**：`run_publish` 的调用点不动、不产 PublishIntent、不等确认。侦察结论是 **S4 可拆且应当拆** —— "接 Gateway"与"等确认"两件事正交：前者改提交，后者改控制流；合在一起会让"返回形状逐字段不变"这条红线无法单独验证。所以本片 = S4a，S4b 只留等确认（+ 待决问题 1）。

侦察（子代理逐条核实）得到三条必须先处理的既成事实：

1. **主链至今不传 `account_id`** —— S2 钉的"按账号发布冷却无生产写入者"缺陷有**两条**路径，S3 只关了控制面那一条，**主链（`run_publish` → `XHSClient.publish_post`）是另一条**。两条同源于 `XHSPublisher.publish_note`，所以本片一接上，这条缺陷的两半才算都关掉。
2. **`xhs.publish` 工具把 CDP endpoint 写死为 `settings.platform.cdp_endpoint`** —— 而主链是按账号解析（`get_account_cdp_endpoint`）。**直迁会让多账号发布静默回退到全局 profile**（多账号共用一个登录态）。这一条是"迁移会引入回归"的实证：旧代码里 `XHSClient` 的这个参数由主链显式构造，工具里却无处可传。
3. **`BaseAgent.tools` 是 property**（`agents/base.py:135` → `shared_gateway()`），`PublisherAgent` 此前完全绕过它。

改动（4 改 2 测）：

| 文件 | 改动 |
|---|---|
| `tools/xhs/publisher.py` | `_get_publisher(cdp_endpoint: str = "")`：**显式值优先，留空回落到全局配置**（控制面路径传空，行为不变）；工具签名加 `cdp_endpoint` |
| `agents/publisher.py` | 类体加 `tool_capabilities = ("xhs.publish",)`；新增 `_publish_gateway_account_id` 与 `_result_from_gateway`；`run_publish(state, store, *, agent=None)`；提交段改为一次 `runtime.tools.invoke(...)`；删掉 `XHSClient(...)` 构造与 `finally: await client.close()` |
| `tests/unit/agents/test_run_publish.py` | 打桩缝从 `XHSClient` 换成 `backend.tools.xhs.publisher._get_publisher`（**只桩浏览器层**）；+4 用例 |
| `tests/unit/agents/test_publisher_account.py` | 同上迁移；断言从 ctor kwargs 换成"工具真的收到了什么" |
| `tests/unit/tools/test_xhs_publisher.py` | **+3 用例**：新增 `TestGetPublisherEndpointSelection`（见设计决定 4） |
| `tests/unit/tools/runtime/test_audit.py` | orphan 断言**改形**（见下） |

**四个设计决定**

1. **★ `_publish_gateway_account_id` 与 `_publish_account_id` 必须不是同一个函数**：前者**没指定就返回 `""`**，后者回退 `"default"`。理由分成两半 —— `compute_publish_id` 需要一个**稳定字符串去 hash**，把它从 `"default"` 改成 `""` 会**重键所有存量幂等记录**（等于一夜之间放开所有重复发布防护），所以**幂等记录里的键不动**；而把 `"default"` 交给**平台层**则会把这批未归属发布移进 `account:default` 桶，**改变一个今天正常工作的护栏的语义**。两个调用点要的东西不同，所以是两个函数，不是一个函数两个参数。方向两边都有断言：`test_unattributed_publish_sends_an_empty_account_id`（"绝不传 default"）。**这条是本片新补的**：初版只有注释写了这个不变量、**没有任何断言**（"注释里写了不变量却没断言的常量 = 突变必存活"），补上后 M8 才被杀死。
2. **★ `_result_from_gateway` 是整片风险的归属地**：Gateway 说的是 `ok` / `error_kind`，`publish_result` 契约说的是 `status` / `error`，翻译只能发生在**这一个函数**里 —— 泄露出去就会碰到下游 8 处消费（`analyst.py:136-298`、`calibrator.py:107`、`analytics.py:569`、`free.py:420-454`、`workflow.py:2839-2945`、`hydration.py:270`、`omp_bridge.py:1880`）。三个分支各自的语义经过挑选：`ok` → 原样 dict；`DOMAIN` → 平台自己的 payload **原样返回**（其中的 `unknown`/`pending` 是"提交出去了、答案丢了"，护栏必须继续 armed）；其余 → `TIMEOUT` 判 `unknown`、其他判 `failed`。
3. **★ 两处契约翻译是"接受"而不是"修掉"**（判据：**迁移不改契约**，但"契约"的边界要划清）：
   - **超时文案**：`TimeoutError("page load timed out")` 经 Gateway 归一化成 `"timeout after 900s"`，方法名不再出现。**接受** —— 超时是**运行时**测量的、也由运行时命名；旧文案里带方法名只是"异常文本原样透传"的副产物。测试从"断言文案"改成**断言判决**（`status == "unknown"` + `error_type == publish_result_unknown`），因为它才是让护栏继续 armed 的那个东西。
   - **`RuntimeError: cookie expired, login required` 带类型前缀**：`classify_publish_error` 是**子串匹配**（`api/errors.py:495`），`"cookie"` 仍在文本里 → `auth_expired` 与旧契约**逐字相同**，不需要剥前缀。这条不改代码，只补一条用例钉住（`test_platform_verdict_survives_the_gateway_round_trip`）。
4. **★ 每一层都要有一个"它真的是生产路径"的测试（M11 的产物）**：突变自检里 **M11（工具忽略传进来的 `cdp_endpoint`）第一次跑是存活的** —— 先问"这条突变改的代码真的被执行了吗"，答案是**没有**：`_get_publisher` 正是所有测试**整体替换**的那个函数，于是它的**函数体（以及"显式 endpoint 优先于全局"这条规则）在任何测试里都没有被执行过**。这是**真覆盖缺口**，不是伪突变：`test_cdp_endpoint_proceeds_with_empty_cookie` 之类的断言只能证明"主链把 endpoint 交给了工厂"，证不了"工厂用了它"。补法是新增 `TestGetPublisherEndpointSelection`（**只桩 `XHSPublisher`**，让选择逻辑真跑），M11 随即被杀。

**★ 那条钉 orphan 的绊线按设计响了，并且被"改形"而不是删掉**：`test_audit.py::test_the_only_orphan_is_the_publisher` 的 docstring 原文写着 *"Pinned deliberately: when P2a wires a publisher, this test fails and the orphan list gets revisited instead of quietly growing."* —— 它在 S4a 准时变红。处理：`test_only_the_four_tool_users_are_listed` → **five**（加 `publisher.py`）；`test_the_only_orphan_is_the_publisher` → **`test_no_capability_is_left_without_an_agent`**（断言 `orphans == ()`），docstring 保留绊线来历与"它被关掉"这件事。**没有删掉它** —— 性质从"某个 orphan 的名字"变成"不存在没有调用者的能力"，后者才是长期该守的东西。

**门禁（四道全绿，提交前实测）**

| 门禁 | 结果 |
|---|---|
| `pytest -q` | **3151 passed / 3 skipped** —— S3 的 3144 + **7**，恰等于本片新增用例数（`test_run_publish` **+4** + `test_xhs_publisher` **+3**）→ **零既有用例被删改**（唯二"改动"的两条是上面那条绊线的改形，属预期信号） |
| `ruff check .` / `format --check .` | **499 files**，All checks passed |
| `uv run mypy backend --python-version 3.12` | **202 source files**，no issues |
| P1b 基线 | `drift within threshold`（L0–L5 prompt 逐字节不变） |
| `tool_runtime_gate.py` | OK；**`publisher.py declared=1 invoked=1 ok`，orphan 行消失**（`named by agents: 10`，`orphans == ()`） |

**突变自检：13/13 killed**，每条**从原始字节起算**、每条被**具名断言**杀掉，覆盖 13 个不同机制：

| # | 突变 | 被谁杀 |
|---|---|---|
| M1 | 删掉 `tool_capabilities` 声明 | `tool_runtime_gate`（`declared=0` → UNDECLARED）+ `test_the_agent_layer_is_clean` + `test_publisher_declares_its_capability` |
| M2 | 调用点 capability 名写错 | 门禁（UNDECLARED + UNUSED 同时出现）+ 同上 |
| M12 | 声明里 capability 名写错 | 门禁（`UNDECLARED=['xhs.publish'] UNUSED=['xhs.publish_note']`）+ 同上 |
| M3 | 不传 `account_id` | `test_uses_selected_account_cdp_profile` |
| M13 | 丢 `account_id` 的 state 级回退 | `test_falls_back_to_global_when_no_account` |
| M8 | 未归属发布回退成 `"default"` | `test_unattributed_publish_sends_an_empty_account_id` |
| M4 | 不传按账号解析的 `cdp_endpoint` | `test_per_account_cdp_endpoint_passed_to_client` |
| M11 | 工具忽略收到的 `cdp_endpoint` | `TestGetPublisherEndpointSelection::test_an_explicit_endpoint_wins_over_the_global_one` |
| M5 | `ok` 结果退化成裸 status（丢 post_id） | `test_browser_definite_failure_releases_guard` |
| M6 | 超时判成 `failed` 而非 `unknown` | `test_timeout_after_submit_action_marks_unknown_not_failed` |
| M7 | 丢掉平台结论（DOMAIN 分支失效） | `test_browser_timeout_after_click_marks_unknown_and_keeps_guard` |
| M9 | 不传 `idempotency_key` | `test_real_publish_reaches_the_gateway_with_the_whole_payload` |
| M10 | 不传 `thread_id` | 同 M9 |

M1/M2/M12 的**第一击杀者都是门禁**（不是 pytest）：这正是"声明与调用逐模块一致"该有的样子 —— 编译期规则比运行期用例更早发现问题。抽验按纪律做了：**M11 那一条不是"抽验通过"，而是"抽验推翻了记录"** —— 首次全跑的存活项经追问"突变体真的被执行了吗"定位到真覆盖缺口，补测后重跑全组才得 13/13（登记的是重跑结果，不是首次结果）。

**打桩缝的选择（唯一的实质副作用）**：patch `backend.tools.xhs.publisher._get_publisher`，**只桩浏览器层** —— 工具自己的载荷归一化、catalog 按名解析、Gateway 的 timeout/retry/scope/tracing 全都**真跑**。旧测试桩的是 `XHSClient`，等价于把"平台层"整个换成替身，同时顺带把 Gateway 一起绕过去了。这也解释了一个数字：这两个文件的耗时 **125.8s → 4.3s**，原来它们**真的在碰浏览器**。

**下一片（S4b）的入口条件**：① `WorkflowStatus` 现在**没有** `AWAITING_PUBLISH`（侦察已确认），要新增取值 + `machine.py` 分支 + `interrupt`/`Command(resume=…)`；② `ActionIntentRequest.account_id` **显式必填** vs 主链隐式账号（**待决问题 1**，S4a 未碰因为在 S4a 里主链根本不产 intent）；③ `review_gate` 人工关卡已存在，但它与"等发布确认"是两回事，不要复用成同一状态；④ 501 兜底要么改成拒绝、要么删掉（S3 遗留）。

### S4b — 主链等人类确认（`feat/p2a-s4b-publish-confirmation`）

**范围**：在 AI 质量门与真实发布之间插入一道**人类授权关卡**。在此之前，"内容合格"
（evaluator 的 verdict）与"授权执行"是**同一个事件** —— 一个 AI 质量门自己决定了不可逆的
外部动作。本片把它们分开：AI 门之后停下来，等一个明确的人说"发"。

**不做的事**（与 S4a 一致，见下面的「修订」）：不产 PublishIntent，不接 Gateway（S4a 已交付），
不新建控制面（`ActionIntent` / `ActionResolution` / `ActionExecution` / 4 条路由 / 人类确认在 S1
就已存在）。**也不给 `run_publish` 的另外两个调用点加关卡** —— `/publish-retry`
（`api/routes/workflow.py`）与 free 发布（`api/routes/free.py`）**已经是显式人工通道**，在它们
上加关卡会破坏语义。

侦察（子代理逐条核实）得到六条必须先处理的既成事实：

1. **两种中断范式并存**：`review_gate` / `ripple_gate` / `blogger_gate` / `brief_gate` 用**动态
   `interrupt()`**（节点体内调用，靠 `Command(resume=…)` 恢复）；`choice_gate` / `draft_gate`
   用**静态 `interrupt_before`**（编译期声明，靠 `ainvoke(None)` 恢复，**`Command(resume=)`
   对它无效**）。跨范式抄错会让"恢复"这条通道静默失灵。
2. **`WorkflowStatus` 是派生值、不是存储值**（`state/machine.py::derive_status`），而且它识别
   gate 有**两条**独立路径：① `next_nodes` 里含 gate 名（`interrupt_before` 的形状）；②
   `snapshot.interrupts[0].value.get("gate")` 做字符串映射（动态 `interrupt()` 的形状）。
   **只加一条 = 有一条路径上 UI 静默错报状态。**
3. **`auto_publish` 是一个"声明了但无读者"的键**：`POST /start` 与 `POST /api/review/submit`
   都宣称"审核通过后自动发布"，schema（`state/schema.py`）有它、DB 写它、state 带它，而
   `backend/graph/**` **从不读它**。
4. **`dry_run` 有两条来源**（工作流级 `state["dry_run"]` / 决策级 `publish_options["dry_run"]`），
   原判据内联在 `PublisherAgent.execute`。
5. **`run_publish` 有 3 个调用点**，其中两个已是显式人工通道（见上）。
6. **"取消"不是新语义**：`derive_status` 的 Priority 1 与 `_check_terminal` 早已把
   `phase=CANCELLED` 映射为 `WorkflowStatus.CANCELLED` → "拒绝发布"**不需要新增状态值**，
   本片只新增 `AWAITING_PUBLISH` 一个。

改动（8 后端 + 5 前端 + 6 测试）：

| 文件 | 改动 |
|---|---|
| `agents/nodes/publish_gate.py`（新） | `publish_needs_confirmation`（唯一判据）+ `publish_gate_node`（跳过 / 中断 / 判决三态）。常量 `PUBLISH_CONFIRMED`/`PUBLISH_CANCELLED` + 三个 `source` 标签 |
| `state/schema.py` | 新增 `publish_confirmation: dict[str, Any]`，**紧跟 `human_feedback`** 并写明为何分键 |
| `state/machine.py` | `WorkflowStatus.AWAITING_PUBLISH`；`next_nodes` 分支 + `gate_type == "publish"` 分支（既成事实 2 的两条）；docstring 优先级表重编号 |
| `agents/publisher.py` | 抽出 `publish_is_dry_run(state)`（**一处规则两个读者**），`execute` 内联判据改调用它 |
| `agents/nodes/__init__.py` | 懒加载导出 `publish_gate_node` |
| `graph/error_handling.py` | `RETRY_POLICIES` 登记 `"publish_gate": None`（重试包住中断点无意义；`get_retry_policy` 对未登记节点 raise → `test_retry_registry` 会红） |
| `graph/routers.py` | `publish_gate_outcome`：**默认拒绝**（只认字面量 `"confirmed"`） |
| `graph/builder.py` | `add_node("publish_gate", …)`（无 retry）；`evaluator_outcome` 的 `"publisher"` 边目标改指 `publish_gate`；新增 `publish_gate` 的条件边 |
| `api/routes/workflow.py` | `/resume` 新增 `AWAITING_PUBLISH` 分支：**无默认 resume_value**，缺 `decision` 时只回"该发什么"、**不执行任何动作**；有则 `Command(resume=…)` + `source="publish_confirmation"` |
| 前端 5 处 | `types/workflow.ts`（union 加 `'awaiting_publish'`）、`composables/dashboardHero.ts`（归入既有 amber waiting 桶，**不新增视觉状态**）、`locales/zh-CN.json` + `en.json`（各一条）、`tests/composables/dashboardHero.spec.ts` |
| 测试 6 文件 | 新增 `tests/unit/agents/nodes/test_publish_gate.py`（36）、`tests/integration/test_publish_gate_flow.py`（10）、`tests/unit/api/test_resume_publish_gate.py`（10）；改形 `tests/unit/state/test_machine.py`（+4）、`tests/unit/state/test_schema.py`（+1）、`tests/unit/graph/test_routers.py`（+14）、`tests/integration/test_evaluator_gate.py`（拓扑绊线改形 +2）、`tests/integration/test_evaluator_pause_resume.py`（下一跳断言改形） |

**九个设计决定**

1. **★ 用动态 `interrupt()`，不用 `interrupt_before=["publish_gate"]`**。两个理由，都不是风格问题：
   ① `Command(resume=…)` **只对动态中断有效** —— 静态中断要多一条 `ainvoke(None)` 恢复通道，
   等于给这一个关卡开第二种协议，而 `/resume` 已有 `Command(resume=…)`（brief / ripple /
   blogger 三处都在用）；② `builder.compile()` 在 `build_graph()` 里，且 **dev / prod 两个分支
   各写一次** —— `interrupt_before` 会让"这道关卡存在"这件事出现**两处**改动，而 `add_node` 只写
   一次 → **单入口不漂移**。
2. **★ `publish_confirmation` 必须与 `human_feedback` 分键**。合并是"两个都是人的决定，那复用
   一个键吧"这种最自然的重构 —— 而它会让 `publish_gate` 的写入**覆盖 `review_gate` 的判据**：
   `review_outcome` 正是读 `human_feedback.decision` 路由的。两者语义也正交：`human_feedback`
   答"这篇内容能不能过"（`approved`/`needs_revision`/`rejected`），发布确认答"这次不可逆的
   外部动作做不做"。方向两边都有断言：`test_the_gate_writes_its_own_key`（节点不写那个键）
   + `test_publish_confirmation_is_its_own_key`（schema 里确实是独立字段）。
3. **★ 失败方向必须是关**。`publish_gate_outcome` 只认字面量 `"confirmed"` 放行，
   **缺失 / 拼错 / 来自旧客户端的任何别的词一律拒绝**。理由写进了 router 的 docstring：
   *"一个把无法识别的值读成'继续'的确认关卡，会把每一次版本错配都变成一次未经确认的真实
   发布。"* 12 个拒绝用例：`None` / `{}` / `decision=None` / `""` / `"yes"` / `"Confirmed"` /
   `"CONFIRMED"` / `"confirmed "`（尾空格） / `True` / `1` / 裸字符串 `"confirmed"`（**不是本
   关卡的契约形状**） / `{"approved": True}`（那是 review_gate 的方言）。
4. **★ 缺默认值是刻意的**。brief / ripple / blogger 的 `resume_value` 都有默认（`skip` /
   `accept`），因为**那里的默认是"继续一件已经被授权的事"**；这里没有默认，因为**这里的默认
   会执行那个不可逆的动作**。所以空 body 的 `/resume` 只回"该发什么"，什么都不跑
   （`test_missing_decision_describes_what_to_send` 同时断言 `mock_run` / `graph.ainvoke` /
   `graph.aupdate_state` **三个都没被 await**）。
5. **★ 拒绝置 `phase=CANCELLED`，不是 `ERROR`，也不留在 `PUBLISHING`**。人说"这篇不发"是
   **决定**，不是故障；而留在 `PUBLISHING` 更糟 —— publisher 被跳过、运行没有后继节点，
   `derive_status` 会为一条**从未发出的笔记**报 *completed*。于是选 `CANCELLED`，且它**不需要
   新状态值**（既成事实 6）→ 路由的两条路径（节点写的 phase / 确认值缺失）通向同一结论，
   docstring 里写明这是有意的。
6. **★ `auto_publish` 从"无人读的键"变成真的开关 —— 这就是"不做破坏性默认"的落点**。
   不接它，本片会把每一个走 `/start`（宣称自动发布）的既有工作流变成必须人工点一次：
   那是**改默认行为**，不是"加一道关卡"。
7. **★ `publish_is_dry_run` 抽成一处规则、两个读者**。`PublisherAgent.execute` 用它选 mock 路径，
   关卡用它判"要不要问"。抽出来之后，**关卡与发布者不可能对"东西到底出没出机器"产生分歧** ——
   这正是"dry run 免问"这条豁免能成立的前提。它也解释了为什么 `auto_publish` 用严格 `is True`
   而 `dry_run` 用 truthiness：**前者没有孪生读者（一个像 `"true"` 的近似值意味着"没人真的做过
   这个声明"→ 关门），后者有（`"yes"` 会让发布者走 mock，与关卡的判断一致 → 开门）**。
8. **`dry_run` 的工作流级来源是两者中更强的一方**（任一为真即真）。一个以 rehearsal 启动的
   线程必须保持 rehearsal，**即使批准决策要求真实发布** —— 只读 `publish_options`（一个只见过
   review 路径的人会这么写）会让那个决策**静默翻转**它。这条在 `publish_is_dry_run` 的 docstring
   里写明，并由真值表里 `{"dry_run": True, "publish_options": {"dry_run": False}}` 钉住。
9. **`publish_summary` 只做展示、不做判定**。判的是**人**，所以 interrupt 载荷只给够人判断的
   三样（标题 / 有没有图 / 账号），**不塞评分** —— 塞了会让"确认"看起来像是在认可那个分数。
   `gate="publish"` 这个值则是**契约**：`derive_status` 靠它（第二条路径）得出 `AWAITING_PUBLISH`。

**修订（与 S4b 计划行的差异，写在票面而不是悄悄缩小范围）**

计划行写的是"`PublisherAgent` 产出 PublishIntent 并停在那里；同时裁决 **待决问题 1**"。
实际交付的是**等确认**这一半，`PublishIntent` 那一半**没做**，理由是它属于**另一个关切**：
让主链改走控制面（intent → Policy → Executor）是**架构迁移**，而"不在没有人类授权时发布"是
**安全性质** —— 后者与前者正交（S4a 拆片的同一条判据），而且**与 S4a 保持一致**（S4a 明确
"既不产 intent，也不等确认"）。所以：

- 主链的发布路径仍是 `publisher` → `run_publish`（**不经控制面**）。
- **待决问题 1（`ActionIntentRequest.account_id` 显式必填 vs 主链隐式账号）因此仍未裁决** ——
  本片没有任何产生 `ActionIntent` 的代码路径，裁决需要一个**真的产 intent 的调用者**才有落点。
  在票面写明"修订"而不是留一条看起来已完成的计划行。

**门禁（全绿，提交前实测）**

| 门禁 | 结果 |
|---|---|
| `pytest -q` | **3227 passed / 3 skipped**（S4a 的 3151 + **76**，恰等于新用例数 `36+9+10+4+1+14+2`）→ **零既有用例被删、零既有断言被弱化**（唯二改动的两条是上面那条拓扑绊线与 pause_resume 的下一跳断言，均为预期信号） |
| `ruff check .` / `format --check .` | **503 files**（S4a 的 499 + 新测试 3 + 新模块 1），All checks passed |
| `uv run mypy backend --python-version 3.12` | 203 source files，no issues |
| P1b 基线 | `drift within threshold`（L0–L5 prompt 逐字节不变） |
| `tool_runtime_gate.py` | OK（`publisher.py declared=1 invoked=1`，orphan 行仍无 —— 本片不碰工具面） |
| 前端 | `type-check` clean；`vitest` clean；`i18n:check` consistent |

**突变自检：22/22 killed**，每条**从原始内容起算**（`restore_all()` 在每条之前）、每条被
**具名断言**杀掉，且**第 0 步先在未改动的树上把 16 个具名击杀者全跑一遍**（否则"被杀"可能
来自一条本来就红的测试）：

| # | 突变 | 被谁杀 |
|---|---|---|
| M1 | `auto_publish` 改成按真值判断（不再是 `is True`） | `test_publish_needs_confirmation_truth_table`（`"true"` / `1` 两例） |
| M2 | 常备授权只读 `publish_options` | `test_auto_publish_at_workflow_level_does_not_interrupt` |
| M3 | 常备授权只读工作流级 `state` | `test_auto_publish_in_publish_options_does_not_interrupt` |
| M4 | 关卡永远问（dry run 不再豁免） | `test_dry_run_at_workflow_level_does_not_interrupt` |
| M5 | 非 dict 的恢复载荷被读成同意 | `test_everything_but_confirmed_refuses` |
| M6 | 缺 `decision` 键默认成 confirmed | 同 M5 |
| M7 | "只要不是 no 就算 yes" | 同 M5 |
| M8 | 拒绝时 phase 留在 `PUBLISHING` | `test_cancelled_is_a_decision_not_a_fault` |
| M9 | interrupt 不再声明 `gate="publish"` | `test_payload_reports_what_is_about_to_be_posted` |
| M10 | interrupt 摘要丢掉标题 | 同 M9 |
| M11 | 路由接受"任何不是 cancelled 的值" | `TestPublishGateOutcome::test_unrecognised_decision_is_refused` |
| M12 | 路由忽略终态 phase | `TestPublishGateOutcome::test_terminal_phase_wins_over_a_confirmation` |
| M13 | evaluator 的边仍直接落到 publisher | `test_evaluator_gate_branch_to_the_publish_gate_and_revise` |
| M14 | 关卡的 `__end__` 边指向 publisher | `TestConfirmationResumesIntoThePublisher::test_cancelled_ends_the_run_without_publishing` |
| M15 | 新节点未登记进 `RETRY_POLICIES` | `tests/unit/graph/test_retry_registry.py` |
| M16 | `derive_status` 删掉 `next_nodes` 分支 | `test_interrupt_at_publish_gate_returns_awaiting_publish` |
| M17 | `derive_status` 删掉 `gate_type == "publish"` 分支 | `test_dynamic_interrupt_publish_gate_returns_awaiting_publish` |
| M18 | `AWAITING_PUBLISH` 换成别的字符串 | `test_missing_decision_describes_what_to_send`（断言 `status == "awaiting_publish"`） |
| M19 | `/resume` 缺 decision 也执行图 | 同 M18 |
| M20 | `/resume` 把缺的 decision 默认成 confirmed | 同 M18 |
| M21 | schema 里不声明 `publish_confirmation` | `test_publish_confirmation_is_its_own_key` |
| M22 | `publish_is_dry_run` 丢掉工作流级来源 | `test_publish_needs_confirmation_truth_table` |

M12 的**首跑是"锚点失败"而不是存活**：它锚在 `if terminal := _check_terminal(state):`，
而全仓 15 个 router 共享这个形状（`count=15`）→ 收紧到 `publish_gate_outcome` 自己的
docstring 尾部后单独重跑才得 killed。**登记的是收紧锚点后的结果，不是首跑结果。**

另有一条**先验真伪的副产品**：`Command(resume={})` 在真实图上**根本不会解开中断** —— 
LangGraph 把空载荷读成"没有可恢复的东西"，节点重新 `interrupt()`，线程原样停在关卡上
（`phase` 未动、`publish_confirmation` 未写、`next` 仍是 `("publish_gate",)`）。这不是错误，
而是**对空回答最安全的读法**，且与"拒绝"可区分，所以单独立了一条
`test_an_empty_resume_leaves_the_gate_waiting` 而不是并进拒绝组。

**那条钉边的拓扑绊线又按设计响了一次（并且同样被改形而不是删掉）**：
`tests/integration/test_evaluator_gate.py::test_evaluator_gate_branch_to_publisher_and_revise`
断言 evaluator 分支的 `"publisher"` 端点**指向 `publisher` 节点** —— 这正是本片改掉的那条边。
处理：改名 `test_evaluator_gate_branch_to_the_publish_gate_and_revise`、断言改
`== "publish_gate"`（并在注释里说明 verdict 的名字仍叫 `"publisher"`：那是**质量陈述**，
授权是下一跳），**再加两条**（`publish_gate` 节点存在 / 它的分支到 `publisher` 或 `__end__`）。
另一条同类改形在 `tests/integration/test_evaluator_pause_resume.py`：`("publisher",)` →
`("publish_gate",)`（与 S4a 处理 orphan 绊线同一纪律）。

**S5 已拆成 S5a / S5b / S5c**：S5a 做**授权**（§S5a）、S5b 做**记录的忠实性**（§S5b，本片）、
S5c 做**契约的表述**（协议文档 + 501 兜底 + 待决问题 1/3 的裁决，入口条件见 §S5b 末尾）。
上面这份清单里的 ①（凭据 + `DecisionRecord`）与 ②（审计）**已全部结清**；③④⑤ 仍待 S5c ——
本片仍刻意没替待决问题 1 作答（理由见 §S5a 的设计决定 12）。

### S5a — 凭据整备（`feat/p2a-s5a-credential-provisioning`）

**范围**：让"哪个账号的凭据、从哪来"有一个**所有者**（`backend/services/xhs_credentials.py`），
并把它接给两个读者 —— 读路径（cookie 交给 `XHSClient`）与 Tool Gateway（scope 交给运行时）。
**不做**：`DecisionRecord` 收尾、持久化"被拒"审计、`docs/publish-action-protocol.md`、501 兜底
（全部归 S5b）；**不给 `account_credentials` 写写入者**（登录流程的职责，见「不做的事」）。

**侦察：四条既成事实**（逐条对代码核实）

| # | 事实 | 位置 | 含义 |
|---|---|---|---|
| 1 | 读路径**根本拿不到 cookie**：`_get_client` 构造 `XHSClient(use_browser=…, headless=False)`，**没有 cookie 参数**；`_require_readable` 的 docstring 自己写着 *"today this guard fires on every call"* | `backend/tools/xhs/trending.py:26/42` | 三个读能力在生产里**从未读到过任何东西**，一直走"平台不可读"的降级分支 |
| 2 | `account_credentials`（白名单 `XHS_COOKIE`/`XHS_USER_ID`）**没有任何生产写入者** —— 全仓只有建表、读、和"把 SYSTEM_KEYS 从它里面删掉" | `backend/db/accounts.py:70/436`、`db/system_config.py:264` | 扫码登录把登录态写进 **CDP profile**，不写这张表；缺的不是"读"，是"从哪写" |
| 3 | `XHS_COOKIE` / `XHS_USER_ID` 在 `.env.example` 从第一天就声明，而 `backend/config/settings.py` 里**没有任何 cookie 字段** | `.env.example:10-11` | 与 S4b 的 `auto_publish` 同一族：**声明了但无读者的键** |
| 4 | `auth_scope` 已声明、Gateway 也已强制（`_check_scopes`），但生产里 `granted_scopes` **恒为 `None`**，而 `None` 的 Gateway 语义是 *unchecked* —— S3 的 docstring 自己写着 *"nothing in this repo owns a publish grant yet"* | `gateway.py:200-205`、`execution.py:~302` | `xhs.publish` 的 `auth_scope=("xhs:write",)` **从 S1 起就是装饰**：有无权限走同一条路 |

**改动（8 改 3 新）**

| 文件 | 改动 |
|---|---|
| `services/xhs_credentials.py` | **新建**：`XhsCredential`（account_id / cookie / user_id / source + `usable` + `scopes`）、`load_credential`（**唯一所有者**：两级来源 + fail-closed 边界）、`granted_scopes`（薄读，供 dispatcher）、`_read_stored`（默认读 `account_credentials`）、`_read_deployment`（默认读 `XHS_COOKIE`/`XHS_USER_ID`）、`_carries` |
| `config/settings.py` | `XHSPlatformSettings` 加 `cookie` / `user_id`（env_prefix `XHS_` ⇒ 正是 `.env.example` 声明的那两个键） |
| `tools/xhs/trending.py` | `_get_client` 从"没有 cookie 可给"改成"解析这个账号的凭据再给"；工厂与 `_require_readable` 的 docstring 同步改口径 |
| `creator_agent/execution.py` | `gateway_publish_dispatcher` 的 `granted_scopes` 默认从 `None`（=unchecked）改成**按 `request.account_id` 解析**；新增 `scope_resolver` 缝；模块 docstring"两条缝"→"三条缝" |
| `creator_agent/advisor.py` | `_execute_publish` 新增**第四道拒绝**（凭据），排在 `thread_id` / artifact / content-hash 三道**之前**；`_required_publish_scopes()` 从 registry **读**声明而非复述；构造器新增 `credentials` 缝 + `CredentialLoader` 别名 |
| `creator_agent/repository.py` | `ActionCredentialUnavailableError`（带 `account_id` / `required_scopes` / `reason`） |
| `api/errors.py` | `ErrorCode.CREATOR_ACTION_CREDENTIAL_UNAVAILABLE` + `CreatorActionCredentialUnavailableError`（**409**） |
| `api/routes/creator_agent.py` | `/execute` 接上 409 映射 |
| `creator_agent/__init__.py` | 导出新错误 |
| `docs/tool-runtime.md` | 「已知残留」两条结清（orphan 由 S4a 结清、读路径未鉴权由本片结清）并写下**新残留**；门禁说明的"当前唯一 orphan"改成"为空" |
| `tests/unit/services/test_xhs_credentials.py` | **新建，19 用例** |

**设计决定**

1. **一个所有者，两个读者**：cookie 与 scope 来自**同一个** `XhsCredential`，所以"这次平台调用带了凭据"与"它的 scope 被授予"不可能互相矛盾（S4b 的 `publish_is_dry_run` 同一手法）。
2. **账号自己的凭据是终局**：账号有行就绝不回退到部署级 —— **哪怕那一行不可用**。回退会以"调用方没点名的另一个身份"去读/发布，那是凭据解析唯一不能发明的失败。
3. **一行是陈述，一个空环境变量不是**：账号行存在但值为空 ⇒ 那是该账号被清空的凭据，仍是它的答案；`XHS_COOKIE` 为空 ⇒ 没人配过部署凭据，于是 `source` 返回 `""` 而不是"consulted 过 environment"。这条不对称是刻意的（写进模块 docstring）。
4. **fail-closed 落在边界上**（复用 S2 的教训）：**任何** reader（含注入的）抛异常 ⇒ 不可用凭据且**不回退** —— "读不到账号有没有自己的凭据"是未知，未知不是"可以用别人身份"的许可。
5. **"没有账号库" ≠ "读不到账号库"**：`is_pool_ready()` 为假（`db/accounts` 是 Postgres-only、无内存回落）是**配置事实**，部署级凭据仍适用；读失败才落边界。两条代码路径分开。
6. **可用性 = 存在 且 形状对**：`usable` 用 `XHSCookieParser.is_valid`（要 `a1` 且有材料）。给一个"能解析但无登录材料"的 cookie 会让 HTTP 客户端进入"配了但每次都失败"的状态 —— 那正是 `can_read` 存在的意义。
7. **一份可用凭据同时授予 read + write**：凭据**就是**账号的身份证据（写它的是同一次扫码登录，它也绑定了该账号的浏览器 profile）。从"浏览器可达"推 write 会让授权随 Chrome 进程停不停而翻转，而**可达性不是授权**；可达性留在原处（publisher 解析 endpoint，工具在浏览器不在时吵闹地失败）。规则只有一条：`usable ⇒ (xhs:read, xhs:write)`。
8. **凭据检查是第四道"Gateway 之前的拒绝"，且排最前**：S3 立下的结构是"每道拒绝都在 Gateway 之前"，本片加第四道。排最前不是因为它便宜，而是因为**授权不依赖 artifact** —— 把答案建立在 artifact 读之上，会让无授权的账号被告知"你的内容有问题"，并让判决依赖于 store 是否可达（M13 杀的就是这条）。
9. **必需的 scope 从 registry 读，不复述**：`_required_publish_scopes()` 读 `xhs.publish` 声明的 `auth_scope`。写死字面量是同一条要求的第二份陈述，而且**漂移是静默的**：Gateway 仍强制*声明*的那个，executor 却按另一个拒绝。
10. **拒绝是 409 不是 403**：403 留给 Policy Engine（一条规则说"不行"）；这里是"调用方被允许、能力可执行，但**账号**拿不出凭据"，与 `ActionPublishContentUnavailableError` 同族，也同样保证"Gateway 没被碰到、没有 receipt"。
11. **dispatcher 的默认从 `None` 改成"解析"**：`None` 的 Gateway 语义是 *unchecked*，而**未检查的要求与没有要求无法区分** —— 这正是 S3 那份 docstring 诚实地承认的状态，本片结掉它。`granted_scopes` 参数保留为显式覆写（测试用）。
12. **主链发布（S4a 那条）本片不接 scope 检查**：`_publish_gateway_account_id` 在账号未指定时**故意返回 `""`**（S4a 的决定，避免把未归属的发布挪进 `account:default` 冷却桶），而 `""` 解析不出授权 —— 在那里加检查等于**替待决问题 1 做裁决**（主链隐式账号 vs `account_id` 必填）。留给 S5b。
13. **读路径不接 scope 检查**：`_require_readable` 已是这条路径的诚实通道（`XHSAuthError` → Gateway 记 `ok=False` → 调用方降级）。再加一道会**把运行期条件变成接线异常**（`PermissionDeniedError` 是 raise，会穿过 `trend_scout` 的降级分支炸掉节点），失败模式反而更差。凭据缺失是运行时条件，不是接线错误。

**不做的事（本轮明确不碰）**

- **不给 `account_credentials` 写写入者**：把扫码登录拿到的 `web_session` 落进加密表是**登录流程**的改动（1900 行的 `xhs_login` + 一个新的 upsert API），属"凭据供给"而非"凭据所有权"。本片把它**钉成事实并写进残留**：今天唯一真能提供凭据的是部署级 `XHS_COOKIE`；per-account 那一行读路径已通、优先级已定，在登录流程开始写它之前是空的。
- 不动 `XHSClient` 第一层吞异常（`get_trending`/`search_posts` 的既有契约）—— 那是另一条残留。

**★ 绊线改形（按设计变红，改形不删）**

凭据拒绝**排在最前**，于是"每道拒绝都在 Gateway 之前"那组既有用例的**账号前提**变了：
`test_action_publish_execution.py` 的 `_advisor()` 工厂与 `test_action_publish_payload.py` 的
`_advisor_with_decision()` 都改成**给账号一个凭据**（`credentials=_credentialed`，一个合法的
`a1=…` cookie）—— 因为"发布测试的账号必须是有凭据的账号"才是真实前提，旧 fixture 之所以能跑，
只是因为这条规则不存在。**断言一条没动**（三条仍断言同样的 `ActionPublishContentUnavailableError`
+ 无 call + 无 receipt）。另一处：
`TestTheDefaultDispatcherIsTheRealPath::test_it_reaches_the_shared_gateway_and_the_lazily_resolved_tool`
从"直接调 dispatcher"改成"用 `XHS_COOKIE` 提供凭据后直接调 dispatcher" —— 它现在是**整条生产链**
的证据：环境 → `xhs_credentials` → scopes → `xhs.publish` 的声明 → Gateway → 工具。

**门禁（四道全绿，提交前实测）**

| 门禁 | 结果 |
|---|---|
| `pytest -q` | **3255 passed / 3 skipped** —— S4b 的 3227 + **28** = 19 + 5 + 1 + 2 + 1，恰等于新用例数（零既有用例被删，两条断言按上节改形） |
| `ruff check .` / `format --check .` | **505 files**（+2 新文件），All checks passed |
| `uv run mypy backend --python-version 3.12` | **204 source files, no issues**（+1 新模块） |
| P1b 基线 | `drift within threshold` |
| `tool_runtime_gate.py` | **OK**（orphan 仍为空；`named by agents: 10`） |
| 前端 | 本片**未改前端**，未跑（S4b 已记录：前端门禁需先 `npm install`） |

**突变自检：17/17 killed**，每条从原始字节起算、每条被具名断言杀掉；**step 0** 先把 23 个具名
击杀者在未改动树上跑一遍（全绿）→ 没有任何 "killed" 可能来自本来就红的测试。

| # | 突变 | 击杀者 |
|---|---|---|
| M1 | `usable` = 存在而非形状对 | `test_a_cookie_without_login_material_is_not_usable` + `...at_the_scope_check` |
| M2 | 不可用也授予两个 scope | 同上 + `...refused_before_the_gateway` |
| M3 | 账号凭据不可用 ⇒ 回退部署级 | `test_an_unusable_account_credential_is_not_overridden` + `...no_stored_material_is_empty` |
| M4 | reader 抛异常 ⇒ 回退部署级 | `test_a_raising_reader_yields_an_unusable_credential` |
| M5 | 默认 reader 去掉"无 pool"守卫 | `test_a_missing_account_store_is_not_a_reader_failure` |
| M6 | 默认 reader 不再按白名单过滤 | `test_only_allow_listed_rows_count_as_the_accounts_credential` |
| M7 | 读工厂解析了凭据却交出空值 | `test_a_resolved_credential_reaches_the_client` |
| M8 | `_require_readable` 永不触发 | `...gets_a_client_that_cannot_read` + `...refuses_to_report_an_empty_platform` |
| M9 | dispatcher 交 `None`（=S3 原状） | `...stops_the_publish_at_the_scope_check` |
| M10 | executor 永远找不到缺失 scope | `...refused_before_the_gateway` + 路由 409 用例 |
| M11 | 凭据拒绝变成"一刀切" | `test_a_credentialed_account_still_publishes` + `test_an_unreadable_artifact_is_refused` |
| M12 | 必需 scope 写成字面量 `("xhs:read",)` | `...required_scope_is_read_from_the_capability…` + `...refused_before_the_gateway` |
| M13 | 凭据检查挪到 artifact 读之后 | `test_entitlement_is_answered_without_reading_the_artifact` |
| M14 | 路由不再映射凭据拒绝 | `tests/unit/api/test_creator_agent.py::test_a_publish_without_a_credential_returns_its_own_409` |
| M15 | 409 改成 403 | 同上 |
| M16 | `XHS_WRITE_SCOPE` 漂移成 `"xhs:publish"` | `...scope_vocabulary_mirrors_the_catalogs_declarations` + `...at_the_scope_check` |
| M17 | 部署级凭据读成空 | `test_the_deployment_credential_is_the_single_account_fallback` + `...reaches_the_shared_gateway…` |

**修订：S5 拆成 S5a / S5b**（本片侦察时定）。票面那一行把两件正交的事捆在一起 —— **授权**
（谁可以调、凭什么）与**溯源 + 审计 + 文档**（我们记了什么）。合成一片会让"授权接对了没有"与
"audit 记全了没有"互相掩盖（与 S4 → S4a/S4b 的拆分理由同一逻辑）。S5a 做授权（本片：改生产行为，
单独一片才可归因）；S5b 做 `DecisionRecord` immutable 收尾 + 持久化"被拒"审计 + 协议文档 +
501 兜底与待决问题 1/3 的裁决。

**下一片（S5b）的入口条件**：① `DecisionRecord` immutable 收尾 —— `apply_feedback` 目前**在位改写**
记录（`backend/db/creator_agent.py:1182-1183` 内存分支与 `:1220-1221` Postgres 分支各一处），
与 `DecisionDatasetEntry` 的 "read-only projection of one **immutable** Decision Record snapshot"
自相矛盾；② 持久化"被拒"审计 —— S2 的 403 与 S4b 的 `cancelled` 至今只有日志/state，
`workflow_events` 的 `kind="action"` **至今无发射者**（S2 的裁决明写"与 immutable DecisionRecord
收尾同批"）；③ `docs/publish-action-protocol.md` —— 现在有了最后一块料（授权来源与 scope）；
④ **待决问题 1 仍在**（本片刻意没替它裁决，见设计决定 12）；⑤ 501 兜底清掉（`CREATOR_ACTION_CAPABILITY_NOT_WIRED`
已无生产者）；⑥ 本片留下的残留：`account_credentials` 仍无写入者。

### S5b — 记录的忠实性（`feat/p2a-s5b-record-fidelity`）

**范围**：让"记下来的东西不会事后变"这件事**真的成立**，两半 —— ① `DecisionRecord` 的**判据冻结**
（`apply_feedback` 是唯一写入者，且只动 `feedback` / `updated_at`）；② **"被拒"落审计**
（`kind="action"`，人类拒绝与策略拒绝各一条）。**不做**：`docs/publish-action-protocol.md`、
501 兜底、待决问题 1/3 的裁决（归 S5c）。

**侦察：票面对 ① 的定性要修正，对 ② 的定性要补充**

| # | 事实 | 位置 | 含义 |
|---|---|---|---|
| 1 | "immutable" 有**三处说法、一处实现**，而 `DecisionRecord` **自己的 docstring 一个字都没有** | 说法：`creator_agent/models.py:577`（`DecisionDatasetEntry`）、`api/routes/creator_agent.py:284`、`creator_agent/advisor.py:454`；实现：`apply_feedback` 整行 `UPDATE payload_json` | 不是"实现写错了"，是**一个没有名字、也没有断言的不变量** |
| 2 | **没有任何消费者依赖 `payload_json` 字节稳定**：数据集用 `REPEATABLE READ` 只承诺"**单次读内**稳定"，两个 feedback 过滤器跑在**纯投影**里（SQL 只过滤 account / audience / status） | `db/creator_agent.py:820-847`、`dataset.py:58-64` | 所以 A1（feedback 拆表）是**为一句 docstring 造表**；真正缺的是把**可变的边界**说准并钉住 |
| 3 | `EVENT_KINDS` 的 `"action"` 从 P1a 起就在"forward-looking set"里，注释自己写着 *"later slices will start emitting"* —— **至今零发射者**；而 `EVENT_KINDS` 本身**除了自己的 `__all__` 没有任何读者** | `db/workflow_events.py:126-128` | 与 `auth_scope` 同一族（**声明 ≠ 执行**）。本片给它装上发射者，并把"发射的 kind 必须在声明里"变成断言 |
| 4 | S2 的 403 与 S4b 的 `cancelled` 各自只有**半条**痕迹：403 有响应体 + warning 日志，`cancelled` 有 `phase=CANCELLED` + `publish_confirmation` | `creator_agent/advisor.py:404`、`agents/nodes/publish_gate.py` | 两者都回答"**这条线程**怎么了"，都不回答"我们**拒了多少、为什么拒**" |
| 5 | 发射范式已存在且只有一种：构造 entry + `emit_events(resolve_thread_id(state), [entry])` | `agents/nodes/_base.py:163`（`record_human_wait`）、`agents/base.py:592`（`_tool_event_sink`）、`agents/nodes/blogger_gate.py:103` | 不需要新机制，只需要新 kind 与一个新构造器 |

**改动（7 改 1 新）**

| 文件 | 改动 |
|---|---|
| `creator_agent/models.py` | `DecisionRecord` **补上 docstring**（冻结集 vs 追加集，并点名唯一写入者）；`DecisionDatasetEntry` 的 "immutable snapshot" 收窄为 "revision-pinned" |
| `db/creator_agent.py` | 新增 `_append_feedback(decision, feedback)` —— **唯一写入者**；内存与 Postgres 两个适配器都改走它（原先是各自重复同样两行赋值） |
| `creator_agent/advisor.py` | receipt 的 docstring 改口径：判据来自 **revision-pinned** 快照，追加的 feedback 不是它的一部分 |
| `state/events.py` | 新增 `ACTION_EVENT_KIND` / `ACTION_POLICY_DENIED` / `ACTION_PUBLISH_REFUSED` / `action_perf_entry(...)`；`__all__` 同步 |
| `api/routes/creator_agent.py` | 新增 `_record_action_refusal(...)`；`plan_creator_action` 在 `ActionPolicyDeniedError` 上发一条 `policy_denied`；数据集路由 docstring 改口径 |
| `agents/nodes/publish_gate.py` | 拒绝时发一条 `publish_refused`；新增 `_account_id()`（**一处规则两个读者**）；新增 `REFUSAL_HUMAN` / `REFUSAL_UNRECOGNISED` |
| `tests/unit/creator_agent/test_decision_record_fidelity.py` | **新建，8 用例** |
| 三个既有测试文件 | 追加 16 条（gate 7 / events 6 / api 3） |

**设计决定**

1. **选 A3（把边界说准并钉住），不选 A1/A2**：A1 把 feedback 拆成独立表、A2 每次 feedback 产生新 revision 行 —— 两者都改**存储形状**，而实测**没有任何消费者依赖 payload 字节稳定**（事实 2）。为一句 docstring 造表，等于把"文档不准"升级成"迁移风险"。真正缺的是把可变的边界**命名 + 断言**。
2. **可变边界只有两个字段，且理由要写出来**：`feedback`（追加）与 `updated_at`（它跟随 reaction 到达的时刻）。理由是**反应不参与判据** —— 它在决定**之后**才到，所以追加它不重写判决。这句话是新 docstring 的核心，也是"immutable"三处说法里唯一站得住的口径。
3. **`_append_feedback` 是唯一写入者，且"唯一"可测**：两个适配器原先各写两行相同赋值（两处漂移的机会）。抽成一个函数后，"唯一"从注释变成断言（源码里 `decision.feedback.append` 恰好一次 + 恰好两个调用点）。
4. **不变量用"推导"而不是"复述"**：冻结集 = `DecisionRecord.model_fields` 减去两个追加字段，并有一条测试断言比较**覆盖了全部字段** —— 以后新增字段会被默认纳入比较，而不是被静默忽略。
5. **审计用既有的 `action` kind，不新造**：它已经在 `EVENT_KINDS` 里躺了五个切片，注释也写着是留给后续的。新造一个 kind 只会让"声明集"与"实际集"继续分叉。
6. **发射点选在"最后还知道线程"的地方**：策略拒绝在 **route** 层发（`state/events.py` 明确把 routes 列为合法写者），因为 advisor 抛异常时已失去"这是哪条工作流"的上下文；人类拒绝在**节点**里发，因为拒绝是节点当场做的决定。
7. **两个拒绝理由不合并**：`human_refusal`（按设计工作）与 `unrecognised_decision`（版本错位，是要追的 bug）是不同事实，合成一个字符串就把要追的东西藏进噪声里。
8. **自由文本不进遥测**：人类的 `comments` 明确**不作为** `action_perf_entry` 的参数 —— Gateway trace sink 同一条规则（"事件说发生了什么，正文属于一次显式、已脱敏的导出"）。评论没丢，它仍在 `publish_confirmation` 里。
9. **`account_id` 一处规则两个读者**：`_account_id()` 同时喂 interrupt 的 `publish_summary` 与审计事件，否则"问的是哪个账号"与"记的是哪个账号"可以不一致。
10. **拒绝的持久化是 best-effort，拒绝本身不是**：`emit_events` 的存储失败被吞（P1a-S2 契约），所以遥测挂掉时拒绝照常生效；而"没有线程可归属"时**不发明一个**线程。
11. **发射的 kind 必须落在声明里**：一条断言把 `ACTION_EVENT_KIND` 与 `EVENT_KINDS` 互钉 —— S5a 对 `auth_scope` 那条教训（**声明 ≠ 执行**）的直接应用。

**不做的事（本轮明确不碰）**

- **不把 feedback 拆表、不给 `DecisionRecord` 造"真正的不可变"**（理由见设计决定 1）。
- **不改 `EVENT_KINDS` 本身**：它是声明集，本片的职责是让 `action` 不再空着，不是重排它。**附带残留**：`EVENT_KINDS` 除本片新增的互钉断言外**仍无任何读者**——声明集仍然没有执行者。
- 不动 `docs/tool-runtime.md` 的两条残留（`account_credentials` 无写入者、`XHSClient` 第一层吞异常）。

**★ 实测推翻的两条（原以为 vs 实测）**

1. **`policy_id` 不是 `GateBlock.reason`**：原以为事件里的 `policy_id` 会是 `"publish_cooldown"`，实测是 `"policy.action.risk_cooldown"`（`GateBlock.reason` 才是 `publish_cooldown`）。断言按实测值钉 —— 这正好印证 `CreatorActionPolicyDeniedError` docstring 那句"`policy_id` 是稳定句柄"：它指的是**策略枚举**，不是人类可读的原因。
2. **"没有 `thread_id` 的发布意图会被策略拒绝"不可达**：`ActionIntentRequest` 的 `_validate_publish_payload(require_thread=True)` 在**创建边界**就要求它（存储侧 `ActionIntent` 仍可空，那是为了让 pre-S3 的行仍可读）。于是"无线程"分支是**守卫**而不是活口 —— 处置是①把那个 422 写成断言（"策略引擎根本跑不到"），②直接对 `_record_action_refusal` 断言"把缺失原样传下去、绝不发明线程"，并在它的 docstring 里写明这是给"以后能被拒绝、却没有工作流的能力"准备的。

**门禁（四道全绿，提交前实测）**

| 门禁 | 结果 |
|---|---|
| `pytest -q` | **3279 passed / 3 skipped** —— S5a 的 3255 + **24** = 8 + 7 + 6 + 3，恰等于新用例数 |
| `ruff check .` / `format --check .` | **506 files**（+1 新文件），All checks passed |
| `uv run mypy backend --python-version 3.12` | **204 source files, no issues**（无新模块） |
| P1b 基线 | `drift within threshold` |
| `tool_runtime_gate.py` | **OK**（orphan 仍为空；`named by agents: 10`） |
| 前端 | 本片**未改前端**，未跑 |

**已知 flaky 一次**：首次全量里 `tests/unit/services/test_ripple_service.py::TestWaitForCompletionWithSSE::test_stale_sse_zero_progress_falls_back_to_time_estimate` 红；隔离复跑绿（0.65s），重跑全量 **3279 passed** 绿。是已登记的时钟依赖 flaky，非本片回归。

**突变自检：17/17 killed**，每条从原始字节起算；**step 0** 先把 17 个具名击杀者在未改动树上跑一遍（`17 passed`）→ 没有任何 "killed" 可能来自本来就红的测试。

| # | 突变 | 击杀者 |
|---|---|---|
| M1 | `_append_feedback` 丢掉它承诺的 `updated_at` | `TestTheJudgmentIsFrozen::test_the_reaction_is_appended_and_dated` |
| M2 | 反应插到队首而不是追加 | `...::test_reactions_keep_arriving_at_the_end` |
| M3 | helper 顺手改写一个**判据**字段（`confidence`） | `...::test_a_reaction_does_not_rewrite_what_judged_the_decision` |
| M4 | Postgres 适配器**又内联**自己的 append | `TestThereIsExactlyOneWriter::test_only_the_helper_mutates…` + `...both_storage_adapters_go_through_it` |
| M5 | 内存适配器又内联自己的 append | 同上两条 |
| M6 | 幂等重试报告"我创建了东西" | `TestAnIdempotentRetryIsATotalNoOp::test_the_same_reaction_twice…` |
| M7 | `ACTION_EVENT_KIND` 改名（声明与发射漂移） | `TestTheActionEntry::test_the_kind_is_one_the_event_store_declares` |
| M8 | 保留键写在 `fields` **之前**（可被覆盖） | `TestTheActionEntry::test_a_field_cannot_spoof_a_reserved_key` |
| M9 | entry 忘记自己的 `kind` | 同上 + `...round_trips_through_the_store` |
| M10 | 确认也记一条拒绝 | `TestTheRefusalIsRecorded::test_a_confirmation_records_no_refusal` |
| M11 | 所有拒绝都记成"人类拒绝" | `...::test_an_unrecognised_decision_is_recorded_as_its_own_reason` |
| M12 | 从 state 里漏自由文本进事件 | `...::test_a_human_refusal_leaves_an_audit_event`（**键集/全等断言是承重的那条**；`...carries_no_free_text` 拦不住空值，见下） |
| M13 | 账号解析不再读 `publish_options` | `...::test_the_record_names_the_account_the_prompt_named` + `TestInterruptPayload::test_payload_reports…` |
| M14 | route 不再记录拒绝 | `tests/unit/api/test_creator_agent.py::test_a_denied_publish_is_recorded_against_its_thread` |
| M15 | route 把策略拒绝记成人类拒绝 | 同上 |
| M16 | recorder 无线程时**发明**一个线程 | `...::test_the_recorder_passes_an_absent_thread_through` |
| M17 | recorder 丢掉收到的账号 | `...::test_a_denied_publish_is_recorded_against_its_thread` |

**两条要单记的 harness 结论**

- **M4 的锚点第一版不唯一**：`_append_feedback(decision, feedback)` 在文件里出现 **2 次**（两个适配器），而且**缩进不同也救不了** —— 搜 12 个空格时会在 16 空格那行的第 4 个字符处匹配。锚点必须扩到**第三行**（`await cur.execute(` vs `_mem_decisions[key] =`）才唯一。**"锚点失败"与"存活"必须分开报告**（S4b 立的规矩，本片又验一次）。
- **harness 的击杀判定方向写反了**：pytest **返回 0 = 用例通过 = 突变存活**，第一版写成 `returncode == 0 → killed`，于是 16 条全被报成"存活"，而日志摘要全是 `1 failed`。**"存活"必须与日志摘要对读**，不能只看自己算出来的布尔值 —— 这是"别只看退出码"那条纪律的一个新变体。
- **本片记账的一处自纠（提交前发现）**：账本初稿把新用例写成 "23 = 8 + 6 + 6 + 3"、全量 3278；提交前重数（`git show origin/main:<file>` 与工作树逐名对比）得 gate 实为 **7** 条 → 合计 **24**，3279。**pass 增量恒等于新用例数**这条判据正是靠"对不上"发现的 —— 对不上时先怀疑**自己的分解**，再怀疑树。（顺带：用 `^\s*def test_` 数用例会把带 `async def` 的文件数成 1 条，必须带 `(?:async\s+)?`。）

**修订：① 与 ② 同片；③⑤④ 归 S5c。** S2 在「待决问题 2」的裁决里明写：持久化"被拒"审计"留给 S5，**与 immutable DecisionRecord 收尾同批**"。上一轮我曾按"授权与溯源正交"提议把 ① 和 ② 再拆一次，**本片实测后撤回** —— 两者确实没有共同字段，但**票面已裁定的批次**比我的切片口味更该被尊重，而且审计**已经被推迟过一次**，再推一次正是那条裁决要防的漂移。③（协议文档）⑤（501）④（待决 1/3）的共同点是"**契约怎么表述**"而不是"记下了什么"，所以合成 S5c。

**下一片（S5c）的入口条件**

① `docs/publish-action-protocol.md` —— 料已齐（S5a 的授权来源与 scope + S5b 的两类拒绝与审计字段集）；
② **501 兜底** —— `ActionCapabilityNotWiredError`（`creator_agent/repository.py:98`）**全仓无 `raise`**，route 的 `except`（`api/routes/creator_agent.py:428-429`）永不触发；根因在 `advisor.py:482-511` 的 `execute_action` 用 `else` 把剩下的一切都当成 `REQUEST_MORE_EVIDENCE`。**修法**：换成对 `ActionCapability` 的**穷举 match**，`case _:` 里 raise → ① 让那条 except 变活；② 把 fail-closed 默认装回去（新能力默认拒绝而非默认成功）。既有测试只是**直接构造错误对象**断 501 —— 断的是**形状不是路径**，要改成走 `execute_action` 的路径测试；
③ **待决问题 1** —— 仍无产 `ActionIntent` 的调用者，**裁决没有落点**；S5c 若仍无落点，就明确记为"延后"，而不是继续挂一条看起来待办的行；
④ 本片残留：`EVENT_KINDS` **仍无读者**（除了本片新增的互钉断言）；`account_credentials` 仍无写入者。
