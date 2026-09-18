# Publish Action 协议（P2a）

一个会**产生外部副作用**的动作，不能是"模型决定完了顺手就做"的副产品。

这层协议存在的理由只有这一个：把"想发"（intent）、"允许发"（policy）、"有人授权发"（human
confirm）、"真的发了"（execution）拆成**四个可以被单独读、单独拒、单独审计的状态**。在这之前
三者是同一个事件 —— `run_publish` 被调用就等于内容合格、等于有人同意、等于发出去了，事后没有
任何东西能把它们分开看。

```text
plan_action ──policy──▶ ActionIntent(pending_confirmation) ──resolve──▶ confirmed
                                                            │
                                                    execute_action
                                                            │
                          credential ─▶ artifact ─▶ content hash ─▶ Tool Gateway ▶ receipt
```

入口是 API（形状见 [creator-agent.md](creator-agent.md#创建和解析-action-intent)），
实现分布在 `backend/creator_agent/{models,advisor,execution,repository,policy}.py`
与 `backend/api/routes/creator_agent.py`。

## 四条拒绝，各在不同的层

| 阶段 | 拒绝时 | 谁拒 | 留下什么 |
|---|---|---|---|
| plan | **403** `..._POLICY_DENIED` | deterministic Policy Engine | **不产生 intent**；一条 `kind="action"` 的审计事件 |
| execute（未确认） | **409** `..._EXECUTION_NOT_ALLOWED` | executor | 无 receipt |
| execute（凭据） | **409** `..._CREDENTIAL_UNAVAILABLE` | executor | 无 receipt、**未读 artifact** |
| execute（能力未接线） | **501** `..._CAPABILITY_NOT_WIRED` | executor 的兜底 | 无 receipt |
| execute（内容不可用） | **409** `..._PUBLISH_CONTENT_UNAVAILABLE` | executor | 无 receipt、未到 Gateway |

两处口径值得单说：

- **policy 拒绝不产生 intent**（S2 的待决问题 2 裁决）：一个永远无法被确认的 intent 不是记录，
  是垃圾。所以"被策略拦下"这件事落在 **thread 的审计时间线**上（见下），而不是造一条永远停在
  `pending_confirmation` 的行。
- **未确认的 intent 必须无法被 execute**：这是红线，由 `ActionExecutionNotAllowedError` 保证。
  `execute_action` 在读取 Decision Record **之前**就完成这项检查，所以"未授权"永远比"内容问题"
  先被回答。

## 执行前的检查顺序是设计的一部分

`execute_action` 里四道检查的顺序不是随意的，它按**依赖强度**排：

1. **确认状态**（不依赖任何外部数据）
2. **能力已接线**（同样只依赖 intent 自己）
3. **凭据与 scope**（依赖账号状态，**不依赖 artifact**）
4. **artifact 可读 → 内容 hash 与人类确认的一致**
5. 才进 Tool Gateway

第 3 条排在第 4 条之前是有理由的：**授权不依赖 artifact**。反过来排会让"这个账号根本没有发布
凭据"被回答成"你的内容有问题"，而且判决会取决于 artifact store 是否可达 —— 一个与授权无关的
组件挂掉，不该改变授权结论。

凭据的唯一所有者是 `backend/services/xhs_credentials.py`（P2a-S5a）：**账号行优先，且账号行
不可用时不回退**到部署级 `XHS_COOKIE`。回退会把"这个账号没有凭据"静默变成"用部署的身份替它
发布"。同一个 `XhsCredential` 同时喂 cookie（给 client）与 scopes（给 Gateway），所以
**"带了凭据"与"被授权"不可能矛盾**。

## 四个 capability

`ActionCapability` 是协议声明，`execute_action` 必须**逐个具名**地对待它们：

| capability | 行为 | 结果来源 |
|---|---|---|
| `compare_options` | 本地确定性 | Decision Record 的候选投影 |
| `save_shortlist` | 本地确定性 | intent 的 `candidate_ids` |
| `request_more_evidence` | 本地确定性 | Decision Record 的覆盖率/置信度 |
| `publish` | **副作用**，经 Tool Gateway | Gateway 的 `ToolResult` 翻译后的 receipt |

**默认分支只允许做一件事：拒绝。** `execute_action` 的兜底会抛
`ActionCapabilityNotWiredError`（→ API 501），绝不返回"另一种 capability 的 receipt"。

这不是理论问题：在 P2a-S5c 之前，那条 `else` 把**任何**它不认识的 kind 都答成了
`request_more_evidence` 的结果。它当时不可达（四个成员都有分支），但它意味着**一份 durable、
immutable 的收据可以声称做过一件从未发生的工作** —— 而 receipt 的全部价值就在于它不能这样。
兜底装上 `raise` 之后，"新增一个 capability 但忘了接执行器"这件事变成一次吵闹的 501，而不是
一条看起来很正常的收据。

`tests/unit/creator_agent/test_action_execution.py` 用两半钉住这个性质：一条行为测试（一个
执行器不认识的 kind 被拒、且**没有留下 receipt**）与一条结构测试（每个声明成员都在
`execute_action` 里被具名 —— 加了成员却不加分支，测试当场指出缺哪个）。

## 幂等：两层，各有各的职责

同一个词（`idempotency_key`）在两个层出现，这不是两套幂等，而是两件事：

| 层 | 键 | 作用 | 谁判定 |
|---|---|---|---|
| 内容级 | `compute_publish_id(state)` | 同一份内容**跨请求**不重复发布 | 主链（`agents/publisher.py`） |
| 请求级 | `ActionIntent.idempotency_key` | 同一个**请求**不产生第二个 intent | `UNIQUE (account_id, idempotency_key)` |
| 运行时 | payload 的 `idempotency_key` | **只是重试护栏的输入** | Gateway 的 `RetryPolicy` |

第三行是唯一容易误读的地方：**Gateway 不用它去重**，它只要求这个字段存在
（`requires_idempotency_key`）才允许对 side-effecting 工具重试 —— 重试一个没有幂等键的发布
等于赌一次重复发布。所以两个生产者往同一个字段里放的是不同的稳定串（主链放 content 级键、
控制面放请求级键），而这是**刻意的**：它们的共同点只是"对这个 intent 稳定"。

## 被拒也留痕（P2a-S5b）

`workflow_events` 的 `kind="action"` 从 P1a 就声明着，直到 P2a-S5b 才有第一个发射者。两条：

- **策略拒绝**（route 层发，`policy_denied`）：advisor 抛异常时已经失去了"这是哪条工作流"的
  上下文，route 是最后还知道 `thread_id` 的地方。
- **人类拒绝**（publish gate 发，`publish_refused`）：拒绝是节点当场做的决定，理由分
  `human_refusal`（按设计工作）与 `unrecognised_decision`（版本错位，是要追的 bug）。

**自由文本不进遥测**：人类的 `comments` 留在 `publish_confirmation` 里，不作为事件字段 ——
与 Gateway trace sink 同一条规则（事件说发生了什么，正文属于一次显式、已脱敏的导出）。
`account_id` 由**一个** helper 同时喂 interrupt 负载与事件，于是"问的是哪个账号"与"记的是哪个
账号"不可能不一致。

## 加一个新 capability

1. 在 `ActionCapability` 加成员（`backend/creator_agent/models.py`）。
2. 在 `execute_action` 里给它**一个具名分支**。忘了这一步不会被静默吞掉：兜底会拒绝，且
   `test_every_declared_capability_has_its_own_arm` 会直接指出缺哪个成员。
3. 若它产生副作用 → 只能经 **Tool Gateway**（P1c 纪律：`backend/agents/**` 不得直调
   `backend.tools`），并确保 payload 带幂等键。
4. 若它暂时**没有**执行器 → 保持 501。**不要**为了"先让它跑通"给一个像样的 receipt：
   receipt 是 durable 且 immutable 的，撒谎的收据比一次失败贵得多。

## 已知残留

- **主链仍不经控制面**：`publisher` 直接调 `run_publish`（S4a/S4b 的刻意决定），所以
  intent → policy → confirm → execute 这条链今天只在 **API 路径**上。这也意味着
  **待决问题 1 仍无落点**（见下）。
  - ⚠️ **名字**：计划行把这一环写成 `PublishIntent`，**落地对象叫 `ActionIntent`**
    （`backend/creator_agent/models.py`）—— `grep -rn PublishIntent backend/` 是**零命中**。
    下面表里的主张一律用落地名：一条点名了「树里不存在的对象」的主张，会让读者连
    对的那半句一起怀疑。
- **`EVENT_KINDS` 的 `cost` / `error` 仍无发射者**：`error` 走的是 realtime
  `EventBusService`，不是 `workflow_events` 这一层；`ripple` 只出现在 S2 迁入的历史条目里。
  `EVENT_KINDS` 本身除自己的 `__all__` 仍**没有读者** —— 声明集仍然没有消费者。
- **`account_credentials` 表仍无写入者**：读路径（S5a）是通的，但扫码登录把登录态写进 CDP
  profile，没有写这张表。所以今天唯一真能提供凭据的仍是部署级 `XHS_COOKIE`。

**这三条都是关于代码的、可测量的事实**（「还有几个调用点」「还有几个读者」「还有几个写入者」），
所以它们在这里发布成值，由 `tests/unit/scripts/test_residue_claims.py` 从树上重算。
**把它们修好而不改这张表，判据会红** —— 这是本节唯一的目的：本仓已经有过一次「登记项被结掉了、
记录继续声称它开放」的经历（`docs/planning.md` 的 `orchestrator_router` 缺键那条，
见 `tests/unit/graph/test_routers.py` 的 `test_brief_mode_creating_routes_to_the_copywriter`），
而当时没有任何机制察觉。散文写的残留就是那个机制缺口。

<!-- claim-table:begin -->

| 主张 | 发布的值 | 复核方式 |
| --- | --- | --- |
| `mainline_run_publish_direct_call_sites` | `3` | AST：`backend/**/*.py` 里 `run_publish(...)` 的调用点，**排除函数定义本身** |
| `action_intent_construction_sites` | `1` | AST：全仓 `ActionIntent(...)` 的构造点；唯一那个在控制面内 |
| `mainline_action_intent_producers` | `0` | 上一个集合里落在 `backend/creator_agent/` **之外**的个数（上一条是它的阳性对照） |
| `event_kinds_readers_outside_its_defining_module` | `0` | AST：除 `backend/db/workflow_events.py` 外，import 或引用 `EVENT_KINDS` 的文件数（**注释不算**） |
| `account_credentials_inserts` | `0` | 正则：`backend/**/*.py` 里 `INSERT INTO account_credentials` 的次数（DDL / `SELECT` / `DELETE` 都不算） |

<!-- claim-table:end -->

## 待决问题 1 的裁决（P2a-S5c）

问题：`ActionIntentRequest.account_id` 显式必填，而主链只知道隐式账号 —— 谁向谁让步？

**裁决：显式必填不变；将来主链若迁移到控制面，它必须显式解析出账号，不得让空账号进入预算。**
理由：`account_id` 是策略与冷却桶的键。S4a 已经因为这一点让未指定账号的发布携 `""` 而不是
`"default"`（"未归属的发布不该落进 `default` 账号的冷却桶"）；同一个不变量在这里就是
"**永不发明账号**"—— 与 S5b 的"没有 `thread_id` 时不发明线程"是同一条。

**这是一个裁决 + 一个触发条件，不是一条待办**：今天没有任何产生 PublishIntent 的主链调用者
（主链直接 `run_publish`），所以这个裁决没有可落地的代码位置；它约束的是**将来那次迁移**。
