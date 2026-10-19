# Tool Runtime（P1c）

Agent 不持有工具，只声明 **capability**。

```python
result = await self.tools.invoke("xhs.trending", {"category": niche})
```

这一层存在的理由只有一个：在它之前，"调用工具"是 9 处各自的写法 —— 每一处自己
`try/except`、自己 `asyncio.wait_for`、自己把异常翻译成降级值。超时、重试、权限、
可观测性因此都是**约定**而非**构造**：漏掉一处不会有任何东西报错。

## 快速使用

```bash
# 门禁：agent 层是否还在运行时之内（静态、离线、不 import 任何 agent 模块）
python scripts/gates/tool_runtime_gate.py

# 连同完整报告
python scripts/gates/tool_runtime_gate.py --json report.json
```

CI 里是独立的 `Tool Runtime Gate` job。门禁长什么样见下文「门禁」一节。

## 三条架构决定（不可回退）

### 1. 晚绑定

Registry 存的是 `"pkg.module:attr"` 字符串（`ToolRef` / `tool_ref` / `bind`），
调用时才 `resolve()`。**不是**在注册时把函数对象抓下来。

原因很实际：全仓测试用 `patch("backend.tools.xhs.trending.xhs_trending", fake)` 打桩。
如果 registry 在 import 期捕获了真函数，打桩就**静默失效** —— 测试仍然通过，只是
测的不再是它以为的东西；那类失效比失败更难查。

### 2. 共享单 Gateway

`max_concurrency` 是 **Gate 按键持有的名额**（`backend/tools/runtime/account_gate.py`），
不是每次调用现造的。每次调用现造一个信号量等于没有上限（每个等待者都有自己的名额）。

键取 payload 的 `account_id`（有则 `capability|account`，无则退回 `capability`），
所以上限是**每账号**的而不是全账号共用一份。名额双层：进程内 `asyncio.Semaphore`
快路径 + PG advisory lock 计数名额（每个名额一个 `pg_try_advisory_lock`），多 worker
共享同一个天花板；PG 不可用时降级为进程内（每 worker 各自计数）。等待有界——
名额等不到就报 `ToolResult(ok=False, error_kind=timeout, attempts=0)`：调用从未开始，
没有副作用可担心。

共享安全的前提正是第 1 条：晚绑定让 `build_registry()` 可以在 patch 生效之后再跑。

### 3. trace 目的地按 task 隔离

同一个 Gateway 被所有并发 workflow 共用，但每个 workflow 的 trace 要进自己的
sink。所以目的地存在 `ContextVar` 里（`bridge.tracing_to`），而不是 Gateway 的
实例字段上 —— 与 P0-W1 修 llm-perf 条目跨任务污染时用的是同一个模式。

## 双失败模式

调用失败有两种，**必须能分开**，因为它们该引发的反应不同：

| 类别 | 例子 | 处理 |
|---|---|---|
| 契约违规 | 未知 capability、`auth_scope` 不足 | **抛异常**（`UnknownCapabilityError` / `PermissionDeniedError`） |
| 运行时失败 | 超时、工具抛异常 | **返回** `ToolResult(ok=False, error_kind=TIMEOUT \| EXCEPTION)` |
| 领域结论 | 模拟给不出结果、报告不可用 | **返回** `ToolResult(ok=False, error_kind=DOMAIN)`，附 `domain` |

第三类值得单独说：`DomainOutcome(reason, **payload)` 表示"工具跑完了，结论是
不行"。Gateway 接住后**立刻返回，不进重试循环** —— 结论不是抖动，重问一遍只会
再买一次模拟。不变量：`domain` 非空 ⟺ `error_kind is DOMAIN`。trace 只带
`domain_reason`，不带 body（同 P1b 召回遥测的口径）。

为什么"超时"与"工具说了不行"不能靠读 error 字符串区分：调用点要对前者重试/降级、
对后者直接换路线，而字符串匹配在第一次文案变动时就悄悄失效了。

