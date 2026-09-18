# P1c 实施 prd — Tool Runtime

> 状态：**草案（2026-09-15）**。用户以"继续"驱动，Q1–Q6 按推荐执行并冻结为本任务
> info.md 的 D1'–D6'；开工前如需推翻某项，改对应条目即可。
> 前置：P1a（Kernel 骨架 + State 三层）与 P1b（Context Compiler）均已合入 main；
> 本任务分支自 main 开（独立 PR）。L1 tool schema 层（P1b 留的空层）由本任务补生产者。

设计权威来源：父任务 prd `09-11-runtime-upgrade/prd.md` P1c 段 +
`research/architecture-review-2026-09-11.md`（Tool 未组件化）+ P1b info.md
（L1_TOOL_SCHEMA 保持空直到 P1c 给生产者）。

## 目标（父 prd 已定）

Agent 不再 `from backend.tools.xhs.xxx` 直调；建立 **ToolSpec**（capability / input-output
schema / latency-cost class / side_effect / retry_policy / auth_scope）+ **Registry** +
**Gateway**；**timeout / retry / permission / rate limit / error / tracing 收口到 Gateway**；
Agent 只声明 capability 需求。

## 现状盘点（2026-09-15 实测）

工具面本身不大——4 个子包、15 个模块；**9 处 agent 直调**，按风险梯度天然分四类：

| # | 调用点 | 工具 | 类别 | 副作用 |
|---|---|---|---|---|
| 1 | `content_strategist.py:593` | `analysis.topic_scorer.topic_scorer` | 纯计算 | 无 |
| 2 | `copywriter.py:504` | `content.de_ai_taste.algorithmic_de_ai` | 纯计算 | 无 |
| 3 | `copywriter.py:456` | `content.de_ai_taste.polish_copy` | 内部 LLM | 无（但计费/慢） |
| 4 | `analyst.py:308` | `ripple.integration.get_report` | 外部服务 | 只读 |
| 5 | `content_strategist.py:635` | `ripple.integration.predict_spread` | 外部服务（重） | 只读，长耗时 |
| 6 | `content_strategist.py:686` | `ripple.integration.validate_pmf` | 外部服务 | 只读 |
| 7 | `trend_scout.py:77` | `xhs.trending.xhs_trending` | 外部平台 | 只读但有封禁风险 |
| 8 | `trend_scout.py:91` | `xhs.trending.competitor_analyzer` | 外部平台 | 只读但有封禁风险 |
| 9 | `trend_scout.py:118` | `xhs.trending.keyword_monitor` | 外部平台 | 只读但有封禁风险 |

模块分布：`xhs/`（analytics / engagement / publisher / trending）、`content/`
（de_ai_taste / layout / style）、`ripple/`（client / integration）、`analysis/`（topic_scorer）。
其中 `xhs/publisher.py` 是**真正的高副作用**面（发帖），目前不在 agent 直调清单里
（走 API 层），P2a 会把它纳入 Action Executor + Gateway——本任务只保证它的工具能被注册，
不改变其调用路径。

## 决策点（按推荐冻结 → info.md D1'–D6'）

### Q1 ToolSpec 的 schema 表达形态
- **A（推荐）**：Pydantic 模型。`ToolSpec` 为 frozen Pydantic，input/output 直接引用
  已有 Pydantic 模型（缺失的补最小模型），必要时导出 JSON schema 供 L1 渲染。
  与项目既有风格一致，可测性好，零新依赖。
- B：dataclass + 手写 JSON schema dict——更轻，但与项目 Pydantic 主流不一致，
  L1 渲染需自己维护 schema 正确性。

### Q2 Gateway 的调用形态
- **A（推荐）**：单一收敛入口 `await Gateway.invoke(capability, payload, *, ctx) -> ToolResult`；
  Registry 负责 capability → 实现绑定。timeout / retry / tracing / error 归一化都在这一条路径上。
- B：给每个工具加 `@tool(...)` 装饰器——改动面看起来小，但 rate limit / permission /
  tracing 会散落各处，违背"收口"目标。

