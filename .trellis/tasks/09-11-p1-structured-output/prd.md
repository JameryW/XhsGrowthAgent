# P1d 结构化输出 schema 化（`09-11-p1-structured-output`）

依赖 P1a（RunContext）。父任务：`09-11-runtime-upgrade`。

## Background

父任务票面原文：主要链路改 provider-native structured output + Pydantic schema + semantic
validator + validation-error retry；`_parse_json_response_impl` 降级为 legacy fallback；
ContentPlan 等 `dict[str, Any]` 全面类型化。

## 现状侦察（2026-09-15）

- `BaseAgent._parse_json_response` / `_parse_json_response_impl`（`base.py:233/254`）是集中
  入口，本质是**猜**：正则给未加引号的 `#hashtag` 补引号、括号纠偏、剥 markdown 围栏。
  **25 个调用点分布在 13 个 agent**；`backend/services/llm_enrichment.py:54` 另有一份独立副本。
- `with_structured_output` **全仓零使用** —— provider-native structured output 完全没上。
- 同一个概念有**三份定义**：`backend/api/generated/models.py:671` 的 Pydantic（OpenAPI
  生成的前端契约）、`backend/state/substates.py:46` 的 TypedDict、agent 里构造的
  `dict[str, Any]`。
- **生产主线压在单个兼容端点上**：`resolve_model_id` 里 13/15 个 TaskType → `astron-code-latest`
  （XUNFEI）；`VIRAL_MATCHING` / `POLISH` / `MOCK_GEN` → `deepseek-v4-flash`。6 个 provider
  里有 4 个（DeepSeek / DashScope / XiaomiMiMo / Xunfei）都走 `ChatOpenAI` + 自定义 `base_url`。
- `_llm_ainvoke`（`base.py:131`）是统一调用入口，带 llm-perf 记账。
- **已有雏形**：`content_strategist._plan_content` 手写了一段 "semantic validator + 带 hint
  重生成"（`selected_topic` 必须落在候选集内，否则带纠偏提示重跑一次）。本片要做的是把它
  抽出成设施，而不是发明它。

## 口径确认（2026-09-15，动手前与用户拍板）

1. **native 落地方式：能力探测 + 降级链**（不做全量 native）。理由：主线端点的
   `response_format` / tool-calling 支持度**无法离线验证**，把可用性赌在未验证的端点上会让
   生产主链挂掉。能力按 provider 静态声明 + **可覆盖**，降级链保证任一步失败都能继续。
2. **schema 来源：混合** —— 新定义"LLM 输出模型"（字段宽松、错误反馈对模型友好），校验后
   归一化映射到 state/API。`backend/api/generated/models.py` 保持前端契约身份不被污染：它是
   OpenAPI 生成物，含 `AwareDatetime` / hex `pattern` / `StrictStr`，对 LLM 过严 —— 模型返回
   naive 时间或 3 位 hex 是**合法输出**，不该判失败。
3. **本片范围：脚手架 + 1 条试点**（content_strategist 的 ContentPlan）。其余 24 个调用点后续
   切片迁移，节奏同 P1c 的 S3a→S3d。

## 设计

三层，职责不重叠：

### 1. 能力声明（`backend/models/structured.py`）

`StructuredMode` 三档：

- `NATIVE_SCHEMA` —— provider 原生 schema（LangChain `with_structured_output`）
- `JSON_OBJECT` —— `response_format={"type": "json_object"}`：约束语法，不约束 schema
- `PROMPTED` —— 只能靠 prompt 约束 + 事后校验

默认按 provider 声明（**声明不是探测结果**，注释写明来源与未验证状态），并允许环境变量覆盖
—— 端点能力是外部事实，写死的表会过时。

### 2. 降级链 + 校验 + 重试（同模块）

`invoke_structured(model, messages, output_model, *, validator=None, max_attempts=2)`：

- 按声明档位尝试 → 失败降一档 → 最末档 `PROMPTED`
- **不变量：无论走哪条路，产物都必须过同一个 Pydantic `output_model` 校验**
- `validator` 是 semantic validator：返回 `None` 通过，返回 `str` 作为给模型的纠错提示
- 校验失败 → 把错误（Pydantic 的字段级错误 或 validator 提示）拼进下一轮 messages 重试
- 重试用尽 → 抛 `StructuredOutputError`（带最后一次原始文本与错误），**不返回半成品**

### 3. 输出模型 + 归一化（`backend/models/outputs.py`）

