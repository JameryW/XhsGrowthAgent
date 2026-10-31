# Memory Promotion Pipeline（协议层 + observe-only 通道 + 管理面 + 晋升 + hy 候选 + 人审写入 + TTL 默认 + policy_version + 样本阈值 + 语义近邻 hint）

> 状态：**Slice A–D + 人审写入面（票 5y）+ TTL 默认（票 5z / PRD §9 Q2）+
> policy_version 来源（票 5aa / PRD §9 Q6）+ 样本阈值（票 5ab / PRD §9 Q4）+
> 语义近邻成本（票 5ac / PRD §9 Q3）已落**
> （`backend/memory/promotion.py` 协议；`promotion_ledger.py` append-only 账本；
> `promotion_observations.py` Creative Memory style 观测的 observe-only 通道；
> `GET /api/creator-agent/memory-promotions` 只读管理面；
> `POST .../memory-promotions/{id}/review` 人审关闭 REVIEW；
> `scripts/observe_memory_promotions.py` 真实调用者；`promotion_source.py` 独立重读 +
> `promotion_apply.py` 第一次机晋升 + `context.retrieval` provenance 透传；`promotion_hy.py`
> + `scripts/observe_hy_promotions.py`：hy-memory 候选 **REVIEW** 接入；
> `promotion_review.py`：人审 `approved`/`dismissed` 写路径；
> `promotion_ttl.py`：全 ns 默认 `ttl_seconds=null`（永不过期，只靠 supersede）+
> 调用方 `ttl_expired_for` 助手；
> `DEFAULT_PROMOTION_POLICY_VERSION` + `default_promotion_policy()`：机判决
> `policy_version` 的 Git 常量权威来源；
> `DEFAULT_PROMOTION_MIN_SAMPLES`：机晋升样本阈值（与 `CreativeMemory.MIN_SAMPLES` 对齐，无冷却）；
> `promotion_semantic.py`：仅 `dedupe==NEEDS_REVIEW` 后付 embedding，hint 进账本
> `detail`，index 不可用 → skip-hint）。
> 设计依据：`.trellis/tasks/archive/2026-10/10-21-memory-promotion-pipeline/prd.md`；
> 人审票：`.trellis/tasks/10-29-memory-promotion-review-write/prd.md`；
> TTL 票：`.trellis/tasks/10-31-memory-promotion-ttl-defaults/prd.md`；
> policy_version 票：`.trellis/tasks/10-31-memory-promotion-policy-version/prd.md`；
> 样本阈值票：`.trellis/tasks/10-31-memory-promotion-sample-threshold/prd.md`；
> 语义近邻票：`.trellis/tasks/10-31-memory-promotion-semantic-near-dupe/prd.md`。
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
| `PromotionPolicy` | 部署配置（经 `default_promotion_policy()`） | `min_samples` 默认 `DEFAULT_PROMOTION_MIN_SAMPLES`（=5，票 5ab，与 `CreativeMemory.MIN_SAMPLES` 对齐）；默认只允许 `internal_fact` 自动晋升；`allowed_namespaces=None` 表示不限制；`policy_version` 来自 `DEFAULT_PROMOTION_POLICY_VERSION`（票 5aa） |

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
`supersedes_older` / `human_approved` / `human_dismissed`。

机器判决成员由 `tests/unit/memory/test_promotion.py::TestEveryReasonIsReachable`
穷举 `decide_promotion` 可达性；`human_approved` / `human_dismissed` **只**由
`promotion_review` 构造（绝不经 `decide_promotion`），由
`tests/unit/memory/test_promotion_review.py` 覆盖——无法到达的枚举值是死词表，不允许存在。

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

## 7. append-only 账本与 observe-only 通道（Slice B1）

### 7.1 存储裁决（PRD §9 Q5）

账本放 `accounts/<account>/memory_promotions`（BaseStore），不建 Postgres 表：

- 记录**不可变**，id 由
  `sha256(candidate_id | source_version | disposition | reason | policy_version)` 派生
  ⇒ 同一判决重复写是幂等（同 key 同字节），新版本/新策略/新判决是**新行**，历史只增不改；
- 与记忆同库，Slice C 读取不需要第二种连接或迁移；
- 运维需要跨账号查询时再镜像 Postgres —— 写入口只有 `PromotionLedger.append` 一处，
  决策对象不变。

**诚实边界**：BaseStore 无 CAS；多写者并发同键依赖"相同字节"这一性质。读页满
（`LedgerPage.complete=False`）时，调用方**不得**据此做去重——缺的那条可能正是重复记录，
所以 observe 通道会直接拒绝决定而不是猜。

