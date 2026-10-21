# Memory Promotion Pipeline（设计 PRD）

> 状态：**Slice A + Slice B（B1 库 / B2 接线）已落**（票 5r：决策协议；票 5s：append-only
> ledger + Creative Memory style 观测的 observe-only 通道；票 5t：只读管理面 + 真实
> 调用者 CLI）。Slice C/D 未实现，按 §6 另开任务，每片单独 PR。
>
> 依据：`docs/agent-os-upgrade-2026q4.md` §3 差距矩阵第 7 行 ——
> 「hy-memory 有 LLM 抽取 + reconciler，无『来源验证→去重→晋升』显式流水线」❌ 缺（P1/P2）。
>
> 侦察记录（每条判断的出处）：`research/2026-10-21-recon.md`
> 实现记录与词表修正：`docs/memory-promotion.md`、本文件 §12 / §13 / §14

## 1. Goal

让「一条记忆从候选变成可信事实、并进入 prompt」成为一个**显式、可审计、可复算**的决定，
而不是某个 SDK 内部 reconciler 或某次 `store.aput` 的副作用：

1. **来源验证**：候选必须能指回一条真实、可读的源（行/证据/工件），验证是*实际做过的检查*，
   不是"看起来像"；
2. **去重/取代**：同一 `(namespace, key)` 只保留一个"当前"，旧记录不删（append-only），
   语义近邻只作为**审核提示**，永不自动合并；
3. **晋升**：只有通过验证的候选才允许写入喂 prompt 的命名空间，且每条晋升留下
   append-only 决定记录（谁、凭什么证据、源版本、TTL）。

**成功的样子**：给定同一批候选与同一份已存记录，`decide()` 的输出逐字节一致；任何一条
无法验证来源的记忆都不可能出现在 prompt 里；回答"这条记忆为什么在 prompt 里"时，能从一个
promotion_id 走到证据 id 与源版本。

## 2. 现状（每条都有代码出处）

| 层 | 今天有什么 | 缺什么 |
|---|---|---|
| hy-memory（外部引擎，默认关） | `remember` / `recall` / `last_error`；pro 模式在 SDK 内做 LLM 抽取与冲突调和（reconciler 对仓库不透明）；降级经 `recall_hy_memory` 的 `DEGRADED` 可见 | 仓库**没有**任何"这条 SDK 抽取的记忆可否被信任"的判断；候选的 `source_ref` 只是 metadata 里的一段字符串，没人验证 |
| `MemoryManager`（4 个命名空间） | 4 个写入方法全部 `store.aput(key=uuid4(), value=...)`，只追加、不看已有 | 没有 verify、没有 dedupe、没有 supersede、没有 provenance 字段 |
| Creative Memory（measured rows） | 行级实测（`engagement_rate` / `sample_count` / `proven_count` / `source_post_id`）；`deposit_style` 按 tone+visual 精确匹配合并并加权平均；`calibrate` 用实际结果回写 | 合并发生在**写入侧**且吞异常；没有"这条实测证据是否够格变成策略结论"的闸门；没有决定记录 |
| Creator Agent（审查/学习） | ADR-0002 先审后学；`proposals.py` 把实测观测投影成确定性 `evidence_id`/`proposal_id` 的只读提案（Laplacian 置信度、按 `source_ref` 去重、草稿偏好有阈值）；`ModelRevision` append-only；`GET /model/evidence-proposals` + `POST /learning-signals/{id}/review` | 这条审查路径服务的是 **Creator Model**，不是 memory；没有任何东西把"证据 → 记忆"的晋升决策记下来 |
| Context Compiler | `TrustClass`（`internal_fact` / `memory` / `external_document` / `model_generated` / `unspecified`）、`verified`、`ttl_seconds`、`source_version` 已存在并可选渲染；检索器把 content_history 映射为 `internal_fact`、其余三个命名空间为 `memory` | 这些字段是**渲染用的标签**，没有生产者做"验证"；trust 也还没参与 rerank（那是另一件事，见 §8） |

