# P1b 实施 prd — Context Compiler（已拍板：按推荐执行）

> 状态：**已定（2026-09-14）**。用户以"继续"驱动，Q1–Q6 按推荐执行并冻结为
> info.md D1'–D6'（含代价记录）；开工前如需推翻某项，改 info.md 对应条目即可。
> 技术方案见同目录 `info.md`，拼装路径勘察见 `research/consumer-map.md`。
> 前置：P1a（09-11-p1-kernel-state-layers）合入 main；本任务分支自 main 开（独立 PR）。

设计权威来源：父任务 prd P1b 段 + `09-11-runtime-upgrade/research/architecture-review-2026-09-11.md`
§十七（Context 未组件化）、§十八（stable prefix / KV 命中）、§十五（静默降级）+ P1a info.md
D5（RunContext 归 P1b、为 Compiler 第一消费方）与 D4 连带注记。现状证据见文末盘点。

## 目标（父 prd 已定）

统一 **recall → rerank → dedup → freshness → confidence → token budget → compile**；
prompt 分层 **L0-L5 稳定前缀**（L0 system/policy、L1 tool schema、L2 account profile ｜
L3 task、L4 memory、L5 observations）；**消除 `"母婴"` 隐式默认上下文污染**；context item
带 **source / timestamp / confidence / scope / priority / token_cost**；引入 **RunContext**
（P1a D5：Compiler 的第一消费方）。

## 决策点（已按推荐冻结 → info.md D1'–D6'）

### Q1 RunContext 形态与构造点
- **A（推荐）**：Pydantic frozen 模型，在 graph 节点 seam 处构造（复用 P1a artifact_seam
  挂载点），agent `execute()` 只读消费。可测试性最好，checkpoint 零污染。
- B：TypedDict 随 state 走——省一层传递，但重新把大对象塞回 checkpoint，违背三层模型。

### Q2 niche 隐式默认消灭方式
- **A（推荐）**：fail-fast——start 入口校验 niche 必填，运行期缺失即抛错（同 P0-W2
  namespace fail-fast 先例）；11 处 `state.get("niche", "母婴")` 默认值全删。
- B：默认值收口为单一常量——改动最小，但静默污染继续存在，与目标相悖。

### Q3 等价性口径（L0-L5 重排后 prompt 无法 byte-equal）
- **A（推荐）**：分段等价——每个 agent 编译产物按层断言"内容集合相等"；另加
  **L0-L2 同 thread 逐字节稳定测试**（prompt cache 命中的前提）。
- B：行为级等价（评估分分布不回归）——信号弱、慢，只作补充不作门槛。

### Q4 token 预算计数
- **A（推荐）**：确定性估算器（CJK ≈1 token/字、ASCII ≈1/4 字），零新依赖；超限按
  priority 从 L5→L4 逐层降配额，L0-L2 永不裁剪。
- B：tiktoken——精确但对非 OpenAI provider 仍需 fallback，多一份依赖。

### Q5 scope：slim /status + artifact API 是否并入
- **A（推荐）**：不入——P1b 只管 LLM-facing context；HTTP 面 UI 演进单列任务
  （P1a info.md D4 原文即"留待 P1b/UI 演进任务"，拆开两风险面）。
- B：并入一次改完——Context Compiler 与 HTTP 契约两个风险面耦合，回滚面大。

### Q6 rerank 强度
- **A（推荐）**：deterministic rerank（recency + 命中分 + source 权重加权），遵守克制
  原则（能 deterministic 不放 LLM）。
- B：LLM rerank——成本/延迟 + 新失败面，P3 outcome learning 后再议。

## 实施要求（按切片，草案）

1. **S1 骨架（零行为变化）**：RunContext + ContextItem（source/timestamp/confidence/
   scope/priority/token_cost）模型 + Context Compiler 接口；现有拼装路径勘察落图
   （research/consumer-map）。
2. **S2 recall 管线**：多 namespace 并行 recall；`RetrievalResult.mode/degraded` 降级
   信号（消灭 `_recall_memory` 异常静默 `[]`，评估 §十五）；deterministic rerank /
   dedup / freshness / confidence。
3. **S3 L0-L5 分层**：prompt YAML 分段 schema（不改写语义文本）+ token budget
   allocator + **L0-L2 稳定前缀测试**。
4. **S4 逐 agent 迁移**：`template.replace` → Compiler；顺序从拼装最野者开始
   （trend_scout 自拼、copywriter/content_strategist 的 ripple_context、evaluator 的
   weights 特例）→ base 通用路径；niche fail-fast 落地，11 处默认清除。
5. **S5 验收基准**：分层稳定性 + token 成本对比脚本写入任务 research/（手法参照
   P1a S4-6：确定性可复跑、生产同路径）；全量门禁。

## 红线与约束（草案）

- 不动 HTTP 契约；不动 checkpoint/reducer 语义（RunContext **不进** checkpoint）。
- 不引入 Task/ToolResult/ActionIntent（P1c/P2a）；不新增 LLM Agent（克制原则）。
- prompt YAML 仅限结构分段化，system 语义文本不改写（防行为漂移）。
- 全量 `pytest tests/unit tests/integration` 零新增失败；mypy strict 零错
  （`--python-version 3.12`）；ruff 干净；uv.lock churn 永不入库；小步提交每步全绿。
- checkpoint GC（completed 线程裁剪）为 P1a 遗留未决项，**单列小任务，不入本任务**。

## 完成定义（草案）

全部 agent 执行点（base.py 注释载明 13 处）的 prompt 均经 Context Compiler 编译，零散装
replace 残留；`niche` 隐式默认 = 0（grep 可验证）；L0-L2 稳定前缀测试绿；memory 静默
降级消灭（RetrievalResult.mode 全路径可观测）；token 预算生效且有测试；基准报告入
research/；S1–S5 合入 main（独立 PR）。

## 现状盘点（证据，2026-09-14）

- 拼装：`BaseAgent._build_system_prompt` = `template.replace("{account_niche}"/
  "{memory_context}")`（base.py:156-161）；evaluator 另有 weights_block/pass_threshold/
  reject_threshold 替换（evaluator.py:154-161）；content_strategist/copywriter 各自管理
  `{ripple_context}`（含 retry 路径多处 replace）；trend_scout 自拼 memory + 实时数据 +
  user topic。
- 隐式默认：`niche = state.get("niche", "母婴")` 散布 **11 处**（base:158、analyst:98、
  blogger_scout:33/83、content_strategist:39、copywriter:117、evaluator:151、
  blogger_gate:145、trend_scout:109、visual_designer:47、review_gate:55）。
- 检索：`_recall_memory`（base.py:163-192）单 namespace 向量搜索 limit=5，
  `except → warning + []` 静默降级；无 rerank/dedup/freshness/confidence/budget。
- prompt 来源：`backend/config/prompts/*.yaml`（system + user_template 两键，
  base.py:141-154）。