### 7.2 `PromotionLedger`（`backend/memory/promotion_ledger.py`）

| API | 语义 |
|---|---|
| `append(account_id, candidate, decision, *, recorded_at=None)` | 写一行；返回 `RECORDED` / `NO_STORE`；store 抛异常则**原样抛**；`recorded_at` 由调用方注入（测试确定性/回填） |
| `records(account_id, *, limit=200)` | 时间倒序一页；`available=False` 表示没配 store（配置事实），`complete=False` 表示可能还有更多 |
| `current_entries(records)` | 从 supersede 边**推导**当前记录：promote ∧ 未被任何记录取代；同键两条 current → 抛（协议只会 supersede，不会分叉） |
| `promotion_id_for(decision, *, source_version)` | 确定性 id；`source_version` 是必要输入，否则 supersede 会覆盖它取代的版本记录 |

`PromotionRecord` 的 15 个字段（含 `supersedes`、`recorded_at`、`body` 快照）原样存取；
`from_dict` 对缺核心字段抛 `KeyError`，`detail`/`body` 对旧行可缺省为空 —— 账本是**记录**，
不是 best-effort 遥测，读不懂的行要炸出来。

### 7.3 observe-only 通道（`backend/memory/promotion_observations.py`）

第一个真实候选源：Creative Memory 的 **style** 行（走既有
`CreativeMemoryObservationSource`，不碰 `recall_style` 的冷启动伪造行）。

- `candidate_from_observation`：`strategy_notes` / key `style:<source_id>` /
  `INTERNAL_FACT` / `source_ref=creative-memory://style/<id>` /
  `evidence_ids=(ev_style_<id>,)` / `sample_count`、`measured_rate` 原样带上；
  **只有 style 在范围内**（plays/materials 的目标命名空间未裁决）；缺时间戳的行**抛**，
  不静默跳过（它无法被版本化，判 `source_unversioned` 会对着一个谎话判）。
- `observe_style_promotions(ledger, account_id, observations)`：读当前账本 → 逐个判决 →
  每个判决都 `append`（observe-only：**不写**目标命名空间）；同一 pass 内若同键出现更新
  版本，把刚晋升的记录折回 `existing`，于是第二条判 `SUPERSEDES_OLDER` 而不是分叉。
- 返回 `ObservationPass(promotions, ledger_available, recorded)`：`ledger_available=False`
  时决定照做、`recorded=0`——"没配库"不等于"没做决定"，两者必须分开呈现。

### 7.4 管理面与真实调用者（Slice B2）

**只读管理面** `GET /api/creator-agent/memory-promotions?account_id=…&limit=…`：

- 鉴权与同目录的 evidence-proposals 一致：`require_owned_account(user, account_id)`；
- 返回 `{account_id, available, complete, records[]}`；`records` 是账本行的原样 dict
  （`PromotionRecord.to_dict`），时间倒序；
- **列表只读是结构事实**：`/memory-promotions` 路由方法集合只有 GET（无 PATCH/DELETE）；
  人审写入走同资源下的 `POST .../{promotion_id}/review`（票 5y，见 §9.1）；
- 没配 store 时 `available=false`，不是"没有决定过"。

**真实调用者** `scripts/observe_memory_promotions.py`：

```bash
python scripts/observe_memory_promotions.py --account-id acc-1            # 记账一次
python scripts/observe_memory_promotions.py --account-id acc-1 --dry-run  # 只决定不写
```

- 它读 Creative Memory style 行（`CreativeMemoryObservationSource`）→ `observe_style_promotions`
  → 把每个判决写进账本；**不写**目标命名空间（晋升仍是 Slice C）。
- **必须有持久化 store**：没有 `XHS_POSTGRES_URI`/`POSTGRES_URI` 时直接退出码 2，
  不退回内存 store —— 记录随进程消失与"什么都没决定"无法区分。
- `--dry-run` 仍然**读**账本（不读当前记录的判决会是不一样的判决），但零写入、`recorded=0`。
- 输出是 JSON 摘要（`scanned` / `style_candidates` / `ledger_available` / `recorded` /
  `scan_saturated` / `decisions[]`），便于 cron/人工核对；调度本身属于部署配置。

## 8. 第一次晋升：独立重读 → 先记账 → 再写入（Slice C，票 5u）

这一节是管道**第一次改变 prompt 可召回内容**的地方。三条纪律缺一不可：