**为什么现在不做会继续坏**：hy-memory 一旦启用 pro 模式，SDK 的 reconciler 会替我们决定
"哪条记忆覆盖哪条"，而这个决定不在仓库的可审计范围内；`MemoryManager` 的 UUID 追加会让
同一结论以多条并存形式进入 prompt，且没有任何字段能回答"它凭什么可信"。

## 3. Decision（ADR-lite）

| Topic | Decision | 理由 |
|---|---|---|
| 管道归属 | **仓库自有 gate**，SDK 抽取只是候选来源 | reconciler 不透明，晋升决定必须能从仓库数据复算；否则审计只能问 SDK |
| 三段结构 | verify → dedupe → promote，每段一个纯函数、一个封闭 reason 集；一个候选一条决定记录 | 与仓内「失败不是数据 / 封闭词表」纪律一致；可单测、可突变 |
| 自动晋升资格 | 只有 `trust_class=internal_fact`（实测行：content_history / creative_memory 行、且 `source_ref` 可解析）能 **machine-promote**；`memory` / `model_generated` / `external_document` 一律 `REVIEW`（人审，复用 ADR-0002 的 disposition 语汇） | 实测行是仓库自己写的；LLM 抽取与人写观点都不能自证为规范 |
| 写入形状 | append-only：`promotion` 决定记录 + 目标命名空间"当前记录"携带 `promotion_id` / `verified` / `source_version` / `ttl_seconds`；旧记录保留并以 `superseded_by` 指向新 id。**解释性记忆不做 in-place 覆盖** | 与 ADR-0005（revision append-only）、ADR-0003（证据是读投影）同方向；删除要审计 |
| 去重顺序 | ① `(namespace, key)` 精确 → ② `source_ref` 精确 → ③ 语义近邻**仅提示**（`NEEDS_REVIEW`，不自动合并） | 键级去重确定、可复算；语义合并会把两条不同主张揉成一条，且依赖 embedding 可用性 |
| 失败语义 | 验证读取失败 → **抛**（沿用票 5m 的「失败即抛」）；可信度不足 → `REFUSE` + 封闭 reason；判断不了 → `REVIEW`（不是 promote，也不是 skip） | 「读不到 ≠ 不存在」；没有第三种"静默跳过" |
| 降级不晋升 | hy-memory 处于 `DEGRADED` / `last_error` 非空的一批候选整体 `REFUSE(source_degraded)`；`REFUSE` 也写决定记录 | 降级是事实；但它不是候选的过错，也不是"没有候选" |
| 过期 | 每条 promotion 带 `ttl_seconds`；过期只**标记 stale**、不自动删除、不自动重晋升 | 删除需要审计；重晋升要走同一闸门 |
| 审核入口 | 复用现有 `evidence-proposal` / `learning-signal` 面，不新建第二套审核 UI | 仓内已有一个审核工作流，第二套会漂移 |
| 观察先于生效 | Slice A/B 只读 + 只记账（observe-only），**任何 prompt 输出必须逐字节不变**；Slice C 才允许第一次写入 prompt-bearing 命名空间，且只限 `internal_fact` | 与 P0-A / P1-A 的观察层先例一致；先让决定可见，再让它生效 |

## 4. 数据形状（implementer 可以照着写）

```text
PromotionCandidate(frozen)
  candidate_id: str            # 确定性：sha256(namespace|source_ref)[:16]
  namespace: str               # 目标命名空间（4 个注册命名空间之一）
  key: str                     # 目标当前记录的键（不是 uuid4 —— 要去重）
  body: str                    # 将要进入 prompt 的文本（不含任何指令性前缀）
  trust_class: TrustClass      # 复用 backend.context.models
  source_ref: str              # 可解析：content_history://<post_id> / creative-memory://<kind>/<id> / hy://<memory_id>
  source_version: str          # 源的行版本/时间戳（用于 stale 判定）
  observed_at: str             # ISO-8601
  evidence_ids: tuple[str,...] # 已有证据（必须逐个可查）
  sample_count: int            # 实测样本；非实测来源为 0
  measured_rate: float | None  # 实测率；非实测来源 None
  ttl_seconds: int | None

PromotionDecision(frozen)
  candidate_id: str
  disposition: PromotionDisposition   # PROMOTE | REVIEW | REFUSE
  reason: PromotionReason             # 封闭枚举，见下
  dedupe: DedupeVerdict               # NEW | SUPERSEDES | DUPLICATE | NEEDS_REVIEW
  supersedes: tuple[str, ...]         # 被取代的 promotion_id（append-only，不删除）
  verified: bool
  decided_by: str                     # "machine" | "creator:<user_id>" | "policy:<version>"
  policy_version: str
```