### Q3 迁移激进程度
- **A（推荐）**：按**风险梯度分批**（纯计算 → 内部 LLM → 外部只读服务 → 外部平台），
  每批独立可合；迁移期新旧路径并存，但立刻加 **AST 门禁冻结新增直调**（只许减不许增）。
- B：一次性全迁——9 处虽不多，但外部平台类工具带封禁风险，回滚面大。

### Q4 权限 / auth_scope 的落地深度
- **A（推荐）**：本任务只做**声明 + 校验元数据**（capability 是否被该 agent 声明、
  auth_scope 是否齐备），真正的账号级鉴权执行留给 P2a（Action Executor + Policy Engine）——
  否则要依赖尚不存在的身份上下文。
- B：本轮接账号级鉴权——依赖超前，且与 P2a 的 Policy Engine 职责重叠。

### Q5 L1 tool schema 的生产方式
- **A（推荐）**：从 Registry **按需生成**——只把该 agent 声明的 capability schema 渲染进 L1。
  稳定前缀第二位，内容随 agent 固定，可安全上 prompt cache；新增 schema 需刷新
  P1b 快照（同 PR 内 `--write-snapshot`，diff 可见）。
- B：全量 schema 进 L1——prompt 立刻膨胀，且与"只给该 agent 需要的"意图相悖。

### Q6 retry policy 的归属
- **A（推荐）**：Gateway 层声明式 `retry_policy`，按 `side_effect` 分级——`pure` 可安全重试，
  `side_effecting` 必须带幂等键；**不与 graph 级 retry 叠加**（P0 已收口双 retry 语义）。
- B：复用 graph 的 retry——自动重试会把"工具级瞬时失败"和"节点级失败"混在一起，
  正是 P0 修掉的坑。

## 切片计划（每片独立 PR）

| 切片 | 内容 | 风险 |
|---|---|---|
| **S1** | `ToolSpec` 模型 + `Registry`（声明式注册、capability 查表、去重/冲突 fail-fast）+ 为现有工具登记元数据。**纯新增，零行为变更** | 低 |
| **S2** | `Gateway` 骨架：`invoke` 单一路径，timeout / retry（按 side_effect 分级）/ error 归一化 / tracing 事件；先接 1 个纯计算工具试点（topic_scorer） | 低-中 |
| **S3** | 分批迁移 9 个直调点：S3a 纯计算(2) → S3b 内部 LLM(1) → S3c ripple 只读(3) → S3d xhs 平台(3) | 中（S3d 最高） |
| **S4** | L1 tool schema 生产者：Registry → L1 层渲染，接入 Context Compiler（P1b 遗留空层）；刷新基线快照 | 中 |
| **S5** | 门禁 + 文档：AST 门禁（`backend/agents/**` 禁止直调 `backend.tools`，白名单=Registry/Gateway）、Registry 覆盖度（每个已注册工具都有 spec）、`docs/tool-runtime.md` | 低 |

执行记录（2026-09-15）：**S3c 实际拆为两片**。

- **S3c-1 ✅**：`ripple.get_report`（analyst）。等待预算从调用点的 120s `asyncio.wait_for` 搬到能力声明（`timeout_s=120.0`），直调 **6 → 5**。
- **S3c-2 ✅（PR #596）**：`ripple.predict_spread` / `ripple.validate_pmf`（content_strategist），直调 **5 → 3**。先给 `ToolResult` 补上**领域结果通道**：`ErrorKind.DOMAIN` + `DomainOutcome(reason, **payload)`，Gateway 接住后**立刻返回**（不进重试循环），payload 落在 `ToolResult.domain`；trace 只带 `domain_reason`。要点：
  - **为什么必须是新的异常类型**：`RippleTimeoutError` 是 `TimeoutError` 子类，原样穿过 Gateway 会被归类成"网关自己的等待超时"，而那条路上 **`job_id` 会被剥掉** —— 取消与恢复都从它开始。
  - **Gateway 的兜底必须高于工具自己的等待预算**：这两个工具用 payload 的 `max_wait`（默认 1800s，来自 `RIPPLE_WORKFLOW_TIMEOUT`）等待，并以领域结果报告超时；Gateway 的 `wait_for` 若先触发就会取消调用、永远看不到那个 id。故声明 `timeout_s=3600.0`（`_RIPPLE_SAFETY_NET_S`），只兜挂死的连接，不承担调度含义。
  - **顺手修正两处失真**：`integration` 不再自己吞异常（归一化只在 Gateway 一个归属地）；服务"降级"（`ripple_fallback=True` + 全零预测体）从"一次成功的预测"改为 `DomainOutcome("unavailable")` —— 原先真实服务返回的零点会被 agent 当成真实预测读走，而 conftest 的替身只返回 `{"ripple_fallback": True}`，两者行为不一致，正是这个不一致掩盖了 bug。
  - 调用点用一个 `_RippleCall` 一次读清结果，删掉"`"ripple_reason" not in result` 即表示成功"的缺失键语义。