**同一条规则的另一半：失败也不能变成数据。** `except Exception: return []`（或
`return {"heat_score": 50}`）交回的是作者写下的字面量，不是对那个问题的回答 ——
handler 是因为调用失败才进的。这类兜底被 AST 扫成两张可数的表
（`scan_silent_fallbacks`，钉在 `tests/unit/tools/runtime/test_silent_fallbacks.py`）：
`@tool` 那一张今天只剩 `ripple_cancel_simulation`，它的字面量**自己写着**
`status: "error"`；服务层那一张**已清零**（2026-10-19，原 5 处：`get_trending` /
`search_posts` / 三个博主方法）。空表不是"没查"，是查完之后的结论，仍然逐次复算。
空列表因此只有一种含义：读到了，确实没有。

### 权限检查是 opt-in：`scopes` 字段

`granted_scopes=None` 读作 **unchecked**，不是 denied（`gateway.py` 的
`_check_scopes`）。所以一个能力可以声明 `auth_scope`，却从来没有人真正按它检查过 ——
声明看起来像保护，实际不产生任何拒绝。为了让这件事从"要靠读代码猜"变成"查得到"，
trace 事件带一个 `scopes` 字段：

| 值 | 含义 |
|---|---|
| `none` | 该能力没声明 scope，没什么可检查 |
| `unchecked` | 声明了，但调用方没传 `granted_scopes` ⇒ **没检查** |
| `checked` | 传了并通过；不足的情况在到达事件之前就已抛 `PermissionDeniedError` |

今天（2026-10-20 复算）的覆盖面：**14 个 capability 里 7 个声明了 scope，全仓有 2 个
调用点真的传 `granted_scopes`**（`backend/creator_agent/execution.py` 与
`backend/agents/publisher.py`），两个都落在 `xhs.publish` 上 —— 控制面确认后发布、
主链工作流发布，两条路径同一条规则。剩余 **6 个声明了 scope 的能力没有任何已检查的
调用点**（其中 `xhs.comment_reply` / `xhs.dm_send` 是票 5f 注册的，还没有任何调用点）。
这些数字不是估算，是 `tests/unit/tools/runtime/test_scope_coverage.py` 从代码树
逐项复算并钉住的；任何新增/收紧都会让那条测试变红，逼着把这节和
`docs/tool-gateway-engagement-migration.md` §9.6 一起改。

**"声明了但没检查的调用点"有两个半边，别混算**：11 个调用点没传 `granted_scopes`，但只有
**4 个**落在"能力声明了 scope"上（这才叫债务），另外 **7 个**落在"能力什么都没声明"上
（`content.*` ×2、`search.*` ×2、`ripple.*` ×3 —— 那里没有承诺可违背）。两个半边都在测试里
钉住，且划分是**从声明推导**出来的，不是各写一遍。

为什么当初没有立刻全线接线：在发布这条路径上，"有可用凭证"与"这台机器能发出去"并不是
同一件事（发布走 CDP，`XHSPublisher(cookie="")` 根本不用 cookie），硬接会拒掉一类
本来能工作的部署。**这条已于 2026-10-19 解掉并接上线**，方向是让授权追上机制：
`XhsCredential` 多了一个 `profile_bound` 事实，`scopes` 改成按机制授予 ——
**读要 cookie，写要 「cookie ∨ 已绑定 profile」**。绑定只读声明、不探测：具名账号读它的
`cdp_port`，空 account_id 读部署声明的 `XHS_CDP_ENDPOINT`（可达性不是授权：让授权随
Chrome 启停翻转，Gateway 会把"浏览器没开"报成"没被授权"）。接线代价是**一处收紧**：
具名账号若没有自己的 `cdp_port`、只靠全局浏览器，以前会经那台浏览器发布，现在被拒
（`missing_publish_credential`，附指路），因为那正是"一个账号的选择、另一个账号的身份"。
见 §9.6。

### 剩下的 4 个为什么还没接：它们不是同一类问题

把"没接"当成一种债务会得出错误的下一步。逐个查过（2026-10-19），它们分三类：

