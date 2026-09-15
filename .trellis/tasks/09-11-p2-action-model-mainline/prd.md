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
| S4 | **主链接入**：`PublisherAgent`/`publisher_node` 改为产出 PublishIntent + 等确认；**`xhs.publish` orphan 消失** → tool runtime 门禁那条"唯一 orphan 是 xhs.publish"断言会红，**同 PR 更新** | 高 |
| S5 | **凭据整备** + DecisionRecord immutable 收尾 + `docs/publish-action-protocol.md` | 中 |

切片顺序的判据：先把**纯数据面**（S1）落定，再落**纯判定**（S2），然后才跨"产生副作用"
这道坎（S3），最后才动主链（S4）。S3 之前任何一片都不改变生产行为。

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

**下一片（S3）的入口条件**：① PUBLISH 经 Tool Gateway 调 `xhs.publish`，`ActionCapabilityNotWiredError` 必须消失；② **记账必须用同一个 key** —— `note_publish` 要带上 account_id，否则 `RISK_COOLDOWN` 这条规则依旧是死的（见上面的钉法）；③ 幂等键就位**之后**才解锁 catalog 的 `RetryPolicy`。