- **S3d ✅（PR #597）**：`xhs.trending` / `xhs.keyword_monitor` / `xhs.competitor_analyzer`（trend_scout），直调 **3 → 0** —— agent 层对 `backend.tools` 的直调至此清零。要点：
  - **迁移不改降级语义**：失败仍退化为 `data_source="llm_generated"`、仍走同一段降级文案；改的是“谁还知道失败了”。此前工具吞一次异常返回 `[]`、agent 再吞一次，Gateway 只会看到“成功的一次空读取”，于是“平台读不到”与“这个领域确实没热点”是同一个值。
  - **发现并修掉一处真造假**：`XHSClient.monitor_keywords` 对每个关键词循环 `search_posts`，而 `search_posts` 在无 Cookie 时返回 `[]` —— 于是它**为每个关键词造出一行全零**（`post_count: 0, avg_likes: 0`），`trend_scout` 的 `if monitor_data:` 判真，把 `data_source` 报成 `"real"`，再把“0 篇帖子 / 平均点赞 0 / 趋势: declining”当真实平台数据喂给模型。三个读工具现在**在调用前**检查新增的 `XHSClient.can_read`（`_http is not None`），读不到就抛 —— 该前提调用前可知、调用后不可知，所以只能在这一侧判。
  - `backend/tools/xhs/trending.py` 三个工具不再自己 `except → return []`（同 S3c-2 规则：归一化只在 Gateway 一个归属地）。空列表从此只有一个含义：平台被问过，它没有内容。
  - 目录声明：三个 `xhs.*` 读能力 `retry=RetryPolicy()`。迁移前调用点从不重试（各自 catch 后降级），且这里的头号失败是缺凭据 —— 等待修不了它。`auth_scope=("xhs:read",)` 仍只是**声明**（执行归 P2a），用测试钉住。
  - **残留（不在本片范围）**：第一层 `XHSClient` 仍吞异常返回 `[]`（`get_trending`/`search_posts` 的既有契约，`tests/unit/services/test_xhs_client.py` 钉着），所以“限流导致的空”与“确实没内容”在第一层仍不可分；修它要连带 `visual_analysis.py` / `topic_scorer.py`，属凭据整备（P2a）。另：`_fetch_real_data` 把 `niche` 传给 `competitor_analyzer.account_id`（该参数语义是“竞品账号或搜索词”）是迁移前就有的形状，本片原样保留、不顺手改语义。