1. **验证不能自证**：`promotion_source.py::CreativeMemoryPromotionSource` 按
   `style_id` 重读 durable 行（`db.creative_memory.get_style`），`present/version` 由
   重读决定。扫描说 v1、行已到 v2 → 判决 `REVIEW(source_stale)`，不晋升。reader 抛异常
   原样上抛；行没有 `last_used` 抛错（无法版本化就不能判）。
2. **先记账、后写入**：`promotion_apply.py` 对 `PROMOTE` 先 `ledger.append` 再
   `write_promoted_memory`。两步之间崩溃 → 账本有 promote 行、目标缺失 = **pending**，
   绝不反向（先写后记会留下无法归因的记忆）。`REFUSE/REVIEW` 只记账、不写。
3. **写入值自带 provenance**：写入 `accounts/<id>/strategy_notes` 的 value 是
   `{note, promotion_id, source_ref, source_version, verified, trust_class, ttl_seconds,
   promoted_at, policy_version, decided_by}`，key 用 candidate 的确定性 key
   （supersede 替换同一行，不堆积近副本）。

**检索侧透传**（`context/retrieval.py::item_to_context_item`，票 5u）：值里带
`trust_class` / `verified` / `ttl_seconds` / `source_version` 时原样进 `ContextItem`；
`trust_class` 只接受发布词表里的拼写（未知拼写回落命名空间默认，不升级也不降级）；
`verified` 只认真正的 `True`；负 TTL / 非整数 TTL 视为没有。这是 P1-A 的字段第一次
有生产者 —— 之前它们只是渲染侧标签。

**CLI**：`--apply` 才走晋升（默认 observe-only）。`--apply --dry-run` 互斥（退出码 2）；
`--apply` 同样要求 Postgres store。

## 9. hy-memory 候选：REVIEW 接入（Slice D，票 5v）

行 7 的原始动机（SDK 抽取的记忆从未经过任何闸门）到这里才真正接上。设计原则是
**接进同一协议，机器侧不给写路径**（人审写路径见 §9.1）：

- `promotion_hy.py::batch_from_retrieval` 接受 `recall_hy_memory` 的三种 mode：
  `HIT` → 行；`EMPTY` → 健康空读；`DEGRADED` → 必须带错误摘要（`HyMemoryBatch` 双向校验：
  降级必须带 error，健康必须不带）。
- `batch_from_bridge` 走管理 API `list_memories` 读**原始行**（不是语义命中），
  `last_error` 只在"读回空且确有错误"时算降级；成功读到行时不因旧错误误判。
- 行 → candidate：`trust_class` 固定 `MEMORY`（协议因此只能给
  `REVIEW(needs_human_review)`，调用方无法改成可机晋升）；`source_ref` 优先 metadata，
  其次 `memory_id`，最后**内容寻址**；版本优先 metadata，否则内容哈希。
- **降级批次 → 一条 `REFUSE(source_degraded)` 账本记录**（key 由 scene+error 派生，
  幂等；错误摘要写进 `PromotionRecord.detail`）——"读不到"绝不渲染成"没有候选"。
- **永不机晋升护栏**：若策略错误地把 `MEMORY` 列入 `machine_promotable_classes`，
  `observe_hy_candidates` 抛 `RuntimeError`，不写账本 —— 未验证来源的机器写入无法归因。

**诚实边界（写进代码注释与 §10）**：

1. SDK 没有可信的重读 API：search 故障会被吞成空结果，`last_error` 只覆盖 client 构建/
   调用异常。所以 hy 行的版本是**文本版本**（内容哈希），不是行版本；机器侧 `REVIEW`
   仍是终点（不能靠再跑 `decide_promotion` “变”成 PROMOTE）。
2. ~~没有审批写路径~~ → **已由票 5y 补上**（§9.1）：人审通过后才能写入；机侧 observe
   仍只产 REVIEW/REFUSE。

调用者：`scripts/observe_hy_promotions.py`（`--account-id` / `--scene` / `--limit` /
`--dry-run`；要求 Postgres store 且 `HYMEMORY_ENABLED=true`）。默认不接进 agent 流程 ——
D 只产 REVIEW，接线无收益且有成本。

### 9.1 人审写入面（票 5y / PRD §9 Q1）

**入口**：`POST /api/creator-agent/memory-promotions/{promotion_id}/review`  
body：`account_id` + `disposition`（`approved` \| `dismissed`，复用
`CreatorReviewDisposition`）+ 可选 `review_note`。鉴权同 GET：`require_owned_account`。

**契约**：

| disposition | 账本 | 目标 ns |
|---|---|---|
| `approved` | 先 append 人审 `PROMOTE`（`decided_by=human`，`reason=human_approved`） | 同请求内 `write_promoted_memory`（顺序同 Slice C） |
| `dismissed` | append 人审 `REFUSE`（`reason=human_dismissed`） | **不写** |

