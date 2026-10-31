# Effect 对账确认写入账本 CONFIRMED（票 5ai）

## Goal

agent-os 行 5「对账增强留 P1」的第一刀：`reconcile_unknown_publish` 在本地证据确认已发布时，必须把 `EffectLedger` 从 `UNKNOWN`（经 `RECONCILING`）写到 `CONFIRMED`。今天 API 可返回 `status=reconciled`，但账本仍停在 `UNKNOWN`，与「对账确认已存在」不同形。

## What I already know

* `reconcile_unknown_publish` 只查幂等行 + ContentHistory 标题匹配；确认则 `{"status":"published", evidence}`，否则 `uncertain`
* `_wf_actions` publish-retry：确认 → 早退 `reconciled`，**不**改账本
* `EffectLedger` 合法转移：`UNKNOWN → RECONCILING → CONFIRMED|FAILED|UNKNOWN`
* Engagement 侧已有读回 `reconcile_effect`（平台 DOM）；publish 仍无自动平台查询——**本票不做平台查询**
* `_write_publish_record` 已能 `mark(..., CONFIRMED)`（best-effort）

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| 确认已发布时 | `UNKNOWN → RECONCILING → CONFIRMED`（evidence 写入 extra） |
| uncertain | 可 `UNKNOWN → RECONCILING → UNKNOWN` 记一次尝试，或**不动账本**——**锁定：uncertain 不动账本**（避免无证据的抖动写） |
| 写失败 | 与现有 `_write_publish_record` 一致：**best-effort warn**，不阻断 gate 返回（telemetry/ledger 辅助；gate 证据仍以 reconcile 返回值为准） |
| 平台查询 | out of scope（后续刀） |

## Requirements

1. `reconcile_unknown_publish`（或紧邻 helper）：本地确认 published 后 mark RECONCILING → CONFIRMED
2. 单测：确认路径后 ledger `get` 为 CONFIRMED；uncertain 后仍 UNKNOWN（或不存在）
3. 更新 agent-os 行 5 / §5.1 注记：本地对账写账本已落；平台查询仍 P1 后续
4. 不改 `evaluate_unknown_publish_retry` 纯 gate 语义

## Acceptance Criteria

* [x] 对账确认 published → EffectLedger CONFIRMED（含 evidence）
* [x] uncertain → 账本不因对账被写成 CONFIRMED
* [x] gate / API 早退语义不变
* [x] 测试绿；docs 注明本刀范围

## Out of Scope

* 自动平台列表/详情查询
* Engagement ledger 改动
* MemoryManager uuid4

## Technical Notes

* `backend/agents/publisher.py` `reconcile_unknown_publish`；`tests/unit/agents/test_run_publish.py`（已有 reconcile 测）
* `backend/state/effects.py` 转移表只读对齐