`ContentPlanOutput` 比前端契约宽松（时间是 `str`、枚举是 `str`、`extra="ignore"`），配
`normalize_content_plan()` 映射到 state 形状（ISO 时间、`#` 前缀、枚举收敛）。
**严格性留在归一化之后**：state/前端契约的要求不变，只是 LLM 的接受面更宽。

## 红线

- **不改 prompt 文本**：L0-L5 字节不变（P1b 快照 0 漂移）。schema 约束走 native 参数或追加在
  **运行时消息**末尾，不写进 system prompt。
- 不改 `backend/api/generated/`（生成物）。
- 不动 `_parse_json_response` 的现有行为（本片只让新链路不再依赖它；"降级为 legacy fallback"
  由后续切片在调用点逐个完成）。
- 不引入新依赖。

## 切片计划（每片独立 PR）

| 切片 | 内容 | 风险 |
|---|---|---|
| **S1（本片）** | 能力声明 + 降级链 + 校验重试 + `ContentPlanOutput` / 归一化 + content_strategist 试点迁移 | 中 |
| S2 | 其余 `astron-code-latest` 主链 agent 逐个迁移（scout / analysis 类） | 中 |
| S3 | 写出类（copywriter / version_generator / visual_designer / shooting_planner） | 中 |
| S4 | `llm_enrichment` 副本收敛 + `_parse_json_response` 正式标 legacy | 低 |

## 验收

- 降级链在三种声明档位下都有测试；**任一路径的产物都过同一套校验**
- 校验失败会带字段级错误重试；重试用尽抛错（不返回半成品）
- content_strategist 试点行为不劣化：既有测试全绿，语义校验（`selected_topic` 候选集）通过
  validator 表达而非手写分支
- L0-L5 prompt 字节不变，P1b 快照漂移 **0**
- 全量 `tests/unit` + `tests/integration` 通过；ruff / mypy 干净

## S1 执行记录（2026-09-15，分支 `feat/p1d-structured-output`）

### 交付

| 文件 | 内容 |
|---|---|
| `backend/models/structured.py`（新） | `StructuredMode` 三档 + provider 声明表 + `degradation_path` + `resolve_structured_mode`（显式 > `XHS_STRUCTURED_MODE_<PROVIDER>` > 表）+ `render_schema_instructions` / `describe_validation_error` / `validate_output` + `StructuredOutputError` |
| `backend/models/outputs.py`（新） | `ContentPlanOutput`（宽松，只有 `selected_topic` 必填）+ `normalize_content_plan`（`normalize_*` 只负责“值”，形状宽松在模型里） |
| `backend/agents/base.py` | `_llm_ainvoke` 增 `runnable` / `model_kwargs` 与 `raw` 解包；新增 `_llm_structured` / `_structured_call` |
| `backend/agents/content_strategist.py` | `_plan_content` 试点迁移：手写“重生成一次”分支 → 闭包 validator |
| `backend/graph/builder.py` | 修既有缺陷：`content_strategist` 条件边补 `"__end__": END`（见下） |
| 测试 | `tests/unit/models/test_structured.py`、`tests/unit/models/test_outputs.py`、`tests/unit/agents/test_llm_structured.py`、`tests/unit/graph/test_conditional_edge_wiring.py` |

### 动手后才暴露的四件事（每件都改在本片内）

1. **纠偏从“一次后照收”被悄悄升格成硬约束**。旧实现重试 1 次后接受漂移（只置
   `topic_revised`），新链路默认用尽即抛 → 一个固执的模型就能让节点失败。设施里因此
   加了 `accept_last_valid`：**schema 过不了永远不返回**（不变量），**schema 过了但
   validator 拒收**则按调用方声明的强度处置（默认仍抛）。content_strategist 声明
   `accept_last_valid=True`，与旧口径一致且重试次数更多（2 > 1）。
2. **`validate_output` 把两种失败压成同一个返回值**，正是上面第 1 条踩的坑。改成
   只做 schema（语义校验由调用方对返回的实例跑），差异留在调用点可见。
3. **native 档位此前是死的**：`with_structured_output` 返回的是已校验的**实例**，
   而 `validate_output` 只认 `dict` → 每个 native 答案都被判不合格并降级。改为同时
   接受「可校验的 mapping」与「`output_model` 的实例」，其它对象仍拒收。
4. **`outputs.py` 的宽松分支原本不可达**：`list[str]` 字段会先被 Pydantic 拒掉，
   `normalize_*` 里的 Mapping / datetime 分支永远跑不到——文档写着宽松，代码是死的。
   更糟的是模型若把 `key_points` 写成 `"要点一、要点二"`，`list[str]` 会**逐字符**
   迭代，得到一个看起来成功的字符列表。形状宽松因此上移到模型（`mode="before"`
   校验器 + `_as_list`），`normalize_*` 只管契约值，两边各司其职。

