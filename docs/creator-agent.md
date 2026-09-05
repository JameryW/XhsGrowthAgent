# Creator Agent 决策核心

Creator Agent 是创作者判断能力的持久化层，不是内容生成器。它把一个创作者的独立身份、偏好、知识主张和决策政策保存为 revisioned Creator Model，再对具体 Audience Member 的结构化需求给出可追溯的候选排序。

## 最小闭环

```text
Creator Model (revision N)
        ↓
Decision Request + candidates
        ↓
Decision Record + Evidence
        ↓
User Feedback
        ↓
Relationship Memory + pending creator review
```

模型和反馈是两条不同的写入路径：反馈会形成 Decision Dataset 和 Relationship Memory，但不会自动修改 Creator Model。只有创作者显式提交下一版模型，revision 才会增加。

## API 示例

所有接口都需要现有的 `Authorization: Bearer ...`，并且 `account_id` 必须属于当前用户。

### 创建或修订模型

```http
PUT /api/creator-agent/model
```

```json
{
  "account_id": "xhs-account-1",
  "expected_revision": 0,
  "model": {
    "identity_summary": "重视长期体验和可解释权衡的家居创作者",
    "domains": ["家居"],
    "preferences": [],
    "knowledge": [],
    "policies": [
      {
        "policy_id": "daily-durability",
        "label": "日常使用先看耐用性",
        "applies_when": {"scene": "daily"},
        "signal_weights": {"durability": 0.8, "price": 0.2},
        "preferred_tags": ["low-maintenance"],
        "excluded_tags": ["high-maintenance"],
        "rationale": "长期使用时先保证稳定性，再看价格。",
        "evidence_ids": ["creator-statement-1"]
      }
    ],
    "evidence": [
      {
        "evidence_id": "creator-statement-1",
        "source_kind": "creator_statement",
        "source_ref": "creator://statement/1",
        "claim": "我优先耐用和低维护",
        "confidence": 0.95
      }
    ]
  }
}
```

第一次写入使用 `expected_revision=0`，服务会生成稳定的 `creator_id` 和 revision `1`。后续写入必须带当前 revision；旧 revision 会返回 `409 ERROR_CREATOR_MODEL_REVISION_CONFLICT`。

### 做一次决策

```http
POST /api/creator-agent/decisions
```

请求需要提供 `audience_id`、目标、上下文和至少两个候选。候选的 `signals` 是调用方经过归一化的 `0..1` 数值；Creator Agent 负责应用政策、偏好、硬约束和证据，不负责凭空搜索产品事实。

返回的 `Decision Record` 会固定使用当时的 `model_revision`。如果没有匹配政策或没有可追溯 Evidence，状态是 `insufficient_evidence`，不会给出伪装成推荐的答案；如果所有候选都被约束/排除，状态是 `no_eligible_candidate`。

### 记录反馈

```http
POST /api/creator-agent/decisions/{decision_id}/feedback
```

反馈必须带同一 `audience_id`。`accepted`、`purchased`、`satisfied` 会积累关系中的已采纳候选；`rejected`、`dissatisfied` 会积累被拒绝候选。带 `correction` 或 `dissatisfied` 会返回 `learning_status=pending_creator_review`，提示创作者决定是否更新模型。

### 查看和审核 Learning Signal

纠正意见和不满意反馈会生成一个独立的 `Learning Signal`。它会保存当时
Decision Record 的 Evidence ID 快照，且不会自动改变 Creator Model：

```http
GET /api/creator-agent/learning-signals?account_id=xhs-account-1&status=pending_creator_review
```

创作者可以明确驳回信号：

```http
POST /api/creator-agent/learning-signals/{signal_id}/review
```

```json
{
  "account_id": "xhs-account-1",
  "disposition": "dismissed",
  "review_note": "这是一次性场景，不改变长期判断。"
}
```

若要采纳，必须提交完整的下一版模型和当前 revision。服务会在同一事务中
写入新模型并把 `applied_model_revision` 链接到信号：

```json
{
  "account_id": "xhs-account-1",
  "disposition": "approved",
  "expected_revision": 1,
  "review_note": "将便携性加入日常场景权衡。",
  "model": { "identity_summary": "完整的下一版 Creator Model" }
}
```

生产请求应携带完整的 `CreatorModelDefinition`（上例仅展示字段形状）。过期
revision 返回 `409` 且不会留下部分写入；重复反馈和重复审核保持幂等，改变
已审核信号的 disposition 会返回冲突。

### 查询 Evidence Graph

Evidence Graph 是从当前 Creator Model、Decision Record 和 Learning Signal
快照组装的只读投影，不引入第二套 Evidence 写入模型。每个节点按稳定的
`evidence_id` 返回，并带有去重后的 typed references：

```http
GET /api/creator-agent/evidence?account_id=xhs-account-1&source_kind=creator_statement&reference_type=decision
GET /api/creator-agent/evidence/creator-statement-1?account_id=xhs-account-1
```

