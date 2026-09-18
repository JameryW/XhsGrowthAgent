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

`max_concurrency` 是 **Gateway 自己持有的 Semaphore**，不是每次调用现造的。
每次调用现造一个信号量等于没有上限（每个等待者都有自己的名额）。

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

## 目录：10 个 capability

| capability | side_effect | pass_style | retry | auth_scope | timeout_s |
|---|---|---|---|---|---|
| `analysis.topic_scorer` | read_only | invoke | 2×3s | `xhs:read` | 120 |
| `content.algorithmic_de_ai` | pure | **mapping** | — | — | 5 |
| `content.polish_copy` | pure | kwargs | 2×2s | — | 30 |
| `ripple.get_report` | read_only | kwargs | — | `ripple:read` | 120 |
| `ripple.predict_spread` | read_only | kwargs | — | `ripple:read` | **3600** |
| `ripple.validate_pmf` | read_only | kwargs | — | `ripple:read` | **3600** |
| `xhs.competitor_analyzer` | read_only | invoke | — | `xhs:read` | 120 |
| `xhs.keyword_monitor` | read_only | invoke | — | `xhs:read` | 120 |
| `xhs.publish` | **side_effecting** | invoke | — | `xhs:write` | 120 |
| `xhs.trending` | read_only | invoke | — | `xhs:read` | 120 |

两处容易误读的数字：

- **`timeout_s=3600` 不是"允许等一小时"。** 两个 ripple 慢查询用 payload 里的
  `max_wait`（默认 1800s）自己等待，并以领域结果自报超时（带 `job_id`）。Gateway
  的兜底**必须严格高于**那个预算，否则 `wait_for` 会先取消调用，而 `job_id` 只有
  工具自己拿得到 —— 于是"重试"从头到尾看不到真正的原因。3600 只是防挂死连接。
- **重试次数少是故意的。** `ripple.*` 与 `content.polish_copy` 从不抛异常，唯一
  可重试的事件是 Gateway 自己的超时；重试超时 = 伪装成重试的加长等待（120s×2
  拖住节点）。要等更久是 `timeout_s` 的事。

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

- **`backend/api/routes/_wf_actions.py:101`** 的 ripple-retry 路由仍直调
  `RippleService.submit_and_wait` —— 刻意绕开 health-check 与 fallback。属 API
  层，门禁不覆盖它；迁移属于后续任务。
  - 同文件 `:119` 还有**第二处**（PMF 那一支）；本节原先只点了第一处。两处都在
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
| `ripple_service_direct_call_sites_in_api_routes` | `2` | 正则：这几个文件里 `ripple.submit_and_wait(` 的出现次数（`_wf_actions.py:101` 与 `:119`） |
| `tool_gate_allowed_prefix` | `backend.tools.runtime.` | 读 `backend/tools/runtime/audit.py` 的 `_ALLOWED_PREFIX` —— 门禁只覆盖这一个包，本节第一条的前提 |
| `account_credentials_inserts` | `0` | 正则：`backend/**/*.py` 里 `INSERT INTO account_credentials` 的次数（与 `publish-action-protocol.md` 同一条事实，**刻意的重复**：两份文档各自要被单独读懂） |

<!-- claim-table:end -->

L1 归一化那一条**未重量**；表里没有它的行，不是漏了，是不给它编谓词（理由见上）。