| 类别 | 能力 | 现状 |
|---|---|---|
| 前置条件在**工具内** | `xhs.trending` / `xhs.keyword_monitor` / `xhs.competitor_analyzer` | `services.xhs_client.require_readable` 在读取前拒绝，凭据由 `client_for_account` 解析。Gateway 再判一次不会多出任何信息，只会把"可降级的结果"变成**抛出的契约违规**，而调用点是按 `ToolResult(ok=False)` 写的降级分支。 |
| 声明结构上无法满足（已修） | `analysis.topic_scorer` | 以前用空 cookie 的 `XHSClient()` 读，并 `except` 成 `heat_score=50` —— 一个没人测过的分数被当数据写进 prompt。现已接上 `client_for_account` + `require_readable`，失败就抛出，调用方跳过该话题。 |
| **与身份无关**（已删声明） | `ripple.get_report` / `ripple.predict_spread` / `ripple.validate_pmf` | 本来就不是"没接"，是**接不了**：不消费任何凭据（`backend/tools/ripple/client.py` 用 `Settings().ripple.api_token`，部署级密钥，没有账号维度），而 `granted_scopes()` 只能吐出 `xhs:*`。所以 `ripple:read` 已于 2026-10-19 从目录里**删除**，理由见下。 |

**为什么删声明而不是"改 vocabulary 给它发一个服务级 grant"**：那样做的效果是"只要部署配好了
token，所有调用方都拿到 `ripple:read`"。那不是一个权限，是一个**伪装成权限的配置检查** ——
它会把"ripple 没配 token"报成"你没被授权"，而这正是本仓已经拒绝过一次的范畴错误（把
"浏览器没开"报成"没被授权"）。配置缺失现在仍然按它自己的语言说：`RippleService` 健康检查
经 `backend/tools/ripple/integration.py` 抛 `DomainOutcome("unavailable")`。

删掉的更实际的理由是**它是个陷阱**：如果谁做一次"把所有声明的 scope 都接上"的机械扫描，
这三个能力会被永久拒掉，而 trace 会把锅甩给调用方的身份。`test_no_declared_scope_is_unsatisfiable`
现在把这条钉住 —— 任何声明的 scope 都必须是 `granted_scopes()` 真能产出的。

所以"读侧接 scope 是检查还是形式主义"的答案是：对第一类是重复，对第二类已由前置条件
覆盖，对第三类是**声明本身写错了域**。要动这三类，动作分别是"不接"、"已修"、"删声明"，
而不是统一加一行 `granted_scopes=`。

## 传参形状：PassStyle

三种，**在签名上不可区分，猜错也不报错**：

| 值 | 调用方式 | 用在哪 |
|---|---|---|
| `KWARGS`（默认） | `tool(**payload)` | 普通函数、LangChain 工具 |
| `MAPPING` | `tool(payload)` | 只吃一个 mapping 的函数 |
| `INVOKE` | `await tool.ainvoke(payload)` | 真 `BaseTool` |

所以它是**声明**，不是推断。`_register` 从同一个 `pass_style` 构造声明与绑定，
`_validate_style` 拒绝签名兑现不了的声明。全目录只有 `content.algorithmic_de_ai`
是 `MAPPING`。

**路由只按声明，不看对象。** 曾经按鸭子类型路由，结果普通函数替身被 `.ainvoke`
应答 —— 每次调用都"成功"，只是**从未收到 payload**，看起来像一次优雅降级。

## 目录：14 个 capability

| capability | side_effect | pass_style | retry | auth_scope | timeout_s |
|---|---|---|---|---|---|
| `analysis.topic_scorer` | read_only | invoke | 2×3s | `xhs:read` | 120 |
| `content.algorithmic_de_ai` | pure | **mapping** | — | — | 5 |
| `content.polish_copy` | pure | kwargs | 2×2s | — | 30 |
| `ripple.get_report` | read_only | kwargs | — | — | 120 |
| `ripple.predict_spread` | read_only | kwargs | — | — | **3600** |
| `ripple.validate_pmf` | read_only | kwargs | — | — | **3600** |
| `search.fetch` | read_only | invoke | — | — | 60 |
| `search.web` | read_only | invoke | — | — | 60 |
| `xhs.comment_reply` | **side_effecting** | invoke | — | `xhs:write` | **300** |
| `xhs.competitor_analyzer` | read_only | invoke | — | `xhs:read` | 120 |
| `xhs.dm_send` | **side_effecting** | invoke | — | `xhs:write` | **300** |
| `xhs.keyword_monitor` | read_only | invoke | — | `xhs:read` | 120 |
| `xhs.publish` | **side_effecting** | invoke | — | `xhs:write` | **900** |
| `xhs.trending` | read_only | invoke | — | `xhs:read` | 120 |

四处容易误读的数字：