**封闭 `PromotionReason`（初稿，实现时由测试穷举）**：
`source_missing` / `source_unreadable` / `source_degraded` / `source_untrusted_class` /
`evidence_missing` / `insufficient_samples` / `duplicate` / `supersedes_older` /
`needs_human_review` / `policy_blocked` / `ttl_expired`.

**禁止的形状**：`{"error": ...}` 当返回值、`except: continue`、用 `False` 表示"不知道"、
在 body 里塞指令性文本（body 只放content，不解释自己的可信度）。

## 5. 管道语义（逐段，含边界）

### 5.1 verify
- 输入候选 + 一个**窄 reader 协议**（`PromotionSourceReader`，由 `backend/memory` 侧实现，
  `creator_agent`/`context` 不 import 具体 DB 模块 —— 方向同 ADR-0006）。
- 校验：`source_ref` 前缀合法 ∧ reader 能读到行 ∧ `evidence_ids` 逐个可查 ∧
  `source_version` 与行当前版本一致（不一致 → `source_stale`，留 review，不 promote）。
- reader 抛异常 → **原样上抛**，不转成 `REFUSE`；`REFUSE` 只表示"读到了，且不够格"。
- 明确不用 `recall_*` API 做验证：`CreativeMemory.recall_style` 有冷启动 `default_*` 伪造行
  （ADR-0006 记过这个坑），验证必须读原始行。

### 5.2 dedupe
- 在目标 namespace 的 key 集合上做键级判定（reader 提供 `existing_keys(namespace)`），
  语义 index 只用于给 `NEEDS_REVIEW` 附"疑似重复"提示，不改变 disposition。
- `SUPERSEDES` 必须满足：`source_version` 更新 ∧ 同 `source_ref` 家族；否则 `NEEDS_REVIEW`。

### 5.3 promote
- `PROMOTE` 才写目标命名空间；写之前必须已有 promotion 记录（先记账、后生效；两步之间
  崩溃 → 记录在、目标未变，读侧把"记录存在但目标缺失"当 `pending`，不猜测成功）。
- machine-promote 阈值（初稿，待产品确认）：`sample_count >= 5` ∧ `measured_rate` 有值 ∧
  `trust_class=internal_fact`。阈值与 `proposals.py` 的 Laplace prior / `_DRAFT_MIN_*`
  保持一致，避免两套"多少样本算数"。

## 6. 切片（按顺序，每片独立可交付）

- **Slice A — 纯协议（observe-only）**
  `backend/memory/promotion.py`：上述 dataclass、枚举、`decide_promotion(candidate, *,
  source, existing, policy)` 纯函数；无 I/O、无全局状态、确定性。测试：每个 reason 至少
  一条；同输入两跑逐字节一致；非 machine-promotable 类 → `REVIEW`；`internal_fact` 但无
  `source_version` → `REFUSE`。
  验收：`tests/` 全绿且 **context baseline 漂移 0**（本片不产生任何 prompt 文本）。
  **已落（票 5r）**：实现形态见 §12 与 `docs/memory-promotion.md`。
- **Slice B — ledger + 真候选（observe-only）**
  append-only promotion 记录（`accounts/{account}/memory_promotions`，§9 Q5 已裁决）+
  reader + `GET` 管理面（只读）；接一个真实候选源（Creative Memory observations）
  **只记账、不写同命名空间**。验收：prompt 输出逐字节不变；账本无 update/delete API。
  **B1 已落（票 5s）**：ledger（`promotion_ledger.py`）+ Creative Memory **style** 观测的
  observe-only 通道（`promotion_observations.py`）；
  **B2 已落（票 5t）**：只读管理面 `GET /api/creator-agent/memory-promotions` + 真实调用者
  `scripts/observe_memory_promotions.py`（`--dry-run` 只读账本零写入；无持久化 store 明确
  退出，不退回内存）。实现形态见 §13 / §14 与 `docs/memory-promotion.md` §7。Slice B 完成。
