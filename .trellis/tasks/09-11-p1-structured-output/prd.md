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
