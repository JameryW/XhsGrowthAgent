# Memory Promotion 人审写入面（票 5y / PRD §9 Q1）

## Goal

给 Memory Promotion 的 `REVIEW` 行一条真实的人审写路径：人审通过后才能把候选写入目标记忆命名空间。今天「人审通过后才允许写入」只靠「没有写路径」保证（Slice D 诚实边界）；本票补上审批流本身。

## What I already know

* Slice A–D 已落（票 5r–5v）；`GET /creator-agent/memory-promotions` 只读账本
* `promotion_apply.py` 已有机晋升写路径：`PROMOTE` → ledger.append **先** → `write_promoted_memory` **后**
* hy-memory 候选固定 `trust_class=MEMORY` → 协议 `decide_promotion` **永远**给 `REVIEW`，人审通过不能靠再跑一遍协议“变”成 PROMOTE，必须是 **human-authored** 的后续账本行（`decided_by=human`）
* ADR-0002 语汇：`CreatorReviewDisposition` = `approved` / `dismissed`
* 约束：不新建第二套审核 UI；ledger 仍 append-only（不改旧 REVIEW 行）
* 学习信号人审面 `POST /learning-signals/{id}/review` 已有 404/409 冲突模式可对齐

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 审核入口 | **A** — `POST /creator-agent/memory-promotions/{promotion_id}/review`（与现有 GET 同资源；不挂 learning-signals / evidence-proposals） |
| `approved` 写路径 | **同请求一步**：append 人审 `PROMOTE`（`decided_by=human`）→ 同请求内 `write_promoted_memory`（顺序同 Slice C）。不做「只记账本 + 另调 apply」两步，避免人审通过后目标仍空、需第二次调用才能生效 |

## Decision (ADR-lite)

**Context**: Slice C 已规定机晋升「先账本、后目标」；人审通过后若只记账本，操作者仍需另调 apply，且 hy 候选无法再跑 `decide_promotion` 变 PROMOTE。  
**Decision**: 人审 `approved` 在同一 HTTP 请求内完成 ledger PROMOTE + target write；`dismissed` 只 append `REFUSE`。  
**Consequences**: 与 Slice C 崩溃语义一致（账本有行、目标缺失 = pending）；API 面更短；不引入独立 apply-from-review 端点。

## Requirements

1. `POST /api/creator-agent/memory-promotions/{promotion_id}/review`  
   body：`account_id` + `disposition`（`approved` \| `dismissed`，复用 `CreatorReviewDisposition`）+ 可选 `review_note`
2. 鉴权：`require_owned_account`；缺 store → 明确错误（与 GET `available=False` 对称，不得伪装成成功）
3. 目标行必须是账本中 `disposition=review` 且尚未被人审关闭的记录（按 `promotion_id` 定位）
4. `approved`：构造 **human-authored** `PromotionDecision`（`decided_by=human`，**不**再调用 `decide_promotion`）→ `ledger.append` **先** → `write_promoted_memory` **后**；候选字段从原 REVIEW 行 / 可重建的 candidate 来源取齐
5. `dismissed`：append human `REFUSE`（封闭 reason），不写目标 ns
6. 幂等 / 冲突：同一 REVIEW 已有后续 human 关闭行 → **409**（对齐 learning-signal conflict）；缺失 / 跨账户 → **404**
7. 旧 REVIEW 行永不 mutate；新行用新 `promotion_id`（id 含 disposition/reason）
8. `review_note` 与原 REVIEW 关联写入新行 `detail`（或等价字段）；关联原 `promotion_id` 可进 `detail` / supersedes 语义按实现选一种并测清
9. 更新 `docs/memory-promotion.md`：去掉「没有写路径」诚实边界，写清人审契约；§11 标记 Q1 已落

## Acceptance Criteria

* [ ] `POST .../memory-promotions/{id}/review` 对 OPEN 的 REVIEW + `approved` → 200；账本新增 `promote` 且 `decided_by=human`；目标 `strategy_notes` 有对应 key
* [ ] 同路径 `dismissed` → 200；账本新增 `refuse`；目标 ns **无**写入
* [ ] 对已关闭的 REVIEW 再审 → 409；对不存在 id → 404
* [ ] 无 store 时不得返回成功 envelope（显式错误 / available 对称）
* [ ] 路由方法集合含 GET+POST（不再断言仅 `{"GET"}`）
* [ ] 单元/API 测试覆盖上述路径；不依赖真实 Postgres
* [ ] `docs/memory-promotion.md` 人审节与诚实边界已改写

## Definition of Done

* 实现 + 测试 + lint/typecheck/CI green
* Docs 更新如上
* Trellis archive（实现合并后）

## Out of Scope

* 新建独立审核 UI / 前端面板
* TTL 默认值、语义近邻成本
* plays/materials 目标命名空间
* 自动调度 / cron
* 把人审结果喂回 Creator Model
* 独立的「apply pending human promote」修复端点（崩溃后 pending 仍按 Slice C 语义可读，本票不修）

## Technical Approach

* API：`backend/api/routes/creator_agent.py` 增 POST；请求模型对齐 `ReviewLearningSignalRequest` 的 disposition/note 形态（可不要求 model revision——晋升人审不改 Creator Model）
* 服务：新建 `promotion_review.py`（或扩展 `promotion_apply.py`）—— `review_promotion(ledger, store, account_id, promotion_id, disposition, note)`  
  - 读 ledger → 找 REVIEW → 查是否已有 human 关闭（同 candidate_id/key 上后续 human PROMOTE/REFUSE）→ 构造 human decision → append → 条件写目标
* 候选重建：从 REVIEW 行字段（namespace/key/source_ref/source_version）+ 必要时从 hy/style 源重读 body；body 缺失则 409/422 明确失败，不写空记忆
* 错误：domain 异常 → API 404/409，参照 `error-handling.md` learning-review 场景
* 测试：扩 `tests/unit/api/test_memory_promotions_route.py` + 新 `tests/unit/memory/test_promotion_review.py`

## Technical Notes

* 契约文档：`docs/memory-promotion.md` §7.4 / §8 / §9 / §10
* 父 PRD：`.trellis/tasks/archive/2026-10/10-21-memory-promotion-pipeline/prd.md` §9 Q1
* 对照实现：`promotion_apply.write_promoted_memory`、`LearningSignalReview` / `review_creator_learning_signal`
* Spec：`.trellis/spec/backend/error-handling.md`（learning review conflicts）、`directory-structure.md`、`quality-guidelines.md`
