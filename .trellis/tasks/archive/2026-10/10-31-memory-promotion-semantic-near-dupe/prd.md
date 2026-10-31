# Memory Promotion 语义近邻去重成本（票 5ac / PRD §9 Q3）

## Goal

关闭 PRD §9 Q3：语义近邻只作审核提示、永不自动合并；定何时付 embedding 成本、index 不可用时怎么办，并落地最小可测接线。

## What I already know

* 父 PRD / 协议：`decide_promotion` 只做键级去重；语义近邻是 reviewer hint，不进纯函数
* Store index 可选：`get_store_index()` 可返回 `None`；无 index 时 `asearch` 退化为 recency
* Ledger `detail` 已是操作者上下文挂载点（hy degraded / 人审 JSON）
* Research：`research/semantic-near-dupe-cost.md` — 推荐 A + C 附着点；unavailable → skip-hint

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 何时跑 embedding | **仅当**机判决 `dedupe == NEEDS_REVIEW` 之后（post-decide）；不在每次候选上跑（否决 B） |
| 附着点 | 写入账本 `detail` 的结构化 hint（不改 `disposition` / `reason` / `dedupe`） |
| Index / store 不可用或 `asearch` 抛错 | **skip-hint**（可记 `semantic_near_dupe:unavailable`）；**不**改 REVIEW/REFUSE/PROMOTE |
| 永不 | 自动合并；把邻居喂回 `ExistingEntry`；缺 index 就拒绝机晋升 |

## Requirements

1. 新助手（如 `promotion_semantic.py`）：`near_dupe_hint_for(...)` — 仅在 `dedupe==NEEDS_REVIEW` 时尝试 `asearch`；返回可写入 `detail` 的字符串/JSON 片段
2. 接线：`observe_style_promotions`（及同构 apply/hy observe append 路径）在 append 前合并 hint 进 `detail`
3. 单测：NEEDS_REVIEW + mock hits → detail 含 hint；无 store / asearch 失败 → 决策不变、hint 跳过；`decide_promotion` 仍无 I/O
4. Docs 关闭 Q3；§11「不判语义重复」改为「协议不判；调用方 post-decide hint」

## Acceptance Criteria

* [x] Q3 成文：仅 NEEDS_REVIEW 后付费；unavailable=skip-hint；永不自动合并
* [x] `decide_promotion` 保持纯函数（测试/静态约定）
* [x] observe 路径在 NEEDS_REVIEW 时可选写入 near-dupe detail
* [x] docs / agent-os 开放问题去掉 Q3（§9 开放项清空或仅余非阻塞备注）
* [x] 相关单测绿

## Out of Scope

* 对所有 `disposition=REVIEW`（含 hy MEMORY+NEW）一律做 hint（可后续加宽）
* 相似度阈值 / top-k 产品调参 UI
* 自动合并或改变 disposition

## Research References

* [`research/semantic-near-dupe-cost.md`](research/semantic-near-dupe-cost.md) — MVP = A with C-style detail enrichment; skip-hint when index unavailable

## Technical Notes

* `MemoryManager` / store `asearch`；`semantic_index_status`；ledger `detail`
