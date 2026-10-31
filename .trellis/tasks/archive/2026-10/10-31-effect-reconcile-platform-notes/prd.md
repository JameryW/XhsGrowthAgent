# Effect 对账平台笔记列表（票 5ak）

## Goal

agent-os 行 5「平台查询对账」第一刀：`reconcile_unknown_publish` 在本地幂等/ContentHistory 均 uncertain 后，用创作者中心 **笔记列表第 1 页** 按标题精确匹配；命中则与 5ai 一样确认账本 `CONFIRMED`。查不到 / 无凭据 / 拉列表失败 → 仍 `uncertain`（绝不伪确认）。

## What I already know

* 5ai 已：本地确认 → `UNKNOWN→RECONCILING→CONFIRMED`；uncertain 不动账本
* `CreatorStatsClient.fetch_note_list` + `extract_note_items` / title 字段别名已有
* Cookie 经 `load_credential`；CDP 路径更重——本票默认 **cookie httpx**，无 cookie 则跳过平台刀
* Engagement 已有 DOM 读回；publish 尚无平台面

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 何时查平台 | 仅本地两路都未确认 **且** title 非空 |
| 匹配 | 标题 **精确** strip 相等；取列表第 1 页（page_size≤50） |
| 命中 | `status=published` + evidence `source=platform_note_list` + note id；走现有 ledger confirm helper |
| 无 cookie / fetch 失败 / 无命中 | `uncertain`（warn）；**不** raise 阻断 retry gate |
| 注入点 | 可选 `platform_note_fetcher` 参数（测试）；默认实现封装 client |
| CDP | out of scope（本票不强制开浏览器） |

## Requirements

1. 扩展 `reconcile_unknown_publish`：本地 uncertain 后尝试平台列表匹配
2. 默认 fetcher：`load_credential` → `CreatorStatsClient(cookie=)` → `fetch_note_list` → extract titles/ids
3. 单测：mock fetcher 命中 → published + ledger CONFIRMED；fetcher 抛错/空 → uncertain；无 title 不调用
4. agent-os 行 5 更新：平台列表对账已落；详情页深查仍可后续

## Acceptance Criteria

* [x] 平台标题命中 → published + ledger CONFIRMED
* [x] 无凭据 / 失败 / 未命中 → uncertain，不伪确认
* [x] 本地已确认时不调用平台
* [x] 测试绿；docs 更新

## Out of Scope

* CDP / 笔记详情页深查
* 模糊标题匹配
* Engagement ledger

## Technical Notes

* `backend/agents/publisher.py`；复用 `_confirm_ledger_after_reconcile`
* `backend/services/creator_stats/{client,normalize}.py` 只读复用
* `tests/unit/agents/test_run_publish.py`