- **`timeout_s=3600` 不是"允许等一小时"。** 两个 ripple 慢查询用 payload 里的
  `max_wait`（默认 1800s）自己等待，并以领域结果自报超时（带 `job_id`）。Gateway
  的兜底**必须严格高于**那个预算，否则 `wait_for` 会先取消调用，而 `job_id` 只有
  工具自己拿得到 —— 于是"重试"从头到尾看不到真正的原因。3600 只是防挂死连接。
- **`xhs.publish` 的 900 同理，不是"允许等十五分钟"。** `services.xhs_publisher`
  持 CDP 会话锁最长 `XHS_CDP_PUBLISH_LOCK_TIMEOUT_S`（默认 600s），之后还要传图
  （60s 选择器）才可能观察到成功。用 SLOW 的默认 120s 会在一次**仍在合法进行中**
  的发布上取消调用，并把一次"可能已经提交"的发布报成超时 —— 这正是 P0-B 里
  `UNKNOWN` 想避免的形态。
- **`xhs.comment_reply` / `xhs.dm_send` 的 300 也是防抢占的兜底。** 互动链自身预算
  上界 ≈165s（CDP 锁 120s + 元素等待 + 逐动作冷却，推导见
  `docs/tool-gateway-engagement-migration.md` §6），300 留 1.8 倍余量。这两个能力
  还声明 `max_concurrency=1`：闸门按账号分键（`account_gate`），同一账号同一时刻
  一次在途互动。
- **重试次数少是故意的。** `ripple.*` 与 `content.polish_copy` 从不抛异常，唯一
  可重试的事件是 Gateway 自己的超时；重试超时 = 伪装成重试的加长等待（120s×2
  拖住节点）。要等更久是 `timeout_s` 的事。

这张表由 `tests/unit/tools/runtime/test_docs_capability_table.py` 从
`build_registry()` **逐格复算**（capability 集合、side_effect、pass_style、retry、
auth_scope、有效超时）。表曾经写着"10 个 capability"（实际 12：`search.web` /
`search.fetch` 加进目录时没补行），并把 `xhs.publish` 的超时记成 120 —— 两个数字
都不会自己变红，所以现在会。

## L1 tool schema 层

`backend/tools/runtime/schema.py::render_tool_schema` 把声明的 capability 渲染成
prompt 的 L1 层文本，经 `RunContext.tool_schema` 由 compiler 播种 —— **"L1 放不
放进 prompt"只有一个归属地**。

**默认关闭**（`BaseAgent.include_tool_schema = False`），且这不是偷懒：模型到
P2c 才有 tool-calling 通道，此刻把能力清单写进 prompt 等于描述一种它无法行使的
能力（还会诱导它在 JSON 里编 tool-call 语法），并且每次请求白付 token。通道已经
建好并测过，逐 agent 打开交给 P2c。

L1 只描述**调用形状**，不描述**运行时权限**：`side_effect` / `auth_scope` /
`latency` / `cost` 刻意不进 prompt，唯一例外是 `pass_style`（它决定调用形状）。
把"运行时会拿这次调用做什么"写进 prompt，只会诱导模型去推理它并不持有的权限。

## 门禁

`scripts/gates/tool_runtime_gate.py` —— 静态、离线、不 import 任何 agent 模块
（读 agent 模块会执行它的 import 与模块级接线，门禁不能有副作用；与
`backend.context.baseline.scan_declared_prompts` 同一条规矩）。

它检查四件事：

1. **agent 不许持有工具对象。** 可以 import 运行时自身
   （`backend.tools.runtime.**` —— 读懂 `ToolResult` 需要的那些类型），但不许
   import 工具实现（`backend.tools.xhs.trending` 之类）：拿到的是 Gateway 永远
   看不见的对象，超时/重试/权限/trace 会在没有任何测试察觉的情况下失效。
   更窄的一条：**bridge 只能由 `base.py` import**（它持有 `self.tools`）。
2. **声明 ↔ 调用一致**，且**双向**：调用了没声明 = 运行时描述不了它；声明了没
   调用 = L1 会描述一个用不到的能力。
3. **读不懂的调用算失败。** 非字面量的 capability、门禁不认识的写法、解析不了的
   源文件 —— 全部报错，绝不跳过。在没读懂的代码上报告"0 处不一致"是假通过，
   而假通过比吵闹的失败更糟。