### 顺带发现的既有缺陷（非本片引入）

`content_strategist_router` 有终点守卫（避免 `ripple_gate` 用默认 1.0 自动接受、
把 ERROR 阶段覆盖成 `creating`），返回类型也声明了 `"__end__"`；但
`builder.py` 里 `content_strategist` 的条件边 path_map **只映射了
`ripple_finalize` / `ripple_gate`**。LangGraph 要用路由返回值去查这张表，于是这条
终局分支抛 `KeyError: '__end__'` —— **content_strategist 一旦失败，整个图崩掉而不是
收尾**。四个兄弟分支都有这一项，说明是漏写。新增
`tests/unit/graph/test_conditional_edge_wiring.py`：把「router 的 `Literal` 返回值
集合」与「path_map 的键集合」做双向结构比对（含“读不懂注解就报错”、豁免名单必须
显式列出、反向检查 map 的目标必须是真实节点），并给出复现该缺陷的非平凡用例。

### 门禁

- `pytest -q`：**2868 passed / 3 skipped**（既有 3 个 flaky 本次未触发）
- `ruff check` / `ruff format --check`：491 files 干净
- `mypy backend --python-version 3.12`：199 files 干净
- P1b 基线 `--compare --drift-pct 5`：**drift within threshold（0）** —— L1 schema 走
  运行时消息，system prompt 逐字节未动
- `scripts/gates/tool_runtime_gate.py`：OK（orphan 仍只有 `xhs.publish`）


## S2a 执行记录（2026-09-15，分支 `feat/p1d-s2a-scout-agents`）

票面要求「逐个迁移」，7 个 agent 一次做完会是一个难以 review 的大 PR，所以先切 scout 类
（`trend_scout` + `blogger_scout`，3 个调用点）—— **恰好覆盖 PROMPTED 与 JSON_OBJECT 两个
档位**：`trend_scout` 走 SCOUTING → XUNFEI（PROMPTED），`blogger_scout` 走 MOCK_GEN →
DEEPSEEK（JSON_OBJECT），后者是仅有的两个走 JSON_OBJECT 档的 agent 之一。

### 交付

| 文件 | 内容 |
|---|---|
| `backend/models/outputs.py` | 7 个新模型（`HotTopicItemOutput` / `CompetitorPostOutput` / `NicheOpportunityOutput` / `TrendingNoteOutput` / `TrendScoutOutput` / `BloggerCandidateOutput` / `BloggerScoutOutput`，`__all__` 2 → 8）+ `normalize_trend_data` / `normalize_blogger_candidates`；助手 `_as_float`（`"90%"` 只去符号不换算）、`_as_int`（`"5万"` / `"1.2w"` / `"3k"`）、`_topic_text`（`topic` / `title` / `name` / `keyword` 别名） |
| `backend/models/structured.py` | `render_schema_instructions` 递归展开嵌套模型（`_nested_models` + `_describe_fields`，每个模型只展开一次）；`_type_label` 认识 `Any` 与 `Optional[X]` |
| `backend/agents/trend_scout.py` | `_llm_ainvoke` + `_parse_json_response` + 手写别名链 → `_llm_structured`；失败时降级为 `normalize_trend_data(TrendScoutOutput())`（空结构只有一个来源） |
| `backend/agents/blogger_scout.py` | 同上；删掉 `_retry_mock_with_explicit_json`（36 行、无测试引用，功能被设施自带的纠偏取代） |
| `backend/agents/base.py` | `_llm_structured` 增第三类失败：**一次都没问到** → 原样抛回（见下） |
| 测试 | `test_outputs.py`(+171) / `test_structured.py`(+72) / `test_llm_structured.py`(+81) / `test_blogger_scout.py`（替身重做）/ `test_trend_scout.py`（失败语义改写） |

### 动手后才暴露的三件事

1. **`_llm_structured` 把「问不到」当成了「答得不好」—— 本片最贵的一处**。S1 的框架只有
   两种失败（产物坏掉 / 产物被 validator 拒收），而「调用本身抛错」被当成「这一档不可
   用」直接降级。对 scout 的后果是：**LLM 完全不可用会被降级成空趋势、节点报 success，
   `07-07` 的 error state 与 P1a-S2 的 failed perf 条目一起消失**，
   `tests/integration/test_stateful_retry.py` 三条 E2E 直接变红。判决为 **(b) 类（行为真
   变差）→ 改设施**：链条走完仍**没有任何一档给出过答复**时抛原始异常，而不是
   `StructuredOutputError`。这个区分是承重的 —— `StructuredOutputError` 是调用方用来转成
   业务兜底（「这次没有趋势」）的东西，一次故障借走这个含义就不再被重试。