- **不**再调用 `decide_promotion`：hy 的 `MEMORY` 永远机判 REVIEW；人审通过是
  **human-authored** 后续账本行，不是协议翻转。
- 旧 REVIEW 行**永不 mutate**；新行有新 `promotion_id`（id 含 disposition/reason）。
- 新行 `detail` 为 JSON：`{"reviewed_promotion_id": "<原 REVIEW id>", "review_note": "..."}`；
  `supersedes` 含原 REVIEW id（审计关联；`current_entries` 只看 promote 边，不受影响）。
- 已有 human 关闭行 → **409**（`CreatorMemoryPromotionConflictError`）；缺失/跨账户 →
  **404**；无 store → **503**（`available=false` 对称，不得成功 envelope）。
- 候选 body：`creative-memory://style/<id>` 优先独立重读 durable 行；hy 等无可信重读
  的来源用账本行在 observe 时快照的 `body`（`PromotionRecord.body`）。两者都缺 →
  400（不写空记忆）。`dismissed` 不依赖 body 重读。

实现：`backend/memory/promotion_review.py`；路由在 `creator_agent.py`。

## 10. TTL 默认（票 5z / PRD §9 Q2）与协议边界

**裁决**：全部目标命名空间默认 `ttl_seconds=null`（永不过期，只靠 supersede）。
不为 `strategy_notes` / `audience_preferences` / `performance_insights` /
`content_history` 发明未校准的天数；plays / materials 仍不进常量表，解析未知 ns →
`None`（不抛）。

| 职责 | 位置 |
|---|---|
| 常量表 + `resolve_promotion_ttl(namespace)` | `backend/memory/promotion_ttl.py` |
| 过期判定 `ttl_expired_for(candidate, *, now, observed_at)` | 同上；`ttl_seconds is None` ⇒ 恒 `False` |
| 候选填 TTL | `candidate_from_observation` / hy 候选构造经 `resolve_promotion_ttl` |
| `SourceCheck.ttl_expired` | 观测 / hy / apply 调用方用助手填；协议层仍不算时钟 |

将来若要给某 ns 设天数：只改 `PROMOTION_TTL_SECONDS` + 测试，不改 `decide_promotion`。
不做自动扫 stale / 删除 / 重晋升（仍在 out of scope）。

## 10.1 policy_version 来源（票 5aa / PRD §9 Q6）

**裁决**：`decided_by="machine"` 时，`policy_version` 的唯一权威来源是 Git 模块常量
`DEFAULT_PROMOTION_POLICY_VERSION`（当前值 `"v1"`），经 `default_promotion_policy()`
工厂出口。不引入 env / 远端配置——同二进制同版本，审计跟 commit。

| 职责 | 位置 |
|---|---|
| 常量 `DEFAULT_PROMOTION_POLICY_VERSION` | `backend/memory/promotion.py` |
| 工厂 `default_promotion_policy() -> PromotionPolicy` | 同上；`decide_promotion(..., policy=None)` 走工厂 |
| dataclass 默认 | `PromotionPolicy.policy_version` 引用同一常量（禁止散落字面量） |
| 人审行 | 仍复用原 REVIEW 行的 `policy_version`（票 5y；不重新发明） |

**Bump 规则**：改变会影响机判决的字段（`min_samples` /
`machine_promotable_classes` / `allowed_namespaces` 语义）时**必须** bump 常量；
仅文档/注释改动不 bump。将来改阈值：只改常量 + 测试 + 本段说明，不在调用方另写版本串。

## 10.2 样本阈值与冷却（票 5ab / PRD §9 Q4）

**裁决**：机晋升 `min_samples` **保持 5**，与 `CreativeMemory.MIN_SAMPLES` 对齐；
抽出单一出口 `DEFAULT_PROMOTION_MIN_SAMPLES`，由 `PromotionPolicy` 默认与
`default_promotion_policy()` 使用。MVP **不做**「最近 N 天」冷却窗口（无
`cooldown_days`、不扫 ledger 时间）——同键更新已由 dedupe / supersede 处理；
冷却另开票且需 `ExistingEntry` 携带 promote 时钟。

| 职责 | 位置 |
|---|---|
| 常量 `DEFAULT_PROMOTION_MIN_SAMPLES` | `backend/memory/promotion.py` |
| 工厂 / dataclass 默认 | `default_promotion_policy()` / `PromotionPolicy.min_samples` |
| 对齐护栏 | 单测断言 `== CreativeMemory.MIN_SAMPLES`（漂移即失败） |
| 改阈值 | **必须** bump `DEFAULT_PROMOTION_POLICY_VERSION`（票 5aa 规则） |