- **S4 ✅（PR #598）**：L1 tool schema 层终于有了生产者并接线到 Context Compiler；**但默认关闭**，14 个 agent 的 prompt 与基线快照**字节不变**（漂移门禁 0 漂移）。
  - **口径偏离已在动手前与用户确认**：票面 Q5/S4 原文是“接入 Context Compiler + 刷新基线快照”，本片改为“建通道 + 默认关闭”。理由：模型到 P2c 才有 tool-calling 通道，此刻把能力清单写进 prompt 等于描述一种它无法行使的能力（还会诱导它在 JSON 里编 tool-call 语法），并且每次请求白付 token。架构评审 §十八 立 L1 是因为它属于 stable prefix / prompt cache 的稳定区 —— 通道先建好，“打开”留给 P2c 逐 agent 决定。
  - **生产者** `backend/tools/runtime/schema.py::render_tool_schema(specs)`：纯函数、按 capability 排序（稳定前缀不能每次重排）、空输入返回 `""`（compiler 用“空”判断该层是否存在，不能只吐一个光杆标题）。另走 `registry.subset()` —— S1 当时预留的窄口子，docstring 原文就是给 L1 用的。交付点在 `bridge.tool_schema_section(capabilities)`。
  - **`pass_style` 分支渲染是 S1 的交办**：MAPPING 工具的 `data` 若照原样渲染，会和另外九个“按名解包”的工具长得一模一样 —— 而那正是“payload 有没有被丢掉”的分水岭，故该行渲染成“整体即 `data: ...`，不再嵌套”。
  - **运行期事实不进 prompt**：`side_effect` / `auth_scope` / `latency` / `cost` 刻意不渲染（有测试钉住）。L1 只说“有什么、怎么调”；“运行时会拿这次调用做什么”是 Gateway 的事，写进 prompt 只会诱导模型去推理它并不持有的权限。唯一进 prompt 的运行时事实是 `pass_style`，因为它决定调用形状。
  - **agent 侧**：`BaseAgent.tool_capabilities`（声明，供 S5 做声明↔代码一致性门禁）+ `include_tool_schema = False`（开关）+ `tool_schema_layer()`。四个真在调工具的 agent 各自声明（trend_scout 3 / content_strategist 3 / copywriter 2 / analyst 1 = 9 个；第 10 个 `xhs.publish` 尚无 agent 调用者，属 P2a）。文本随 `RunContext.tool_schema` 走，由 compiler 在 `compile()` 里播种到 L1 —— **“L1 放不放进 prompt”只有一个归属地**；`LAYER_ORDER` 保证它在 L0 之后、L2 之前，`_TRIM_ORDER` 只含 L5/L4，故预算裁剪永远不会吃掉它。隔离性也钉住了：`compile()` 不污染调用方传入的 sections。
  - **未知 capability 抛错而非静默省略**：`tool_schema_section` 让 `UnknownCapabilityError` 抛出。默认关闭意味着没有消费者会发现配置错误 —— 静默省略会把它藏到 P2c 打开开关的那一天。
  - **测试**：`test_schema.py`（13，含 MAPPING 分支与“运行期事实不泄露”）、`test_tool_schema_layer.py`（6，含“声明 ⊆ 目录”与“全仓开关为 False”两条钉子）、`test_compiler.py` +5（无声明则无 L1 / 位置在 L0 与 L2 之间 / 预算不吃 L1 / YAML 段与 RunContext 合并 / 不污染调用方的 sections）、`test_trend_scout.py` +1（真实 prompt：关→一个字不进，开→L1 真进去且在 L0 之后）。全量 **2747 passed / 3 skipped**；ruff/format/mypy(196)/基线零漂移全绿。
  - **残留**：L1 的参数类型是**原样反射**（LangChain 工具给 JSON-schema 的 `string`，普通函数给注解名 `dict[str, Any]`），未做归一化 —— P2c 真要把 schema 交给模型调工具时需要一个统一口径。`docs/tool-runtime.md` 仍归 S5。