2. **`_parse_json_response` 的失败产物 `{"raw_content": ...}` 现在能通过 schema**：全默认
   字段 + `extra="ignore"` 让它变成一个合法的空 `TrendScoutOutput`。所以「模型原文不进
   state」由**输出模型声明过所有键**保证，而不是被链条拦住 —— 两个机制都在，断言钉的是
   可观察性质而不是某一个机制。
3. **`render_schema_instructions` 对嵌套模型渲染不足**：scout 的输出恰恰是嵌套的，而旧实
   现只会输出类名。补递归展开，并顺手修 `_type_label` 把 `Optional[X]` 当 `string` 的错
   —— 它与「只展开一次」叠加后**没有补偿信息**：第二个引用同一模型的字段只剩一个错误标签。

### 顺带发现的既有缺陷（非本片引入）

- `trending_notes`（`blogger_scout._summarize_trend_data` 读 `title`）与
  `market_saturation`（`content_strategist` 原样透传给 Ripple）都被真实读取，却不在
  `state/substates.py::TrendData` 里 —— 此前只在模型碰巧输出该键时才有值。两者已进输出
  模型，并有一条测试把与契约的差距**显式钉成「恰好这两个键」**，免得它悄悄变成三个。
- `test_blogger_scout.py` 6 条用例用 `AsyncMock()` 当模型：`bind()` 返回**未被 await 的协
  程** → JSON_OBJECT 档 `AttributeError` → 链条静默降级到 PROMPTED，测试全绿却从没跑过生
  产用的那一档。换成真对象替身（`_JsonModel`），并加一条
  `bound == [{"response_format": {"type": "json_object"}}]` 断言把「跑的是生产那一档」钉住。

### 门禁

- `pytest -q`：**2910 passed / 3 skipped**
- `ruff check` / `ruff format --check`：493 files 干净
- `mypy backend --python-version 3.12`：199 files 干净
- P1b 基线 `--compare --drift-pct 5`：**drift within threshold（0）**
- `scripts/gates/tool_runtime_gate.py`：OK（orphan 仍只有 `xhs.publish`）

## S2b 执行记录（2026-09-15，分支 `feat/p1d-s2b-analysis-agents`）

票面 S2 是「其余走 `astron-code-latest` 的主链 agent」。侦察出 **6 个调用点分布在 5 个 agent**：
`brief_analyzer`（解析 + 澄清，2 个）、`analyst`、`content_analyzer`、`viral_matcher`，以及
`content_strategist.py:420` 的 **S1 残留**（低传播重生成那条分支）。

**`evaluator` 单独留作 S2c**：它是唯一一个已经有确定性重算构建器
（`_build_evaluation_result`，约 250 行）与 degraded 路径的调用点 —— 迁移它等于改写既有逻辑，
而不是替换一个解析器，属另一类改动。

### 交付

| 文件 | 内容 |
|---|---|
| `backend/models/outputs.py` | 11 个新模型 + 6 个 `normalize_*`（`__all__` 8 → 21）：brief（`BriefAnalysisOutput` + `normalize_brief_analysis`）、澄清（`ClarificationQuestionOutput` / `BriefClarificationOutput` + …）、分析（`AnalyticsOutput` + …）、差距分析（`GapItemOutput` / `SuggestionItemOutput` / `OptimizationAnalysisOutput` / `ContentAnalysisOutput` + …）、爆款参考（`ViralPostOutput` / `ViralPostsOutput` + …）；助手 `_non_blank` |
| `backend/models/structured.py` | `accepts_bare_list` 声明 + `_takes_a_list_root` + **形状感知的纠偏文案**（`_OBJECT_ROOT_CORRECTION` / `_LIST_ROOT_CORRECTION`） |
| `backend/agents/*.py` ×5 | 6 个调用点全部改走 `_llm_structured`；`content_strategist` 的 S1 残留清零 |
| 测试 | `test_outputs.py`(+267) / `test_structured.py`(+74) / 4 个 agent 测试文件（+476） |

### 设计决定

**降级语义按调用点的可观测后果分别定，而不是统一抄一份。**

