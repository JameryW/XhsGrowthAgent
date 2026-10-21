# Memory Promotion Pipeline（协议层）

> 状态：**Slice A 已落**（`backend/memory/promotion.py` + 测试），Slice B/C/D 未实现。
> 设计依据：`.trellis/tasks/10-21-memory-promotion-pipeline/prd.md`；
> 现状侦察：同目录 `research/2026-10-21-recon.md`。
> 路线图出处：`docs/agent-os-upgrade-2026q4.md` §3 第 7 行。

## 1. 这一层是什么（以及不是什么）

`backend/memory/promotion.py` 是**决定协议**，不是管道实现：

- 输入：一条候选记忆（`PromotionCandidate`）、调用方已经读回来的来源事实
  （`SourceCheck`）、目标键当前已晋升的记录（`ExistingEntry`）、策略阈值
  （`PromotionPolicy`）；
- 输出：一条 `PromotionDecision`（disposition / reason / dedupe / verified /
  supersedes / decided_by / policy_version）；
- **不做**：I/O、存储、时钟、随机、写 prompt、写记忆、审核 UI。

设计动机（PRD §3）：hy-memory 的 reconciler 对仓库不可透明，而"这条记忆凭什么进
prompt"必须能从仓库自己的数据复算。所以 SDK 的抽取只是**候选来源**，闸门在仓库里。

与 `backend.state.progress`（P0-A）同形：先把判断变成可观测、可测试的纯函数，再谈接线。

## 2. 输入从哪来

| 输入 | 谁提供 | 关键约定 |
|---|---|---|
| `PromotionCandidate` | 候选来源适配器（Slice B/D） | `source_ref` 必须可解析；`source_version` 必须可排序（ISO-8601 或行版本） |
| `SourceCheck` | 调用方的**窄 reader** | reader 读失败**抛异常**（本层没有 fallback）；"读到了但不存在"是 `present=False`；`degraded=True` 表示 reader 本身不可用 |
| `ExistingEntry` | 目标命名空间的晋升记录（Slice B 的 ledger） | 只用于键级去重，不看正文 |
| `PromotionPolicy` | 部署配置 | `min_samples` 默认 5；默认只允许 `internal_fact` 自动晋升；`allowed_namespaces=None` 表示不限制 |

**候选形状的硬约束**（`__post_init__` 校验，违反即 `ValueError`，不是 REFUSE）：
非空 `namespace/key/body/source_ref/observed_at`；`sample_count >= 0`；
`measured_rate ∈ [0,1]` 或无；`ttl_seconds > 0` 或无；`evidence_ids` 不重复；
`trust_class` 必须是 `backend.context.models.TrustClass` 成员（复用 Context Compiler 的
provenance 词表，不另造一套）。

## 3. 判决优先级（契约的一部分）

顺序固定；同样输入必须得到同样输出，不能依赖调用方先跑了哪一步。

| # | 条件 | disposition | reason | dedupe |
|---|---|---|---|---|
| 1 | reader degraded | REFUSE | `source_degraded` | `not_evaluated` |
| 2 | 候选没有 `source_version` | REFUSE | `source_unversioned` | `not_evaluated` |
| 3 | 来源不存在 | REFUSE | `source_missing` | `not_evaluated` |
| 4 | TTL 过期（调用方判定） | REFUSE | `ttl_expired` | `not_evaluated` |
| 5 | 任一引用证据解析不到 | REFUSE | `evidence_missing` | `not_evaluated` |
| 6 | 命名空间不在 policy 白名单 | REFUSE | `policy_blocked` | `not_evaluated` |
| 7 | 来源版本 ≠ 候选版本 | REVIEW | `source_stale` | `not_evaluated` |
| 8 | `trust_class` 不在 machine-promotable 集合 | REVIEW | `needs_human_review` | 照常计算（给审核者） |
| 9 | 样本数 < `min_samples`，或 `measured_rate` 缺失 | REFUSE | `insufficient_samples` | 照常计算 |
| 10 | 同键同源、版本比已存记录旧 | REVIEW | `source_stale` | `duplicate` |
| 10 | 同键同源、版本相同 | REFUSE | `duplicate` | `duplicate` |
| 10 | 同键同源、版本更新 | **PROMOTE** | `supersedes_older` | `supersedes`（`supersedes` 列出所有旧 promotion_id，排序） |
| 10 | 同键不同源 / 同源已晋升到别的键 | REVIEW | `needs_human_review` | `needs_review` |
| 11 | 以上都不适用（新键、已测量、版本匹配、证据齐全） | **PROMOTE** | `verified_internal_fact` | `new` |