Reference 类型包括 `model`、`preference`、`knowledge_claim`、
`decision_policy`、`decision`、`candidate` 和 `learning_signal`。候选引用的
`target_id` 使用 `decision_id:candidate_id`，并携带实际使用的模型 revision；
Learning Signal 则从它指向的原始 Decision Record 读取 Evidence payload，避免
后续模型 revision 改写历史 provenance。列表按 `evidence_id` 和 reference
字段稳定排序，未知节点只在所属 account 内查找，返回
`ERROR_CREATOR_EVIDENCE_NOT_FOUND`。

### 创建和解析 Action Intent

Action Intent 是 Decision Record 到未来执行器之间的安全交接层。当前只支持
`compare_options`、`save_shortlist` 和 `request_more_evidence` 三种非交易能力，
创建后永远先处于 `pending_confirmation`：

```http
POST /api/creator-agent/actions
```

```json
{
  "account_id": "xhs-account-1",
  "decision_id": "decision-1",
  "action_kind": "save_shortlist",
  "candidate_ids": ["candidate-a"],
  "idempotency_key": "handoff-2026-09-04-1"
}
```

候选动作只能引用该 Decision Record 的推荐候选；`request_more_evidence` 不允许
候选目标，且可以用于证据不足的 Decision Record。相同账号重试同一个
`idempotency_key` 会返回原始 intent，不会替换候选或 action kind。

```http
GET /api/creator-agent/actions?account_id=xhs-account-1&status=pending_confirmation
POST /api/creator-agent/actions/{action_id}/resolve
```

解析请求必须明确选择 `confirmed` 或 `cancelled`。`confirmed` 只表示未来执行器
可以接收该 intent，本期不会搜索、购买、预约、发消息或调用任何外部系统；变更
已解析 intent 的 disposition 会返回 `ERROR_CREATOR_ACTION_CONFLICT`。

### 执行已确认的 Action Intent

确认后仍需一次显式执行调用，才能生成机器可读的执行收据：

```http
POST /api/creator-agent/actions/{action_id}/execute
GET /api/creator-agent/actions/{action_id}/execution?account_id=xhs-account-1
```

执行请求只携带 `account_id`；服务端从持久化 Action Intent 读取确认状态，不能
由请求体伪造 `confirmed`。`pending_confirmation` 和 `cancelled` 会返回
`409 ERROR_CREATOR_ACTION_EXECUTION_NOT_ALLOWED`，不会写入收据。

本期执行器是 `local-v1`，无搜索、商家、购买、预约、消息或平台写入副作用：

- `compare_options` 返回选中推荐候选的 Decision Record 快照（候选 ID、标签、
  分数、理由和 Evidence ID）；
- `save_shortlist` 返回选中的推荐候选 ID，作为可审计的 shortlist 结果；
- `request_more_evidence` 返回原 Decision Record 的状态、Evidence 覆盖率和置信度，
  交给上游调用方继续补证据。

同一 `(account_id, action_id)` 只会产生一张不可变收据，重复 POST 和 GET 返回相同
的 `execution_id`、结果和时间戳。收据保留 `decision_id`、`model_revision`、
`executor_version`，便于未来替换执行器时审计历史行为。

### 查询 Decision Dataset

Decision Dataset 是 Decision Record 和 User Feedback 的只读历史投影，适合
审核、导出和后续训练管线使用。每一行的 `decision` 都是创建时保存的完整快照，
不会因为当前 Creator Model revision 变化而重新计算；`learning_signal_ids` 只返回
同一账号、同一 decision 关联的 Signal ID，不展开 Signal payload：

```http
GET /api/creator-agent/dataset/decisions?account_id=xhs-account-1&limit=20
GET /api/creator-agent/dataset/decisions?account_id=xhs-account-1&audience_id=audience-1&status=recommended&feedback_outcome=purchased&has_feedback=true
```

结果按 `created_at DESC, decision_id DESC` 稳定排序，`total` 是当前筛选条件下的
完整总数，即使请求带 `cursor` 也不会变成“剩余行数”。`next_cursor` 是仅包含该
排序键的版本化不透明游标；游标损坏会返回 `ERROR_VALIDATION`，不会静默回到第一页。
过滤条件会先应用，再计算总数和分页，`limit` 范围为 `1..100`。账号归属校验在
读取任何快照之前完成；接口不会写入反馈、Learning Signal、Action Intent 或模型。

## 与现有能力的关系

- XHS Account 仍是平台操作和权限范围；Creator ID 才是可迁移的创作者身份。
- Creative Memory（Style DNA、转化策略、素材）可以在未来作为 `creator_content` Evidence 接入，但不等于 Creator Model。
- Trend / Brief / Free 工作流本期保持兼容；后续可以把它们的建议生成改为调用 `CreatorAdvisor`，而不是各自拼接字符串。
