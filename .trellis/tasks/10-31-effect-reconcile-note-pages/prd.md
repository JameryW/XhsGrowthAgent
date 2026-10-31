# Effect 对账笔记列表多页（票 5al）

## Goal

票 5ak 只拉创作者中心笔记列表 **第 1 页**。本票把默认 fetcher 扩到最多 **N 页**（锁定 N=3），命中仍精确标题匹配 + 5ai 确认账本。缓解「刚发的笔记不在首页」假 uncertain，仍不做 CDP/详情页。

## What I already know

* `_default_fetch_platform_notes` 现只 `fetch_note_list(page_num=1, page_size=50)`
* `CreatorStatsClient.fetch_all` 已有多页循环可参考；本票只扩对账默认 fetcher
* 可注入 `platform_note_fetcher` 仍返回扁平 list（测试不受影响）

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| max_pages | **3**（常量；文档化） |
| page_size | 50（与 5ak 同） |
| 提前停 | 某页 `extract_note_items` 为空，或 len(items) < page_size |
| 匹配 | 不变：精确 strip title；需非空 note id |
| 失败 | 任一页抛错 → 整次平台刀 uncertain（warn），与 5ak 一致 |
| CDP/详情 | 仍 out of scope |

## Requirements

1. `_default_fetch_platform_notes` 循环 page 1..3，合并 items
2. 单测：mock client/transport 或 patch `fetch_note_list` 证多页被调用；第 2 页命中也能 confirm（可经注入 fetcher 返回多页合成 list，或 patch 默认实现）
3. docs agent-os：5al 多页；详情/CDP 仍后续

## Acceptance Criteria

* [x] 默认 fetcher 最多拉 3 页并提前停
* [x] 非首页标题命中仍可 published + CONFIRMED
* [x] 拉页失败仍 uncertain，不伪确认
* [x] 测试绿；docs 更新

## Out of Scope

* CDP / 笔记详情 API
* 模糊匹配 / max_pages 配置化 env

## Technical Notes

* `backend/agents/publisher.py` `_default_fetch_platform_notes`
* `tests/unit/agents/test_run_publish.py`