`verified=True` 只表示**这一遍实际做过的检查**（读到了、版本匹配、证据解析）都通过，
从不表示"内容正确"；所有 REFUSE 路径的 `verified` 都是 `False`（除非拒绝发生在第 9/10 步，
那时读取检查确实已经做完）。

## 4. 封闭词表

`PromotionDisposition`：`promote` / `review` / `refuse`（三种结局，没有第四种"跳过"）。

`DedupeVerdict`：`new` / `supersedes` / `duplicate` / `needs_review` / `not_evaluated`
（`not_evaluated` 与 `new` 刻意分开："没去看"和"看了是新的"是两件事）。

`PromotionReason`：`source_missing` / `source_unversioned` / `source_degraded` /
`ttl_expired` / `evidence_missing` / `insufficient_samples` / `duplicate` /
`policy_blocked` / `needs_human_review` / `source_stale` / `verified_internal_fact` /
`supersedes_older`。

成员集合由 `tests/unit/memory/test_promotion.py::TestEveryReasonIsReachable::
test_the_vocabulary_is_the_published_set` 穷举，且**每个成员都有一个真实输入用例**——
无法到达的枚举值是死词表，不允许存在。

## 5. 确定性

- 无时钟、无随机、无 I/O；所有比较都是纯字符串/数值比较；
- `candidate_id = "cand_" + sha256("<namespace>\\x1f<source_ref>")[:16]` —— 由身份派生，
  不含 `observed_at`。同一候选跨进程/跨重跑是同一个 id（ledger 才能拒绝重复）；
- `supersedes` 元组按 `promotion_id` 排序；同一输入两次调用返回**相等**的 decision。

## 6. 用法（Slice B 接线时）

```python
from backend.memory.promotion import (
    PromotionCandidate, SourceCheck, ExistingEntry, decide_promotion,
)

decision = decide_promotion(
    PromotionCandidate(
        namespace="strategy_notes",
        key="style:治愈:温暖治愈",
        body="治愈风格历史互动率 0.412（样本 10）",
        trust_class=TrustClass.INTERNAL_FACT,
        source_ref="creative-memory://style/style_abc",
        source_version="2026-10-01T20:00:00Z",
        observed_at="2026-10-01T20:00:00Z",
        evidence_ids=("ev_style_style_abc",),
        sample_count=10,
        measured_rate=0.412,
    ),
    source=SourceCheck(
        present=True,
        version="2026-10-01T20:00:00Z",
        evidence_found=("ev_style_style_abc",),
    ),
    existing=(),          # 目标键当前的晋升记录
)

if decision.disposition is PromotionDisposition.PROMOTE:
    ...  # Slice B/C：先记账，再写目标命名空间
```

## 7. 明确不在这里的东西

- **不读任何存储**：来源行、证据、已有记录都由调用方读好再传；
- **不判语义重复**：键级去重是确定的；语义近邻需要 embedding 与判断，只作为审核提示，
  不在本函数内（PRD §3）；
- **不算 TTL**：`SourceCheck.ttl_expired` 由调用方用真实时钟算好传入，本层保持纯函数；
- **不写 ledger、不写记忆、不改 prompt**：Slice B/C；
- **不接 hy-memory**：Slice D，且初期只产 `REVIEW`；
- **不做审核 UI**：复用现有 evidence-proposal / learning-signal 面。

## 8. 下一片

- **Slice B**：append-only ledger（`accounts/{account}/memory_promotions` 或 Postgres，
  待 PRD §9 Q5 裁决）+ 真候选源只记账；
- **Slice C**：第一次 `internal_fact` 晋升 + `context.retrieval` 透传 provenance 字段；
- **Slice D**：hy-memory 候选（`REVIEW` only，`DEGRADED` 批次整体 REFUSE）。