- **S5 ✅（本分支）**：门禁 + 文档收官。三件东西 —— 静态审计模块、CI 门禁 job、`docs/tool-runtime.md`。
  - **门禁一句话**：`backend/agents/**` 里没有工具对象；声明与调用一致；读不懂的调用算失败；目录覆盖度双向可查。入口 = `backend/tools/runtime/audit.py`（纯 AST、不 import）+ `scripts/gates/tool_runtime_gate.py`（CLI，失败退 1）。
  - **审计在设计上就是静态的**：AST 而非 import —— 读 agent 模块会执行它的 import 与模块级接线，门禁不能有副作用（同 `scan_declared_prompts` 的规矩）。`known_capabilities` 由调用方传入而非 import 目录：测试能给它一棵临时树，且目录构建失败不会把门禁一起拖死。
  - **判定面被门禁自己修正过一次**：第一版写成“只允许 `base.py` import `backend.tools.runtime.bridge`”，一跑就报三处 —— `analyst.py` / `content_strategist.py` 的 `ErrorKind`/`ToolResult`（读懂 Gateway 结果必需）、`base.py` 的 `ToolGateway`（在 `TYPE_CHECKING` 里）。规则改成“不许持有**工具对象**”：允许 `backend.tools.runtime.**`（运行时自身的类型与设施），禁止其余一切（工具实现），bridge 仍只允许 `base.py`。这条边界现在写在 `_ALLOWED_PREFIX` 的注释里，连同它曾经画错的事实。
  - **“读不懂 = 失败”是本片最重要的一条**：非字面量 capability、门禁不认识的写法、**解析不了的源文件**，全部报错。这条是被自己的测试逼出来的 —— 测试夹具的三引号字符串保留了方法缩进，文件语法错误，而当时 `_parse_sources` 会静默跳过它 —— 于是门禁在**从未读过的树**上报告“干净”。现在 unparseable 会进 `unreadable`。
  - **测试先证明能抓违规**（23 例）：7 例直接导入（工具实现 / 裸包 / `import` 写法 / 嵌套目录 / runtime 类型不算违规 / bridge 只许 base / 公共入口与审计一致）、6 例声明一致（含去重、无工具模块不入列）、4 例不可读（非字面量 capability / 非字面量声明 / 无参 invoke / 语法错误；其中“调用不可读时声明会**同时**被报成 unused”是两条都成立的真话，测试如实断言）、2 例覆盖度（未知失败 / orphan 不失败）、5 例对真仓跑（干净、只有四个工具使用者、声明与调用一致、唯一 orphan 是 `xhs.publish`、默认目录就是 agents 包）。
  - **CI 新增独立 job `Tool Runtime Gate`**（`python scripts/gates/tool_runtime_gate.py`），CI 因此 7 项 → 8 项。
  - **门禁范围只画到 `backend/agents/**`**：`backend/api/routes/workflow.py:~2184` 的 ripple-retry 路由仍刻意直调，属 API 层。范围能讲清楚，白名单才能是一个可以讲清楚的东西。
  - **文档** `docs/tool-runtime.md`：三条不可回退决定、双失败模式、PassStyle、10 个 capability 的声明表（含两处容易误读的数字：`timeout_s=3600` 不是“允许等一小时”，两个 ripple 慢查询自己等 1800s 并自报领域超时；retry 少是故意的，重试超时 = 伪装成重试的加长等待）、L1 层与默认关闭的理由、门禁四问与范围、加新工具的 4 步、已知残留。
  - **顺带修掉一处类型陷阱**：`_agent_tool_usage` 的循环体里把解构结果写进了参数名 `parsed`。运行时侥幸无害（迭代器在循环开始时就已创建，重新绑定不影响它）—— 正因为侥幸无害才危险，mypy 抓住了它。
  - **门禁**：全量 **2770 passed / 3 skipped**（比 S4 多 23 例）；ruff check + format 全绿（485 files）；mypy backend **197** files 无错；基线漂移 **0**；新门禁 OK。

## 验收

- `backend/agents/**` 对 `backend.tools` 的直调**清零**（AST 门禁强制，白名单仅 Registry/Gateway 自身）
- 每次工具调用经 Gateway，产生 tracing 事件；timeout / retry 行为有测试覆盖
- `pure` 工具重试安全、`side_effecting` 工具强制幂等键（无键即拒）
- L1 层被真实填充且不破坏 P1b 稳定性四不变量；快照在同 PR 刷新
- 全量 `tests/unit` + `tests/integration` 通过；ruff / mypy 干净

## 红线（不做的事）

- 不引入 LLM Tool-calling 自主规划（那是 P2c 的事）
- 不改变 `xhs/publisher.py` 的实际发布路径（P2a 负责）
- 不做账号级鉴权执行（P2a Policy Engine）
- 不为"以后可能用到"提前抽象未注册工具
