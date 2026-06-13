# fix: analytics posts-published count includes mock and failed

## Goal

修复数据分析页面"发布数"指标不准确的问题：dry_run 的 mock 发布和失败的发布被错误计入发布数。

## Root Cause

`_extract_post_data()` (backend/api/routes/analytics.py:89) 的过滤条件只检查 `title or analytics`，不验证 `publish_result.status`。导致：
1. `dry_run=True` 的 mock 发布（`post_id: "mock_..."`, `status: "mock_published"`）被计入
2. 发布失败（`status: "failed"`）也被计入（如果有 title）

前端 `Analytics.vue` 第 32 行用 `analyticsStore.posts.length` 显示发布数，无过滤。

## Requirements

* `_extract_post_data()` 跳过 `status` 为 `"mock_published"` 或 `"failed"` 的记录
* 或等效方案：在 `get_performance()` 返回结果中标记 post 类型，前端过滤

## Acceptance Criteria

* [ ] mock 发布（dry_run）不计入发布数
* [ ] 失败发布不计入发布数
* [ ] 真实成功发布正常显示
* [ ] 现有 analytics 相关测试通过

## Technical Notes

* `_extract_post_data()` 位于 `backend/api/routes/analytics.py:89`
* publisher mock 发布标记：`post_id: "mock_..."`, `status: "mock_published"`
* publisher 失败标记：`status: "failed"`, `error_type` 字段
