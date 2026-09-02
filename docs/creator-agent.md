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

## 与现有能力的关系

- XHS Account 仍是平台操作和权限范围；Creator ID 才是可迁移的创作者身份。
- Creative Memory（Style DNA、转化策略、素材）可以在未来作为 `creator_content` Evidence 接入，但不等于 Creator Model。
- Trend / Brief / Free 工作流本期保持兼容；后续可以把它们的建议生成改为调用 `CreatorAdvisor`，而不是各自拼接字符串。
