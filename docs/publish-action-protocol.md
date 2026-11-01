# Publish Action 协议（P2a）

一个会**产生外部副作用**的动作，不能是"模型决定完了顺手就做"的副产品。

这层协议存在的理由只有这一个：把"想发"（intent）、"允许发"（policy）、"有人授权发"（human
confirm）、"真的发了"（execution）拆成**四个可以被单独读、单独拒、单独审计的状态**。在这之前
三者是同一个事件 —— `run_publish` 被调用就等于内容合格、等于有人同意、等于发出去了，事后没有
任何东西能把它们分开看。

```text
plan_action ──policy (+ stamped / account-level judgers)──▶ ActionIntent(pending_confirmation)
                                                            │ resolve
                                                            ▼ confirmed
                                                    execute_action
                                                            │
     credential ─▶ artifact ─▶ content hash ─▶ decide_publish_eligibility ─▶ Tool Gateway ▶ receipt
```

「能不能发」与工作流共用
`backend.services.compliance.judgers.decide_publish_eligibility`（经
`backend.services.compliance.projection` 投影成 state-like dict，**不复制规则表**）：

| 层 | 何时跑 | 输入 | 失败时 |
|---|---|---|---|
| **plan** | `evaluate_action_policy`（账号/冷却之后） | 有 `thread_id` 时由 `load_action_policy_context_from_thread` **自动**从工作流 checkpoint 读取 stamped `publish_eligibility`（及 niche / `auto_publish` 等）；显式 `policy_context=` 可覆盖（测试）；账号级判定器 `PLAN_TIME_JUDGERS`（`dual_auto` / `high_risk_auto`）；**不读 artifact**、不跑正文 lexicon/disclosure；缺 stamp 不拒（execute 仍判正文） | stamped / dual_auto → **403** `policy.action.publish_eligibility_denied`；checkpoint/graph 不可读 → **403** `policy.action.eligibility_context_unavailable`；**不产生 intent** |
| **execute** | artifact 可读且 content hash 一致之后、Gateway 之前 | artifact 正文投影 | **409** `..._PUBLISH_ELIGIBILITY_DENIED`；无 receipt；`publish_blocked` / `publish_eligibility_denied` 审计 |

