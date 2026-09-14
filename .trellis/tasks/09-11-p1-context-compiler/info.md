# P1b 技术方案：Context Compiler（评估件）

> **决策已定（2026-09-14）**：用户以"继续"驱动、按 prd 草案 Q1-Q6 推荐执行——
> D1'=RunContext 为 Pydantic frozen 模型、节点 seam 构造；D2'=niche fail-fast；
> D3'=分段等价 + L0-L2 逐字节稳定；D4'=确定性 token 估算器；D5'=slim /status 拆出本任务；
> D6'=deterministic rerank。如开工前用户推翻某项，改 prd 对应条目即可，不影响其余结构。

依据：`research/consumer-map.md`（拼装路径勘察）、父任务 architecture-review §十五/§十七/§十八、
P1a info.md D4/D5 连带注记。目标：Context 成为独立组件——recall → rerank → dedup →
freshness → confidence → token budget → compile 一条管线；prompt 分层 L0-L5 稳定前缀；
RunContext 作为第一消费方。**本阶段不动 HTTP 契约、不动 checkpoint、不引入 LLM rerank。**

## 一、目标模型

```
RunContext（不进 checkpoint；节点 seam 构造，agent execute 只读）
│   thread_id / account_id / niche / topic / workflow_mode / phase
│   store / config / 已 resolve 的 RuntimeState 视图（hydration 产物）
│
├ ContextItem（流水线统一条目）
│   body / source / timestamp / confidence / scope / priority / token_cost
│
└ Context Compiler（backend/context/ 新包）
    recall（多 namespace 并行，RetrievalResult.mode=hit|empty|degraded 信号）
      → rerank（deterministic：recency + 命中分 + source 权重加权）
      → dedup → freshness（ts 衰减）→ budget（L5→L4 逐层降配额）
      → compile（L0-L5 分段拼装 → CompiledPrompt）
```

**L0-L5 归置（对现状 content 的映射）**：
- L0 = prompt YAML `system` 的 policy/身份段（永不裁剪、逐字节稳定）
- L1 = tool schema（现状无 tool 注入则该层恒空，接口预留）
- L2 = account profile（niche/account_id 等稳定账户事实——现状散在各 user_msg 头部，收拢）
- L3 = task（user_template 正文 + 本 superstep 目标）
- L4 = memory recall 产物（现 `{memory_context}`：历史洞察/偏好/策略）
- L5 = 最新观测（现 `{ripple_context}`、trend_scout 的实时数据块、evaluator 的
  weights_block）——变化最快、预算紧张时最先收缩

## 二、决策与代价（记录，均已拍板）

- **D1' RunContext 构造点**：节点 seam（同 P1a artifact_seam 挂载模式）在 execute 前构造。
  代价：builder.py 一处统一包装；agent 签名不变（RunContext 作参数传入或经 self 暂存——
  倾向参数传入，保 P0-W1 纯净）。TypedDict 进 state 方案被拒（checkpoint 再污染）。
- **D2' niche fail-fast**：start 入口（workflow.py start/brief 两条路径）校验 niche 必填；
  11 处 `state.get("niche", "母婴")` 默认值删除，缺失抛错（P0-W2 namespace fail-fast 同款）。
  代价：老调用方（cli/main.py 等）需显式传 niche——迁移面一次付清。
- **D3' 等价性口径**：每 agent 迁移 PR 附"分段等价"测试（L0-L5 各段内容集合与迁移前
  相等）+ 全局 L0-L2 稳定前缀测试（同 thread 多 superstep 逐字节相等）。行为级评估分
  回归只作观察项不作门槛。代价：测试基建先行（fixture 冻结迁移前编译产物）。
- **D4' token 估算器**：CJK≈1 token/字、ASCII≈1/4 字，函数纯确定性；预算超限按
  priority 降 L5→L4，L0-L3 永不裁剪。代价：非精确计数——接 tiktoken 属单点替换，接口预留。
- **D5' 范围排除**：slim /status + GET artifact API 单列任务（P1a D4 遗留）；checkpoint GC
  单列小任务（P1a info.md 未决项）。两件都不进 P1b。
- **D6' rerank 强度**：deterministic 加权（recency + 命中分 + source 权重）。LLM rerank
  等 P3 outcome learning 后再议。降级信号（§十五 静默 `[]` 的根治）：RetrievalResult
  必带 mode=hit|empty|degraded + error 摘要，进 Event store（复用 P1a workflow_events
  通道，kind=context）可观测。

## 三、实施切片（任务内小步提交，每步全绿）

1. **S1 骨架（零行为变化）**：`backend/context/` 新包——RunContext / ContextItem /
   RetrievalResult / CompiledPrompt 模型 + Compiler 接口与确定性估算器；consumer-map
   勘察入 research/（已完成）。旧路径零触碰。
2. **S2 recall 管线**：多 namespace 并行 recall + RetrievalResult.mode 信号 + deterministic
   rerank/dedup/freshness；事件面（kind=context）落 workflow_events。
3. **S3 L0-L5 分层**：prompt YAML 分段 schema（只分段不改写语义文本）+ budget allocator
   + L0-L2 稳定前缀测试 + 分段等价 fixture 基建。
4. **S4 逐 agent 迁移**：先野路径（trend_scout 自拼、copywriter/content_strategist 的
   ripple_context、evaluator weights 特例）→ base 通用路径 → 其余 7 个纯模板 agent；
   每迁一个删对应 replace，niche fail-fast 最后统一切。
5. **S5 验收基准**：token 成本/分层稳定性对比脚本（手法参照 P1a S4-6：确定性可复跑、
   生产同路径）写入 research/；全量门禁。

## 四、风险与未决问题

- **prompt YAML 分段是行为敏感面**：分段化不得改写任何语义文本（红线）；分段边界靠
  YAML anchor/注释标记，解析失败 fail-fast。
- **RunContext 与 P0 ContextVar 的关系**：P0 用 ContextVar 修了共享可变状态；RunContext
  是值对象（frozen），不与 ContextVar 冲突，但传参方式（参数 vs self 暂存）需在 S1 定死，
  避免 13 个 execute 点两种风格并存。
- **strategy_notes namespace 无 agent 消费方**（recall 零调用）：是迁移时顺手清 dead ns
  还是保留给 P1b 新管线用——S2 开工时定。
- 未决（不阻塞开工）：L1 tool schema 层现状为空，接口预留到 P1c Tool Runtime 才有实体。

## 五、验收

全部 agent 执行点的 prompt 经 Compiler 编译（零散装 replace 残留，grep 可验证）；
`niche` 隐式默认 = 0；L0-L2 稳定前缀测试绿；memory 静默降级消灭（mode 全路径可观测）；
token 预算生效且有测试；基准报告入 research/；全量测试 + mypy strict + ruff 六门绿；
S1–S5 合入 main（独立 PR）。
