# 对账确认同步 publish_result（票 5am）

## Goal

`POST /publish-retry` 在对账确认已发布（gate `status=reconciled`）时，除 5ai 写 EffectLedger `CONFIRMED` 外，还要把 checkpoint 里的 `publish_result` 从 `unknown` 同步成 `published`（带 evidence/post_id），避免状态 API / UI 仍显示「结果不明」而账本已确认。

## What I already know

* `_wf_actions`：reconciled 早退只 `return success(...gate)`，**不** `aupdate_state`
* force 路径才会 `aupdate_state`（force_publish）
* 5ai/5ak/5al 已确认账本；本票补 **工作流可见状态** 同形

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 何时写 | gate 判定 `reconciled`（对账确认 published）时 |
| 写入字段 | `publish_result`: `status=published`，保留/合并原字段；写入 `post_id`（evidence 有则用）、`reconcile_evidence`、`result_known=True` |
| uncertain / requires_force | **不**改 publish_result |
| 写失败 | best-effort warn；仍返回 gate（与 ledger 写失败同族） |
| as_node | 复用现有 `_get_as_node(state)` |

## Requirements

1. `_wf_actions` reconciled 早退前 `aupdate_state` 同步 publish_result
2. 单测：reconciled 路径断言 `aupdate_state` 被调用且 status published；requires_force 不写
3. docs 一句注记（agent-os §5.1）

## Acceptance Criteria

* [x] reconciled → checkpoint publish_result.status=published
* [x] requires_force / 非 unknown 路径不误写
* [x] update 失败不阻断 API 成功返回
* [x] 测试绿

## Out of Scope

* CDP 详情深查
* 改 gate 纯函数 `evaluate_unknown_publish_retry`
* 前端文案

## Technical Notes

* `backend/api/routes/_wf_actions.py`；`tests/unit/api/test_publish_retry.py`