4. **目录覆盖度。** agent 提到但目录里没有 → 失败；目录里有但没人用 → **只报告**
   （当前**为空**：`xhs.publish` 的调用者由 P2a-S4a 接上，门禁里那条 orphan 断言也随之
   改成 `orphans == ()`）。与 prompt 覆盖度门禁同口径：
   对计划中的工作失败的门禁，最后会被人关掉。

**为什么只覆盖 `backend/agents/**`：** `backend/api/routes/_wf_actions.py` 仍有一处
刻意的直调（ripple-retry 路由绕过 health-check/fallback，见「已知残留」），它属
API 层。把门禁范围画到"agent 是否绕开运行时"这一条上，才能让白名单是一个可以
讲清楚的东西。

## 加一个新工具

1. 在 `backend/tools/runtime/catalog.py` 的 `build_registry()` 里登记 `ToolSpec`
   + 绑定（`tool_ref(...)` / `bind(...)`）。声明要诚实：`side_effect` 决定能不能
   重试（`side_effecting` 且 `max_attempts > 1` 时必须带幂等键，否则构造即报错）。
2. 在 agent 类上把 capability 加进 `tool_capabilities`。
3. 用 `await self.tools.invoke("<capability>", {...})` 调，不要 import 实现。
4. `python scripts/gates/tool_runtime_gate.py` 应当变绿；门禁会把漏掉的第 2 步
   直接指出来。

## 已知残留

- **`backend/api/routes/_wf_actions.py:129`** 的 ripple-retry 路由仍直调
  `RippleService.submit_and_wait` —— 刻意绕开 health-check 与 fallback。属 API
  层，门禁不覆盖它；迁移属于后续任务。
  - 同文件 `:134` 还有**第二处**（PMF 那一支）；本节原先只点了第一处。两处都在
    `_run_retry()` 里，都走 `ripple.submit_and_wait`，都不经 Gateway。
- **L1 参数类型是原样反射的**：LangChain 工具给 JSON-schema 的 `string`，普通函数
  给注解名（`dict[str, Any]`）。没有归一化 —— P2c 真要把 schema 交给模型调工具时
  需要一个统一口径。
- **`account_credentials` 没有写入者**：读它在 `services/xhs_credentials`（P2a-S5a），
  但扫码登录把登录态写进 CDP profile（per-account Chrome user-data-dir），并没有写
  这张表。所以**今天唯一真的能提供凭据的来源是部署级的 `XHS_COOKIE`**
  （`.env.example` 里声明、P2a-S5a 之前无人读）；per-account 那一行读路径是通的、
  也是优先的，但在登录流程开始写它之前一直是空的。写它属于后续任务。

**可重算的部分发布成值（下面的表），量不出来的那一条不编谓词。**

「L1 参数类型是原样反射的、没有归一化」**不是树的形状，是一个设计判断** —— 它可以被读出来、
被争论，但没法被一个扫描器证实或证伪。按 `docs/planning.md` 的先例（量不出来的主张宁标
「未重量」也不写一个恒真的检查），它**留在上面的散文里、不进表**。给一条设计判断编一个
恒真的谓词，等于给自己发一张写着「已复核」的收据。

<!-- claim-table:begin -->

| 主张 | 发布的值 | 复核方式 |
| --- | --- | --- |
| `api_route_modules_importing_ripple_service` | `3` | AST：`backend/api/routes/*.py` 里 import `RippleService` 的文件数 |
| `ripple_service_direct_call_sites_in_api_routes` | `2` | 正则：这几个文件里 `ripple.submit_and_wait(` 的出现次数（`backend/api/routes/_wf_actions.py:129` 与 `:147`） |
| `tool_gate_allowed_prefix` | `backend.tools.runtime.` | 读 `backend/tools/runtime/audit.py` 的 `_ALLOWED_PREFIX` —— 门禁只覆盖这一个包，本节第一条的前提 |
| `account_credentials_inserts` | `0` | 正则：`backend/**/*.py` 里 `INSERT INTO account_credentials` 的次数（与 `publish-action-protocol.md` 同一条事实，**刻意的重复**：两份文档各自要被单独读懂） |

<!-- claim-table:end -->

L1 归一化那一条**未重量**；表里没有它的行，不是漏了，是不给它编谓词（理由见上）。