- **Slice C — 第一次晋升（`internal_fact` only）**
  把通过 §5.1/§5.2 的 measured 观测晋升进 `strategy_notes`（只这一个命名空间）；同时让
  `context.retrieval.item_to_context_item` **透传** `verified` / `source_version` / `ttl_seconds`
  （今天只映射 timestamp 与 trust_class），使被晋升的记录在 provenance 标签上可见。
  验收：任何未验证候选无法到达 prompt（突变自检）；重复候选第二次跑 → `DUPLICATE` 不新增。
- **Slice D — hy-memory 候选（REVIEW-only 起步）**
  SDK 抽取的记忆以 metadata 里的 `source_ref` 进入同一闸门；`DEGRADED` 批次整体
  `REFUSE(source_degraded)`；初期**只产 `REVIEW`**，人审通过后才允许任何写入。
  验收：`last_error` 非空时零晋升；人审 disposition 与 ADR-0002 语汇一致。

## 7. Acceptance Criteria（全局）

* [ ] `promotion.py` 无任何 `except ...: pass/continue`（由既有 fallback 登记扫描覆盖）；
      reader 失败原样上抛，`REFUSE` 只承载"读到但不够格"。
* [ ] `PromotionReason` / `PromotionDisposition` 由测试穷举（新增成员必须同时新增用例）。
* [ ] 决定性：同一输入两次决策字节一致（含 `dedupe`、`supersedes` 排序）。
* [ ] 未验证 / 无证据 / 降级来源 **不可能** 产出 `PROMOTE`（每条一个突变用例）。
* [ ] append-only：账本没有 update/delete 路径；`superseded_by` 只增不改。
* [ ] 先记账后生效：两步之间崩溃时读侧判 `pending`，不把"没写成功"说成"已晋升"。
* [ ] Slice A/B 前后 **context baseline 零漂移**（`python scripts/benchmarks/context_compiler_baseline.py --compare`）。
* [ ] 文档：新增 `docs/memory-promotion.md`（管道/词表/失败语义/边界），
      `docs/agent-os-upgrade-2026q4.md` 第 7 行从 ❌ 改为「Slice X 已落（PR #…）」；
      若新增 claim 值，必须进 claim-table 并由脚本重算。
* [ ] 突变自检：每片至少覆盖"删掉验证 → promote"、"把未知当 False → REFUSE"、
      "跳过去重 → 重复晋升"三类；判定必须是断言红，不是崩溃红。

## 8. Non-goals

- 不重写 hy-memory SDK 的 reconciler，也不给它新增写入路径；
- 不改 Creator Model / `ModelRevision` 流程（ADR-0002/0005 已覆盖）；
- 不做跨账号或群体级晋升（账号隔离与隐私边界优先）；
- 不做自动删除/过期清理（只标记 stale，删除另开任务并带审计）；
- 不新建第二套审核 UI/流程（复用 evidence-proposal / learning-signal 面）；
- 不把 trust 接进 rerank（P1-A 留的后续项，与本管道独立）；
- 不顺手改 `deposit_*` 的 best-effort 吞异常（邻近风险，见 §10，另开票）。

## 9. Open questions（实现前需要产品/架构裁决）

1. **审核入口**：promotion 的 `REVIEW` 挂在 `GET /model/evidence-proposals` 旁，还是
   `learning-signals/{id}/review` 上？两者的 disposition 语汇不同。
2. **TTL 默认值**：策略笔记 / 受众偏好 / 洞察各自多久过期？还是全部 null（永不过期、
   只靠 supersede）？
3. **语义近邻去重的成本**：只在 `NEEDS_REVIEW` 时做（省一次 embedding）还是每次去重都做？
   语义 index 不可用时是 `REVIEW` 还是 `REFUSE`？