**不在本票**：`proposals._DRAFT_MIN_SAMPLES=3` 是草稿门槛，不是晋升闸门，不改。

## 10.3 语义近邻去重成本（票 5ac / PRD §9 Q3）

**裁决**：语义近邻**只作审核提示、永不自动合并**；embedding 成本**仅在**机判决
`dedupe == NEEDS_REVIEW` **之后**支付（post-decide）；store / semantic index 不可用或
`asearch` 抛错 → **skip-hint**（可在 `detail` 记 `status=unavailable`），**不**把
disposition 改成 REVIEW/REFUSE。

| 职责 | 位置 |
|---|---|
| `near_dupe_hint_for` / `merge_promotion_detail` / `detail_with_near_dupe_hint` | `backend/memory/promotion_semantic.py` |
| 接线 | `observe_style_promotions` / `promote_style_observations` / `observe_hy_candidates` 在 `ledger.append` 前合并 hint |
| 协议 | `decide_promotion` / `_dedupe` 仍只做键级；无 I/O |

**`detail` 编码**：hint 是 JSON 对象片段 `{"semantic_near_dupe": {...}}`。
空 `detail` → 直接写该对象；已有 JSON 对象（人审等）→ 浅合并同名键；已有**纯文本**
（hy 降级错误摘要）→ **不改写**（避免把错误串污染成半截 JSON）。

**不做**：对所有 `disposition=REVIEW`（含 hy `MEMORY`+`NEW`）一律跑 hint；自动合并；
把邻居喂回 `ExistingEntry`；缺 index 就拒绝机晋升。

## 11. 明确不在这里的东西

- **协议层不读任何存储**：来源行、证据、已有记录都由调用方读好再传；
- **协议不判语义重复**：键级去重是确定的；语义近邻由调用方在 post-decide 时写入
  账本 `detail` 作审核提示（票 5ac），永不自动合并，也不喂回 `decide_promotion`；
- **协议不算 TTL**：`SourceCheck.ttl_expired` 由调用方经 `promotion_ttl.ttl_expired_for`
  用真实时钟算好传入，本层保持纯函数（票 5z）；
- **无冷却窗口**：MVP 不扫「最近 N 天」（票 5ab）；冷却另开票；
- **只晋升 style 一族（机晋升）**：plays/materials 的目标命名空间未裁决（PRD §9），未接；
- **hy 候选机器侧只产 REVIEW**：没有可信重读就没有机晋升；人审写入见 §9.1；
- **不做独立审核 UI / 前端面板**：HTTP 面挂在既有 creator-agent 资源上；
- **不自动调度**：CLI 是真实调用者，但 cron/部署接线属于配置，不在代码里；
- **不做 pending 修复端点**：人审 approve 崩溃后「账本有行、目标缺失」仍按 Slice C
  pending 语义可读（票 5y out of scope）。

## 12. 下一片 / 已落清单

- ~~B2：`GET` 只读管理面 + 调度/CLI 调用者~~ **已落（票 5t）**；
- ~~Slice C：第一次 `internal_fact` 晋升 + retrieval 透传 provenance~~ **已落（票 5u）**；
- ~~Slice D：hy-memory 候选（REVIEW only，DEGRADED 批次整体 REFUSE）~~ **已落（票 5v）**；
- ~~Q1 人审入口 + 人审写入面~~ **已落（票 5y）**：`POST .../memory-promotions/{id}/review`；
- ~~Q2 TTL 默认值~~ **已落（票 5z）**：全 ns 默认 `null` + supersede-only；
  `promotion_ttl.py` 单一解析/判定入口；
- ~~Q6 `policy_version` 来源~~ **已落（票 5aa）**：`DEFAULT_PROMOTION_POLICY_VERSION` +
  `default_promotion_policy()`；审计跟 commit，无 env/远端；
- ~~Q4 machine-promote 样本阈值~~ **已落（票 5ab）**：`DEFAULT_PROMOTION_MIN_SAMPLES=5`
  对齐 `CreativeMemory.MIN_SAMPLES`；冷却 out of scope；
- ~~Q3 语义近邻去重成本~~ **已落（票 5ac）**：仅 `NEEDS_REVIEW` 后 hint；unavailable →
  skip-hint；`promotion_semantic.py`；
- 行 7 的四片 + 人审写入 + TTL / policy_version / 样本阈值 / 语义近邻 hint 全部落地；
  PRD §9 开放项已清空（账本存储 Q5 早已在 Slice B 裁决）。