| 调用点 | 「问过了但不可用」 | 「一次都没问到」 |
|---|---|---|
| `brief_analyzer`（解析 + 澄清） | 空解析 —— confidence 0.5 < 阈值 0.6，仍然去问用户（= 旧行为） | 上抛 |
| `analyst` | 空快照 | **上抛** —— 空快照带着 `engagement_rate=0.0` / `views=0` 进 state 与报表，与"一次真实的零表现"无法区分（P1c「全零不是数据」的上一层） |
| `content_analyzer` | 空三键结构 | **上抛** —— 同上，空差距分析看起来像"这篇没有差距" |
| `viral_matcher` | 空参考列表 + `optimization_error` | **一起兜住**（= 旧行为）—— 爆款参考是本节点唯一的可选产出，而失败**被贴了标签**进 state，不是被伪装成"这次没搜到" |
| `content_strategist`（重生成） | — | 上抛（与主调用点一致） |

**`accepts_bare_list` 是设施缺口，不是语法糖。** `validate_output` 一律拒收非 object 顶层，而
`_parse_json_response` 对 `[{"field": …}]` 真的返回 `list`（实测，不是推断）——两个旧调用点
（`brief_analyzer` 的澄清、`viral_matcher`）**两种拼法都收**。直接迁移会把"能收下"变成"硬失败"。
这个形态差异 Pydantic 表达不了（object-only 那道闸在 `model_validate` 之前），所以由模型用
`accepts_bare_list: ClassVar[bool]` 自己声明，`validate_output` 据此放行。

纠偏文案随之形状感知：告诉一个收问题列表的模型"必须是 JSON 对象"，会把重试花在把它收窄到我们
不需要的那个拼法上 —— 而纠偏是重试机制的全部。

**三处"唯一来源"的收敛**（旧代码里同一件事有两个说法）：
- **空分析长什么样**：`content_analyzer` 旧代码缺键时另手写 `{"gaps": [], "suggestions": [], "viral_patterns": []}`
  → 现在只有 `normalize_optimization_analysis` 一个来源；
- **必带/选带话题带不带 `#`**：`normalize_brief_analysis` **原样保留**（品牌方原文），
  `normalize_content_plan` **补一个 `#`**（模型生成的推荐标签）—— 判据是"谁写的内容"，不是"看起来像不像标签"；
- **`SuggestionItemOutput.priority` 默认 3**：提示词的示例写着 `"priority": 1`，`version_generator`
  两处都读 `s.get('priority', 3)` —— 有消费者的字段拿消费者的兜底值，不另发明一个。

### 动手后才暴露的三件事

1. **`analyst` 的 `StructuredOutputError` 只能由"顶层不是对象"触发**。`AnalyticsOutput`
   全字段有默认值 + `extra="ignore"`，所以任何能解析成 dict 的答复都合法 —— 一份
   `{"raw_content": "..."}` 会变成一个合法的空快照。这不是缺陷（空快照的形状由 schema 保证），
   但它意味着这个模型的"答得不好"分支很窄：测试要造一个**数组**答复才走得到。
2. **`viral_matcher` 的超时用例此前是假绿**。它用 `MagicMock()` + `ainvoke` 抛 `TimeoutError`，
   而 `MagicMock` 会自动长出 `bind()`（返回值不可 await）→ JSON_OBJECT 档死于替身**造出来**的
   `TypeError`；又因为链条在"一次都没答"时抛的是**第一档**的异常，最终进 `optimization_error`
   的是那个 `TypeError` 而不是超时。换真替身（`_TimingOutModel`，`bind` 返回自身）后两档都抛真实
   超时，断言恢复原义。
   - **顺带记一笔未改的观察**：`raise unreachable[0][1]` 取的是**第一档**的失败。当各档失败类型
     不同（强档属"能力不支持"、弱档是真实网络错）时，报出来的是前者。S2a 的既有用例（单档，
     或各档抛同一异常对象）分辨不出这个选择，本片也不改它 —— 口径值得单独一轮定。
3. **`SuggestionItem` 契约里本来就有 `priority`**。侦察时的口头结论是"契约漏了这个字段"，
   动手时对着 `state/substates.py` 复核发现文档字符串写错了（契约有、提示词有、消费者也读），
   已按事实改写 —— 与代码相反的注释比没有注释更贵。

### 门禁

- `pytest -q`：**2965 passed / 3 skipped**（较 S2a 的 2910 增 55 条）
- `ruff check .` / `ruff format --check .`：491 files 干净（全仓口径，与 CI 一致）
- `mypy backend --python-version 3.12`：199 files 干净
- P1b 基线 `--compare --drift-pct 5`：**drift within threshold（0）** —— prompt 逐字节未动
- `scripts/gates/tool_runtime_gate.py`：OK（orphan 仍只有 `xhs.publish`）