4. **machine-promote 阈值**：`sample_count >= 5` 是否够？要不要加"最近 N 天"冷却窗口？
5. **账本存储**：~~BaseStore namespace 还是 Postgres 表？~~ **已裁决（票 5s）：
   BaseStore namespace `accounts/<account>/memory_promotions`**。理由：记录不可变、id 由
   `(candidate_id, source_version, disposition, reason, policy_version)` 派生 ⇒ 同 key 写
   相同字节是幂等而非改写历史；与记忆同库，Slice C 读取不需要第二种连接/迁移；运维需要
   跨账号查询时再镜像到 Postgres —— 写入口只有 `PromotionLedger.append` 一处，决策对象不变。
   代价（诚实边界）：BaseStore 无 CAS，多写者并发同键依赖"字节相同"这一性质；读页满
   （`complete=False`）必须拒绝据此去重，已写进协议。
6. **谁算 `decided_by="machine"` 的责任人**：审计要能定位策略版本；`policy_version` 的
   来源（常量？配置文件？）需要定。

## 10. 邻近风险（本 PRD 明确不解决，但要登记）

- `CreativeMemory.deposit_*` 四个方法都是 `except Exception: logger.warning`（`creative.py:313`
  等）—— 写入失败不抛、调用方当成功。它与「失败不是数据」冲突，但改它会动现有写入面，
  应另开票（可纳入 `MEMORY_FALLBACKS` 的第五张表讨论）。
- hy-memory 的 `remember` 契约是"永不炸调用方 + 返回 None"（`docs/hy-memory.md` §1）——
  这是**外部增强层**的合理契约；本管道不依赖它做证明，但读取时要把 `last_error` 当事实。
- `MemoryManager` 写入 key 是 `uuid4()`，所以今天**无法按键去重**；Slice C 引入确定性 key
  （由 `candidate_id` 派生）会改变"同一结论可并存多条"的现状，需要迁移说明。

## 11. Definition of Done

- 每片：`tests/` 全绿；`ruff check` / `ruff format --check`；`mypy backend`（仅允许既有
  `backend/memory/creative.py:350`）；四道本地门（tool-runtime / context-baseline /
  harness / stealth）全绿；新增登记表必须空表并复算。
- 每片 PR 描述必须写「改了什么 / 证据数字（来自复算，不是估计）/ 没做什么」。
- Slice A 完成后，把本 PRD 的「状态」改为进行中并链接 PR；全部落地后把
  `agent-os-upgrade-2026q4.md` 第 7 行改成已满足，并把本任务归档。

## 12. Slice A 实现记录（票 5r）—— 与本节初稿的差异

实现时对 §4/§5 的初稿做了以下几处修正，理由都写在 `docs/memory-promotion.md`：

| 初稿 | 实现 | 理由 |
|---|---|---|
| `SOURCE_UNREADABLE` 拒因 | **移除** | reader 读失败 = 异常上抛；把它做成拒因会让"失败"与"拒绝"同形（违反本仓「失败不是数据」） |
| 未列 `SOURCE_UNVERSIONED` | 新增 | "没有版本"可判定（`candidate.source_version` 为空）→ REFUSE；来源 present 但无版本是**非法输入**（`ValueError`，由 `SourceCheck.__post_init__` 保证） |
| 未列 `SOURCE_STALE` 的两种用法 | 合并为一个拒因 | ①来源版本 ≠ 候选版本（REVIEW）；②候选比已存记录旧（REVIEW）。两者语义都是"不新鲜" |
| 未列 `POLICY_BLOCKED` | 新增 | policy 白名单是真实配置面；不设它 Slice C 的目标命名空间就只能靠调用方自律 |
| 未列 `VERIFIED_INTERNAL_FACT` / `SUPERSEDES_OLDER` | 新增 | 正向判决也需要封闭 reason，否则"为什么 promote"无法记账 |
| `dedupe` 只有 4 值 | 加 `NOT_EVALUATED` | "没去看"与"看了是新的"必须分开（ledger 不能把两者读成一件事） |
| `decide_promotion(candidate, *, existing, policy)` | `decide_promotion(candidate, *, source, existing, policy)` | verify 的事实必须显式传入；函数保持纯，不读存储 |