入口是 API（形状见 [creator-agent.md](creator-agent.md#创建和解析-action-intent)），
实现分布在 `backend/creator_agent/{models,advisor,execution,repository,policy}.py`
与 `backend/api/routes/creator_agent.py`。

## 拒绝分层

| 阶段 | 拒绝时 | 谁拒 | 留下什么 |
|---|---|---|---|
| plan | **403** `..._POLICY_DENIED` | deterministic Policy Engine（含 publish judgers） | **不产生 intent**；一条 `kind="action"` 的审计事件 |
| execute（未确认） | **409** `..._EXECUTION_NOT_ALLOWED` | executor | 无 receipt |
| execute（凭据） | **409** `..._CREDENTIAL_UNAVAILABLE` | executor | 无 receipt、**未读 artifact** |
| execute（能力未接线） | **501** `..._CAPABILITY_NOT_WIRED` | executor 的兜底 | 无 receipt |
| execute（内容不可用） | **409** `..._PUBLISH_CONTENT_UNAVAILABLE` | executor | 无 receipt、未到 Gateway |
| execute（判定器拒绝） | **409** `..._PUBLISH_ELIGIBILITY_DENIED` | `decide_publish_eligibility` | 无 receipt、未到 Gateway；`publish_blocked` 审计 |

两处口径值得单说：

- **policy 拒绝不产生 intent**（S2 的待决问题 2 裁决）：一个永远无法被确认的 intent 不是记录，
  是垃圾。所以"被策略拦下"这件事落在 **thread 的审计时间线**上（见下），而不是造一条永远停在
  `pending_confirmation` 的行。
- **未确认的 intent 必须无法被 execute**：这是红线，由 `ActionExecutionNotAllowedError` 保证。
  `execute_action` 在读取 Decision Record **之前**就完成这项检查，所以"未授权"永远比"内容问题"
  先被回答。

## 执行前的检查顺序是设计的一部分

`execute_action` 里检查的顺序不是随意的，它按**依赖强度**排：

1. **确认状态**（不依赖任何外部数据）
2. **能力已接线**（同样只依赖 intent 自己）
3. **凭据与 scope**（依赖账号状态，**不依赖 artifact**）
4. **artifact 可读 → 内容 hash 与人类确认的一致**
5. **`decide_publish_eligibility`（正文投影）** — lexicon / disclosure 等需正文的判定器
6. 才进 Tool Gateway

第 3 条排在第 4 条之前是有理由的：**授权不依赖 artifact**。反过来排会让"这个账号根本没有发布
凭据"被回答成"你的内容有问题"，而且判决会取决于 artifact store 是否可达 —— 一个与授权无关的
组件挂掉，不该改变授权结论。第 5 条必须在 Gateway 之前：判定器失败不得产生 receipt，也不得
调用副作用能力。

凭据的唯一所有者是 `backend/services/xhs_credentials.py`（P2a-S5a）：**账号行优先，且账号行
不可用时不回退**到部署级 `XHS_COOKIE`。回退会把"这个账号没有凭据"静默变成"用部署的身份替它
发布"。

同一个 `XhsCredential` 同时回答两件事：cookie 给 HTTP client，`scopes` 给 Gateway。但
`scopes` **不是**"有 cookie"的同义词 —— 读走 `XHSClient`（身份就是 cookie），发布走
`XHSPublisher(cookie="")`（身份是账号自己绑定的浏览器 profile）。所以规则按机制给：

| scope | 什么时候有 | 为什么 |
|---|---|---|
| `xhs:read` | cookie 可用 | 读只有 HTTP 这一条路，没有 cookie 就没有可用的身份 |
| `xhs:write` | cookie 可用 **∨** 已绑定 profile | 发布走 CDP，评论/私信走 HTTP，两条机制任一成立即可 |
| `xhs:outreach` | （cookie 可用 **∨** 已绑定 profile）**∧** 该账号的触达策略允许触达（`mode != nobody`） | 唯一一个**机制 ∧ 策略**档：两个登录完全相同的账号可以在这里不同。票 5av 起它的语义收紧为「账号被允许触达」而不是「允许冷启动」：默认 `inbound_only` 也持有它（应答式回复本就允许），`nobody` 才失去它；某个目标是不是冷启动、是否超每日主动预算，仍是服务层按目标 + 人工确认把关（scope 无法表达条件权限）。策略解析见 `docs/tool-gateway-engagement-migration.md` §9.5 |

"已绑定 profile"对**具名账号**读的是它自己的 `cdp_port`；对**空 account_id** 读的是
部署声明的 `XHS_CDP_ENDPOINT`（单账号部署就是"这个部署有一台自己的浏览器"，与
`XHS_COOKIE` 的地位对称）。两者都**只读声明，不探测**浏览器是否在跑 —— 授权不该随一个
Chrome 进程的启停翻转；浏览器没开由发布工具自己报 `cdp_unavailable`。既然授权指的是
"这个账号的浏览器"，payload 就带上它的 `cdp_endpoint`，而不是让工具回落到账号无关的
全局那台。
细节见 `docs/tool-gateway-engagement-migration.md` §9.6。

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

## 被拒也留痕（P2a-S5b / 票 5k）

`workflow_events` 的 `kind="action"` 从 P1a 就声明着，直到 P2a-S5b 才有第一个发射者。三条：

- **策略拒绝**（route 层发，`policy_denied`）：advisor 抛异常时已经失去了"这是哪条工作流"的
  上下文，route 是最后还知道 `thread_id` 的地方。
- **人类拒绝**（publish gate 发，`publish_refused`）：拒绝是节点当场做的决定，理由分
  `human_refusal`（按设计工作）与 `unrecognised_decision`（版本错位，是要追的 bug）。
- **发布路径自身的前置条件**（publisher 发，`publish_blocked`，票 5k）：账号停用/不存在、
  未绑定 CDP endpoint、没有 `xhs:write` 授权、幂等账本拦住重复发布 —— 四者都是"这次发布
  **没有尝试**"，没有调用任何 capability，因而不可能有 effect。与"人类拒绝"（`publish_refused`）
  和"策略拒绝"（`policy_denied`）是不同的事实（没人说过"不"；是环境/前置条件不允许），
  所以用**新的 action 名 + 封闭 reason 词表**（`account_inactive` / `missing_cdp_endpoint` /
  `missing_credential` / `duplicate_publish` / `publish_eligibility_denied`），而不是塞进任何一个旧名字。重复发布那条额外带
  `publish_id` 与 `prior_status`（机器可读的"为什么"）。**每个线程的 `publish_result` 仍然回答
  "这次怎么了"；action 账回答"多久发生一次、为什么"** —— 与 publish gate 那条同一分工。

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

> 主链迁移（票 5au 四阶段 P1–P4）已收口：三条主链发布路径统一经
> `backend/creator_agent/mainline_publish.py:execute_mainline_publish`（P3b-2，票 5bg），
> 实现体为私有 `agents/publisher.py:_run_publish_attempt` 且无公开别名（P4，票 5bh）；
> 该入口决定身份（review 审批原样传递 / free 的操作员身份 / 无账号不产生），发布前
> 已跑共享策略（P2），主链发布 intent 由入口链路产出并落库（P1b）。下面剩余条目属于
> 其他主题，不再涉及主链执行边界。
- ~~**`EVENT_KINDS` 的 `cost` / `error` 仍无发射者**~~ **已收口（票 5ao）**：两条 kind
  从 `EVENT_KINDS` 退休 —— 它们从来没有发射者，且各自已有权威载体：cost 落在
  `kind:"llm"` 条目的 `cost_usd`（`/analytics/costs` 从这里聚合），error 的实时通道是
  realtime `EventBusService.WORKFLOW_ERROR`、持久面是 `kind:"node"` 的 `status`/`error`。
  补发射端会给同一事实造第二份真相，所以选择让**声明集追上发射面**；现在的声明集由
  `tests/unit/db/test_workflow_events_kinds.py` 钉成字面量（加回任何 kind —— 包括这两条
  —— 都要改它，即一次有意识的决定）。`EVENT_KINDS` 仍有**一个**外部读者
  `backend/services/signal_inventory.py`，它把未声明的 `kind` 报成"声明漂移"（#676
  那类事故的唯一可见出口）；读者不替发射端兜底的性质没变，变的是不再有"声明了但没人写"
  的条目藏在声明集里。
- ~~**`account_credentials` 表仍无写入者**~~ **已解决（票 5n）**：扫码登录确认成功后，
  `XhsLoginSession._persist_login_cookie` 把 cookie 经 `db.crypto` 加密 upsert 进
  `account_credentials`（`(account_id, key_name)` 唯一，重登即替换）。三条护栏：只写
  **已证明的登录**（creator token 谓词；www-only 半登录不写）、只写**读侧会接受的**
  cookie（`XHSCookieParser.is_valid` ⇔ `XhsCredential.usable`）、无账号库时跳过；落库
  失败 best-effort。**诚实边界**：行优先于部署 env 的 `XHS_COOKIE`，cookie 过期后需重扫码
  刷新（过期行会暂时遮蔽仍可用的部署 cookie）。

**这几条都是关于代码的、可测量的事实**（「还有几个调用点」「还有几个读者」「还有几个写入者」），
所以它们在这里发布成值，由 `tests/unit/scripts/test_residue_claims.py` 从树上重算。
**把它们修好而不改这张表，判据会红** —— 这是本节唯一的目的：本仓已经有过一次「登记项被结掉了、
记录继续声称它开放」的经历（`docs/planning.md` 的 `orchestrator_router` 缺键那条，
见 `tests/unit/graph/test_routers.py` 的 `test_brief_mode_creating_routes_to_the_copywriter`），
而当时没有任何机制察觉。散文写的残留就是那个机制缺口。票 5n 刚走过一次这个机制：写入者
从 0 变 1，表同步改成 1。★ 票 5ao 的收口形状不同：它不是把某个值从 0 变 1，而是把
**声明面缩到与发射面一致**（删掉两条从未被写入的 kind）—— 因此没有 claim 值可改，
守卫落在那条钉住完整声明集的单测里；`event_kinds_readers_outside_its_defining_module`
仍为 1。

<!-- claim-table:begin -->

| 主张 | 发布的值 | 复核方式 |
| --- | --- | --- |
| `action_intent_construction_sites` | `2` | AST：全仓 `ActionIntent(...)` 的构造点；advisor 一处 + 主链 producer 一处（票 5bc） |
| `mainline_action_intent_producers` | `1` | 上一个集合里落在 `backend/creator_agent/` **之外**的个数（上一条是它的阳性对照） |
| `event_kinds_readers_outside_its_defining_module` | `1` | AST：除 `backend/db/workflow_events.py` 外，import 或引用 `EVENT_KINDS` 的文件数（**注释不算**）；今天那 1 个是 `backend/services/signal_inventory.py` 的漂移检测 |
| `account_credentials_inserts` | `1` | 正则：`backend/**/*.py` 里 `INSERT INTO account_credentials` 的次数（DDL / `SELECT` / `DELETE` 都不算）。票 5n 起唯一那处是扫码登录的 `upsert_credential` |

<!-- claim-table:end -->

## 待决问题 1 的裁决（P2a-S5c）

问题：`ActionIntentRequest.account_id` 显式必填，而主链只知道隐式账号 —— 谁向谁让步？

**裁决：显式必填不变；将来主链若迁移到控制面，它必须显式解析出账号，不得让空账号进入预算。**
理由：`account_id` 是策略与冷却桶的键。S4a 已经因为这一点让未指定账号的发布携 `""` 而不是
`"default"`（"未归属的发布不该落进 `default` 账号的冷却桶"）；同一个不变量在这里就是
"**永不发明账号**"—— 与 S5b 的"没有 `thread_id` 时不发明线程"是同一条。

**这是一个裁决 + 一个触发条件，不是一条待办**：迁移（票 5au）已经让主链**显式解析**发布主体并
尊重这条裁决 —— review 审批产生 mainline 身份、部署本体不构造 account-scoped intent；将来若引入
新的发布主体，仍必须先满足它。

## 主链迁移控制面：阶段方案（票 5au）

> 裁定（2026-10-31）：迁移。上文「已知残留」第一条的开放状态不变——**本方案只切阶段，
> 不改今天的行为**；每个阶段单独开票、单独验收、单独回滚，stage 边界由 claim 表数值定义。

### 起点（可复算）

| 事实 | 今天 | 复核 |
| --- | --- | --- |
| 主链执行入口 | 单一入口 `execute_mainline_publish`；无公开直调符号（票 5bg/5bh） | AST 不变量测试（`test_mainline_publish_entry.py`） |
| 主链产出 `ActionIntent` | `mainline_action_intent_producers = 1`（票 5bc 起） | claim 表（AST） |
| 控制面 intent 构造点 | `action_intent_construction_sites = 2`（advisor + 主链 producer） | claim 表（AST） |

三条主链发布路径：`backend/agents/publisher.py`（主链发布节点）、
`backend/api/routes/_wf_actions.py`（publish-retry 通道）、`backend/api/routes/free.py`
（free 模式）。它们都经**单一执行入口**
`backend/creator_agent/mainline_publish.py:execute_mainline_publish` —— 该入口负责
**决定身份**（review 审批原样传递；free 发布由操作员显式产生
`free_publish_operator` 身份；无账号则不产生身份），实现体
`agents/publisher.py:_run_publish_attempt` 为私有、无公开别名（P4 收口）。

### 可复用的控制面零件（不重写）

- `ActionIntent` + 请求/回执模型：`backend/creator_agent/models.py`；
- intent 构造与审批入口：`backend/creator_agent/advisor.py`；
- policy 评估：`backend/creator_agent/policy.py`；
- 执行 dispatcher（Gateway `xhs.publish` + `granted_scopes` + 账本/回执）：
  `backend/creator_agent/execution.py`（其 `PublishDispatcher` 就是可注入的 seam）；
- capability 声明与 scope 检查：`backend/tools/runtime/catalog.py`、`backend/tools/runtime/gateway.py`。

### 阶段

**P1 — 显式主体 + 意图生产者（不改执行器）**

P1 在落地时被切成两半，因为一个前提不成立：控制面的意图对象**不是主链能直接构造的**。

**P1a — 可派生的部分（已落地，票 5ba）**：主链发布前把行为主体**显式分类**为
「具名账号」或「部署本体」（`backend/services/publish_intent.py` 的
`resolve_publish_principal`），并把本次提交内容写成
`artifact://publish_content/<publish_id>` + sha256；PREPARED 记录携带
`principal_kind` / `principal_account_id` / `artifact_ref` / `content_hash`。
空账号仍表示部署本体（凭证解析器本来就按部署声明解析它，不是发明账号），
执行器、幂等键与 publish_result 全部不变。claim：直调仍 `3`；生产者随后由 P1b-2 从 0 变 1。

**P1b — 身份模型（未拍板，先别构造 `ActionIntent`）**：`ActionIntentRequest` 需要
`decision_id`，`ActionIntent` 还要 `creator_id` / `audience_id`；主链三者都没有，
而 `DecisionRecord` 是 creator_agent 概念（`audience_id`、`model_revision`、
ranked candidates）。所以在主链构造控制面对象 = 发明身份，正是待决问题 1 禁止的方向。
需要先选一条路：
- **A（推荐，窄版）**：控制面接受 `origin="mainline"` 的意图，`creator_id`/`audience_id`
  对 mainline origin 可空，并让主链审批时间点产生一条**最小 decision 记录**
  （decision_id、thread_id、account_id、publish_id、approved_by/at、content_hash、artifact_ref）；
  涉及 `ActionIntent`/`ActionIntentRequest` 模型与 intent 表的列迁移。
- **B**：主链自有意图模型 + 执行器适配层（控制面不泛化，切换成本在 P3 体现）。

**A 的模型半步已落地（票 5bb，2026-11-01）**：`ActionIntent` 新增 `origin`
（`ActionOrigin.CREATOR` / `MAINLINE`）；creator origin 强制 `creator_id`/`audience_id`
非空，mainline origin 禁止携带二者（不能借创作者的身份证）；`/creator_agent` 既有
构造路径与 API 契约不变，旧行缺 `origin` 时读作 creator。存储是整行 `payload_json`，
因此**无需列迁移**。在 P1b-2 之前，构造点只有 `creator_agent/advisor.py` 一处 ——
`action_intent_construction_sites` 当时为 `1`。

**P1b-2 已落地（票 5bc，2026-11-01）**：review 审批端点在批准**真实**发布时写入
`state["publish_decision"]` —— `decision_id`（`mainline:<uuid>`，审批事件自己的身份，
不由内容派生）、`thread_id`、`account_id`、`content_hash`（审批时内容哈希，绑定
"批准了哪份内容"而不绑定时间窗漂移的 publish_id）、`approved_by`/`approved_at`。
`execute_mainline_publish`（单一入口）在 Effect 账本 claim 成功后消费它：只有 **account-scoped**
（部署本体不构造：模型是 account-scoped 的）、内容哈希一致、账号一致、thread 非空时，才构造
`origin=mainline` 的 `ActionIntent`（`creator_id`/`audience_id` 为空、
`status=CONFIRMED`、`resolved_at=approved_at`、`idempotency_key=publish_id`）并经
creator-agent 仓库落库。**执行仍走入口背后的私有 attempt**（票 5bg/5bh）；构造失败/不匹配一律
best-effort 跳过并记日志，绝不影响发布。因此 `action_intent_construction_sites` = `2`
（advisor + `services/publish_intent.py`），`mainline_action_intent_producers` = `1`；
直调 `3` 已在 P3b-2 降为 `0`。

- claim：`mainline_action_intent_producers` 0 → **1**；直调 `3`（P3b-2 后为 `0`）。
- 验收（P1a/P1b）：两类主体（account/deployment）行为与测试齐；批准路径有 decision 身份、
  内容哈希不匹配/账号不匹配/部署主体都不产出 intent；发布结果逐字段不变。
- 回滚：P1a/P1b 都是旁路写入（artifact、账本 extra、intent 行）；删调用即回到裸取
  account_id 且执行器未变。

**P2 — 策略门禁（复用同一份规则）**
在 intent 构造后调用 `policy.py` 的发布策略评估；拒绝返回 typed 结果且**不写回执**，
与 creator_agent API 路径的拒绝语义一致。禁止复制一份策略逻辑到主链——只允许调用。
- claim：不变（没有换执行器、没有新增构造点之外的生产者）。
- 验收：允许/拒绝矩阵有测试；拒绝不产生 `UNKNOWN` 账本状态；与 API 路径共用规则（有测试断言同一函数被调用）。
- 回滚：去掉 gate 调用，回到 P1。

**P2 已落地（票 5bd，2026-11-01）**：发布入口在写 grant 检查之后、**任何持久副作用之前**
调用 `creator_agent.policy`：`build_policy_snapshot_for_capability(PUBLISH, principal.account_id,
policy_context=action_policy_context_from_values(state))` → `evaluate_action_policy` ——
同一个引擎、同一份规则表、同一份 checkpoint 投影（新增的两个共享函数让主链不必伪造
`ActionIntentRequest`，也不必复制投影逻辑）。拒绝时返回 typed `publish_result`
（`error_type="publish_policy_denied"` + verdict 的 `policy_id`/`retry_after_seconds` +
结构化 `recovery`），并写一条 `publish_blocked` 事件（`reason="publish_policy_denied"`）；
**不写 PREPARED 记录、不 claim 账本、不产 intent、不写回执、不调 Gateway**。
- 已知边界：部署本体（无 account）发布**不走**该策略——规则引擎按契约为 account-scoped，
  没有 account 就没有可评估的账号级判定；该路径仍由人工 review 审批把关，且不构造
  account-scoped intent（P1b-2 同一条边界）。
- 测试：stamped eligibility 拒绝 / 风险冷静期拒绝（typed + retry hint）/ 拒绝时零副作用 /
  部署主体边界 / capability 快照与 request 快照等价 / 非副作用 capability 不咨询 gate。
- claim：不变（直调仍 3、构造点仍 2）。

**P3 — 换执行器**
发布执行改走 Tool Gateway `xhs.publish` + `granted_scopes`（复用
`backend/creator_agent/execution.py` 的 dispatcher），私有 attempt 成为该 capability 的实现、入口统一调用；
主链的 `EffectLedger` 六态语义、幂等键与 human review gate 的先后关系必须逐条对齐（先写测试再切换）。
- claim：直调 3 → 0（票 5bh 后该 claim 行已删除）；生产者数不变。
- 验收：三条路径（主链/retry/free）都经 Gateway；scope 违规被拒且有测试；幂等键跨重试稳定；
  重复提交不产生第二次平台副作用。
- 回滚：dispatcher 注入回退到直接调用 attempt（本阶段保留该注入点）。

**P3a 已落地（票 5be，2026-11-01）：共享执行请求。** 主链不再自建 `xhs.publish`
载荷字段表：发布入口构造共享 `PublishRequest`（account / thread / idempotency_key /
artifact_ref / content_hash / content + 主链侧 `private` / `scheduled_time` /
`cdp_endpoint`）并调用 `creator_agent.execution.build_publish_payload` —— 与控制面执行器
**同一份**载荷定义。主链侧三个事实留在 request 上，控制面保持默认，因此控制面载荷键集合
逐字段不变（有测试钉住）；dispatcher 也改为优先使用 request 上**已解析**的 endpoint，
避免同一账号被解析两次或解析漂移。
- 本阶段**不改**三条直调：claim 仍 `3`。剩余 P3b：把主链/retry/free 三条路径接到
  控制面执行器（单执行入口；`EffectLedger` 六态语义、幂等键与 human review gate 的先后
  逐条对齐），再按 P3 验收把 claim 3→0。
- 回滚：恢复内联载荷构造；共享 request 的字段可保留（控制面不用默认值）。

**P3b-1 已落地（票 5bf，2026-11-01）：控制面执行器支持 mainline-origin intent。**
主链接下来的执行入口是同一个 `CreatorAdvisor.execute_action`，所以先让它能执行
`origin=mainline` 的已确认 intent：
- `ActionExecution` 新增 `origin`（默认 creator）；creator origin 必须携带
  `creator_id`/`audience_id`/`model_revision`，mainline origin 必须**为空/None**
  （不借创作者身份；`model_revision=None` 而非 0 —— 0 会和真实 revision 撞车）；
- `execute_action`：mainline intent **不加载** `DecisionRecord`（审批身份就是
  `decision_id`，票 5bc），只允许 PUBLISH（其他 capability 按未接线拒绝，不产生回执）；
- 回执由单一 `_record_execution` 写入，两种 origin 共用同一条持久化路径；
- 仓库 `create_action_execution` 对 mainline-origin 跳过 DecisionRecord provenance 查询，
  其余（intent 必须 CONFIRMED、来源字段一致、同 action 幂等返回同一回执）不变。
- 已验证：主链 intent 执行一次并产出 mainline 回执（creator 半区为空）；二次执行返回
  同一回执且只 dispatch 一次；失败发布 → FAILED 回执；非 CONFIRMED / 非 publish 的
  mainline intent 被拒且无回执。creator_agent 既有 204 用例全绿。
**P3b-2 已落地（票 5bg）：单一执行入口 + 决定身份。** 三条路径改为调用
`creator_agent.mainline_publish.execute_mainline_publish`；实现体私有化为
`agents/publisher.py:_run_publish_attempt`。入口负责决定身份：review 审批原样传递；free
发布由操作员显式产生 `free_publish_operator` 身份（账号 + 内容哈希 + approved_by/at；不伪装
review，无账号则不产生）；legacy retry 无身份时不产 intent（行为不变）。claim
`mainline_run_publish_direct_call_sites` 3 → 0。

**P4 已落地（票 5bh）：收口。** 选择验收分支 **A（实现体在入口背后）**：`_run_publish_attempt`
保持私有、无公开别名，唯一调用点是 `execute_mainline_publish`（AST 不变量测试钉住
"backend 中除入口模块外零调用"）；claim 行与残留声明删除。
- 迁移四阶段 P1/P2/P3/P4 至此收口；`run_publish` 符号已从 backend 删除，不存在兼容别名。

**P4 分支 B（未采用，可选后续）：入口直接落到控制面 `execute_action` 回执路径。**
当时不做的理由（控制面 receipt 路径不承载 `EffectLedger` 六态）已由票 5bi 解除——控制面
publish 现在也在 dispatch 前 claim、按 outcome 结算。若未来要做，最小迁移方案：
1. 执行前先落 CONFIRMED `ActionIntent`（P1b-2 的 producer 已有，需从"账本 claim 之后"
   提前到"执行之前"）；
2. 入口用 `CreatorAdvisor.execute_action` 替换 `_run_publish_attempt` 的执行段，
   PREPARED/force/ContentHistory 与 `publish_result` 映射保留在外层；
3. 对齐两条幂等键：主链 `publish_id`（内容+账号+时间窗）与 intent
   `idempotency_key` 必须同源，否则两条护栏各自记账、互相看不见；
4. 先写测试再切换：crash-window 只 dispatch 一次、force 语义、`UNKNOWN ≠ FAILED`、
   receipt 与工作流事件不冲突；
5. 回滚：入口内保留 dispatch 开关，回退到 attempt 即可。
- 未做原因：这会改变主链执行语义，并牵动 `test_run_publish` 约 500 行既有假设，
  需要产品/架构拍板后单独立项。

### 不变量（每阶段都必须保持）

1. **永不发明账号**：`account_id` 必须显式解析，空则拒。
2. **不双执行**：迁移期间 intent 与发布 attempt 只能有一个执行入口；两阶段切换点由测试钉住，
   禁止「先两边都写、后面再删」。
3. **回执/账本不撒谎**：拒绝不写回执；`UNKNOWN ≠ FAILED` 语义沿用控制面裁决。
4. **人类审批边界不变**：主链的 review gate 仍是审批点，控制面 confirmation 不得绕过它。
5. **claim 表与散文同步**：每阶段结束更新 claim 数并重算；否则判据红。

### 不做 / 触发条件

- 不在 P1/P2 阶段改发布 attempt 内部实现（先让意图与策略就位）。
- 不在没有跨进程幂等证据前进入 P3（否则重试可能变成第二次真实发布）。
- 迁移的每一步都是**独立票**；本方案每阶段单独落地、单独验收。