最终交付：`backend/memory/promotion.py`（12 个 reason 全可达、确定性、非法输入 ValueError、
无 except）、`tests/unit/memory/test_promotion.py`（42 条）、`docs/memory-promotion.md`。

## 13. Slice B1 实现记录（票 5s）

| 项 | 实现 | 与初稿/PRD 的差异 |
|---|---|---|
| ledger 存储 | `accounts/<account>/memory_promotions`（BaseStore） | Q5 裁决见 §9；未建 Postgres 表 |
| 记录形状 | `PromotionRecord`（14 字段，含 `supersedes` / `recorded_at`） | `recorded_at` 由调用方注入（测试确定性/回填），不是协议层的时钟 |
| id 派生 | `promo_` + sha256(`candidate_id | source_version | disposition | reason | policy_version`)[:16] | 初稿只说"确定性"；实现把 **source_version** 也纳入，否则 supersede 会覆盖旧版本记录（突变 M2 钉住） |
| 追加语义 | 同 id 覆盖相同字节 = 幂等；不同 id 只增不改；无 update/delete | — |
| 无 store | `LedgerAppendOutcome.NO_STORE` / `LedgerPage.available=False` | 不把"没配库"说成"记录了 0 条" |
| 读失败 | 原样抛（无 except） | 与「失败不是数据」一致 |
| 页满 | `LedgerPage.complete=False`；observe 通道**拒绝据此去重** | 初稿未写；不加这条会让"缺的那条正是重复记录"时静默分叉 |
| current 推导 | `current_entries` 从 supersede 边推导：promote 记录 ∧ 未被取代；同键两条 current → 抛 | 不存"当前"标志，append-only 历史是唯一事实 |
| 真候选 | Creative Memory **style** 观测（`promotion_observations.py`），复用 `creator_agent.proposals` 的 evidence id/claim/ref 推导 | plays/materials 的目标命名空间未裁决，Slice B 刻意只接 styles |
| 观察检查 | `source_check_from_observation`：本轮读到的行即来源（present/version/evidence） | **Slice C 必须换成独立重读**，否则"验证"就是拿扫描结果自证（文档已写明） |
| 未接线 | `GET` 管理面、调度/CLI 调用者 → **B2** | 本片不产生生产调用者，也不写目标命名空间 |

交付：`backend/memory/promotion_ledger.py`、`backend/memory/promotion_observations.py`、
`tests/unit/memory/test_promotion_ledger.py`（12）、`test_promotion_observations.py`（13）、
文档 `docs/memory-promotion.md` §7。prompt 输出零变化。
Slice A 不产生任何 prompt 文本，context baseline 零漂移。

## 14. Slice B2 实现记录（票 5t）

| 项 | 实现 | 取舍 |
|---|---|---|
| 管理面 | `GET /api/creator-agent/memory-promotions`（挂在既有 creator-agent router） | 复用同一鉴权/响应面；不在 `backend/memory` 里造 HTTP 依赖 |
| 响应 | `{account_id, available, complete, records[to_dict]}` | 两个事实分开：`available`（没配 store）与 `complete`（页满） |
| 只读 | 路由只有 GET；测试从 router 的方法集合断言 `{"GET"}` | "只读"是结构事实，不是约定 |
| 鉴权 | `require_owned_account(user, account_id)` 在账本读取之前 | 与 evidence-proposals 同一条作用域规则 |
| 调用者 | `scripts/observe_memory_promotions.py`：`--account-id` / `--window` / `--dry-run` | cron/调度属于部署配置，代码只提供可重复的 pass |
| 持久化要求 | 无 `XHS_POSTGRES_URI`/`POSTGRES_URI` → 退出码 2 | 不退回内存 store：记录随进程消失 ="什么都没决定" |
| dry-run | 仍读账本（当前记录影响判决），`record=False` 零写入、`recorded=0` | 为此给 `observe_style_promotions` 加了 `record: bool = True`（默认行为不变） |
| 测试 | 路由 6、CLI pass 8（含 dry-run / 无 store / saturated / 校验 / CLI 拒跑） | 校验用 outcome 断言，避免下游 store 的报错替本层背书 |

文档 `docs/memory-promotion.md` §7.4。prompt 输出仍零变化；Slice B 至此完成。
