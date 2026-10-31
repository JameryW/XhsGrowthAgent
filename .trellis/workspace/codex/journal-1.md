# Journal - codex (Part 1)

> AI development session journal
> Started: 2026-08-12

---



## Session 1: Split bilingual README and showcase product capabilities

**Date**: 2026-08-12
**Task**: Split bilingual README and showcase product capabilities
**Branch**: `main`

### Summary

Rewrote README.md as English-first, added README.zh-CN.md, captured live Showcase and Workflow Replay screenshots under docs/assets/readme, and documented the public/authenticated capability boundary from xhs.jameryw.dev.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `a586ba1b` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 2: Improve free creation UI and README showcase

**Date**: 2026-08-21
**Task**: Improve free creation UI and README showcase
**Branch**: `main`

### Summary

Added guided Free Creation goal handoff with examples and path steps; carried selected account and editable goal into AgentTUI; synchronized English and Chinese README product tours; added axe-core test dependency and coverage.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `175ece97` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 3: Fix public showcase auth error

**Date**: 2026-08-21
**Task**: Fix public showcase auth error
**Branch**: `codex/fix-public-showcase-auth`

### Summary

Removed redundant auth initialization from public Showcase and WorkflowReplay mounts, added guest regression tests, updated frontend state-management guidance, and verified 695 frontend tests plus production build.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `68bdbba1` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 4: Add free draft publish and copy commands to the Agent TUI

**Date**: 2026-08-22
**Task**: Add free draft publish and copy commands to the Agent TUI
**Branch**: `codex/free-tui-publish-copy`

### Summary

Added /publish <id> [confirm] with preview-first confirmation gate, degraded-eval and already-published refusals, and outcome rendering for success/mock/failure; added /copy <id> clipboard command with manual-selection fallback; wired help rows and /draft follow-up hints; bilingual locale strings; 8 new spec cases. type-check, i18n:check (2174 keys), 703/703 tests, and build pass.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `e7214eac` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 5: Free Creation post-publish feedback loop

**Date**: 2026-08-25
**Task**: Free Creation post-publish feedback loop
**Branch**: `codex/free-creation-polish`

### Summary

/free/analytics now persists a last_analytics snapshot onto the draft, backfills ContentHistory with raw counts (fraction rate), and writes one deterministic insight; TUI /analytics notes the saved snapshot, /draft shows latest engagement; History free-drafts tab renders view/like/collect badges. Backend 77 focused tests, ruff clean; frontend 720 tests, type-check/i18n/build green; bilingual README + free-creation spec updated.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `fbec9ef9` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 6: Free-mode RQGM samples feed evaluator evolution

**Date**: 2026-08-25
**Task**: Free-mode RQGM samples feed evaluator evolution
**Branch**: `codex/free-creation-polish`

### Summary

evaluate_draft now inserts an evaluator training sample under synthetic thread key free:{draft_id} (mirrors _collect_sample guards: degraded/scoreless/non-ready status and pool-down all skip); /free/analytics backfills the weak engagement label onto that sample with raw counts. 85 focused route tests + 103 omp-bridge tests green, ruff clean, free-creation spec updated. Zero schema migration.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `33742760` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 7: Free drafts anchor creative memory calibration

**Date**: 2026-08-25
**Task**: Free drafts anchor creative memory calibration
**Branch**: `codex/free-creation-polish`

### Summary

FreeDraft gained optional style_id/play_id anchors (create+PATCH); build_creative_context now exposes record ids so the agent can anchor; publish threads anchors into the ContentHistory chain via _build_publish_state; /free/analytics triggers schedule_calibration with the analyst's payload builder when anchored and views>0. omp tool schema/usage updated. 236 tests across free routes + creative memory + omp bridge, ruff clean, spec updated.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `a0423531` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 8: Free analytics triggers evaluator evolution

**Date**: 2026-08-26
**Task**: Free analytics triggers evaluator evolution
**Branch**: `main`

### Summary

get_analytics now fire-and-forgets maybe_evolve after a successful weak-label backfill (mirrors analyst._safe_evolve; testable _schedule_free_evolve seam). Free-mode samples can cross the fit threshold autonomously. +3 tests (95 free-route total), omp-bridge 103 green, ruff clean, spec boundary removed. Merged via PR #551.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `80593cc1` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 9: Engagement snapshot trend series

**Date**: 2026-08-26
**Task**: Engagement snapshot trend series
**Branch**: `main`

### Summary

Repeated /analytics fetches now build a capped trend series (analytics_snapshots, last 10) alongside the latest-pointer last_analytics; list summaries carry a server-computed engagement_trend views delta; TUI detail card renders a colored +/- delta line and the History GUI badge row gains an up/down indicator once two captures exist. Bilingual i18n +3 keys, README en/zh, spec contract updated. Backend 243 passed, frontend 725 passed, type-check/i18n/build green. Merged via PR #552.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `8aef8bc4` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 10: Material vault anchors activate calibration

**Date**: 2026-08-26
**Task**: Material vault anchors activate calibration
**Branch**: `main`

### Summary

FreeDraft gained optional material_ids; _to_copy_content threads used_material_ids and build_calibration_payload synthesizes per-material effectiveness (0.9/0.25 by the >=3% signal) when the analyst provides none - activating the dormant _calibrate_materials path for both free mode and the fixed workflow. Creative context materials now expose id=. +10 tests (259 across four suites), ruff clean, spec updated. Merged via PR #553.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `c0f4ff54` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 11: Display creative memory anchors on drafts

**Date**: 2026-08-27
**Task**: Display creative memory anchors on drafts
**Branch**: `codex/free-anchor-display`

### Summary

Finished the in-progress anchor-display task: list_drafts carries style_id/play_id/material_ids, TUI /draft renders an anchors line, History free-drafts panel shows an anchor badge with id tooltip; fixed the self-defeating omit-test fixture and removed a debug console.log. Backend 105 focused tests, frontend 729/729 + type-check + i18n (2234 keys) + build green; local ruff/mypy noise verified pre-existing on main.

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `30521fda` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 12: 完成自由草稿下一步深链

**Date**: 2026-08-31
**Task**: 完成自由草稿下一步深链
**Branch**: `codex/free-creation-next-step-actions`

### Summary

完成自由草稿 History 到 TUI 的发布预览与表现采集深链；修正摘要缺少 post_id 时的真实帖子身份校验；聚焦测试、类型检查、i18n 与生产构建通过；任务已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `05c47b39` | (see git log) |
| `a6d0a43d` | (see git log) |
| `0b7b23ea` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 13: 实现自由草稿快速预览抽屉

**Date**: 2026-08-31
**Task**: 实现自由草稿快速预览抽屉
**Branch**: `codex/free-draft-preview-drawer`

### Summary

新增账号隔离、只读、响应式的自由草稿详情抽屉；展示正文、创作上下文、评估、锚点、发布与表现数据；复用完整详情生成安全 TUI 下一步；补齐迟到响应、焦点恢复与真实帖子身份测试。68 项聚焦测试、类型检查、i18n 和生产构建通过，任务已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `91a17386` | (see git log) |
| `03b8fe3d` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 14: 实现自由草稿连续审阅队列

**Date**: 2026-08-31
**Task**: 实现自由草稿连续审阅队列
**Branch**: `codex/free-draft-preview-review-queue`

### Summary

在自由草稿预览抽屉内新增当前过滤队列的位置、上一条/下一条和 Alt+方向键导航；按 draft_id 实时派生位置，支持刷新重排、目标移除、账号切换与迟到详情防护；不循环、不预取、不写数据。75 项聚焦测试、类型检查、i18n 和生产构建通过，任务已归档。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `3b152b36` | (see git log) |
| `afa46e6` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 15: 保存自由草稿审阅返回上下文

**Date**: 2026-08-31
**Task**: 保存自由草稿审阅返回上下文
**Branch**: `codex/free-draft-review-return-context`

### Summary

新增白名单路由上下文深模块，支持 History 筛选与草稿预览在 TUI 往返恢复；收紧账号与草稿身份一致性、重定向参数清理和账号切换同步清场。101 项聚焦测试、类型检查、i18n 与生产构建通过。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `45b72dcc` | (see git log) |
| `61d5073a` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 16: P0 正确性修复完成并合并（PR #577），P1a 方案拍板

**Date**: 2026-09-13
**Task**: P0 正确性修复完成并合并（PR #577），P1a 方案拍板
**Branch**: `main`

### Summary

架构升级启动：建 runtime-upgrade 父任务+9子任务；P0(W1-W5+F1-F3) 两轮实施两轮 check 全绿合并 PR #577；沉淀 error-handling/workflow-state 规范；P1a 勘察两篇+方案件，D1-D5 已拍板，prd/jsonl 就绪

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `48c4c993` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 17: P1a/P1b 快照落盘、PR#642 开关与主干同步

**Date**: 2026-09-22
**Task**: P1a/P1b 快照落盘、PR#642 开关与主干同步
**Branch**: `main`

### Summary

本地 P1a+P1b 快照提交 ccac0e03 并推分支建 PR#642；fetch 后发现远端已完整落地 P1a/P1b 及后续演进（runtime-upgrade 全系归档），PR#642 实为过期平行副本。补提交回填后关闭 PR#642、删除分支，本地 main reset 到 origin/main（1493cf50e）。同步后全量门禁 3615 passed / 3 skipped。教训：开工前先 fetch 对齐远端；git untracked-cache 损坏曾隐藏新文件，已禁用。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `1493cf50e` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 18: 归档 09-18～09-20 已合并任务

**Date**: 2026-09-22
**Task**: 归档 09-18～09-20 已合并任务
**Branch**: `main`

### Summary

核验 PR#630-#641 全部 MERGED 后归档 11 个 completed 任务（task.py archive，各自 auto-commit），活跃任务 27→16。uv.lock 附带 5846 行换行符 churn 已 revert 未入库。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `9a6b5ad03` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 19: 剩余任务分诊与归档：16→2

**Date**: 2026-09-22
**Task**: 剩余任务分诊与归档：16→2
**Branch**: `main`

### Summary

分诊 16 个剩余任务：9 个 creator-agent（实现 PR#560-566 在 main，179 passed/2 skipped，ruff/mypy 净）+ free 批次 3 项（后端 116 passed、AgentTUI.spec 46/46）+ 双语 README + 08-11 数据同步修复（creator_stats 249 passed）共 14 个验证归档，已 push。07-17 与 08-05 系 owner 在 prd 明确保留的仓外发布总闸（人工走查/Lighthouse/签字），不可伪造完成，保持 in_progress。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `a94bdabdb` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 20: parked 双任务回归复验

**Date**: 2026-09-22
**Task**: parked 双任务回归复验
**Branch**: `main`

### Summary

07-17/08-05 虽被仓外总闸 park，复验代码仍绿：前端 775/775（一次 localhost:3000 flaky 环境噪声）、type-check、i18n 2317 keys、后端 upsert 相关 54 通过。复验结论追加进两任务 prd，不改判 in_progress。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `HEAD` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 21: owner 豁免关闭最后双任务，全清

**Date**: 2026-09-22
**Task**: owner 豁免关闭最后双任务，全清
**Branch**: `main`

### Summary

用户指示跳过签字直接关闭：以豁免（风险接受，非门槛通过）记录 G1-G8 残留风险，归档 07-17/08-05，活跃任务归零。修复被 index.lock 中断的分裂提交并补推；清理 09-11-p1-context-compiler 空 research 残留。远端已同步。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `f139d7a1a` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 22: 架构升级完成度实质审计

**Date**: 2026-09-22
**Task**: 架构升级完成度实质审计
**Branch**: `main`

### Summary

独立复算：PR#577-627 合并提交连续无缺口；9/9 交付物在现主干均存在（state/context/tools-runtime/leases/machine-modes/policy/publish-gate 及 6 份契约文档），tool_runtime_gate 绿。遗留 8 条重核：R1/R6 已由#630-641 关闭（租约+孤儿0），R3 系误登记已撤回，R5 声明性钉断言；R2（3 处直调=协议契约）/R4（零调用者+反向断言）/R7（写侧不合并）/R8（创建时间窗口+保守方向）仍刻意开放且与登记一致。结论：升级交付完成，4 条已知开放残留，无新增缺口。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `HEAD` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 23: README 双语架构同步

**Date**: 2026-09-22
**Task**: README 双语架构同步
**Branch**: `main`

### Summary

README 中英事实同步：内核口径、Kernel layers 新节、真实模型路由、visual 路径修正、7 契约文档链接；验收对齐/链接/路径/diff-check 全绿，已提交归档并推送。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `HEAD` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 24: 分支与垃圾清理

**Date**: 2026-09-23
**Task**: 分支与垃圾清理
**Branch**: `main`

### Summary

删本地 .workbuddy scratch、924MB 死 venv、logs 旧输出；删远端 64 个已合并分支（开放 PR 为 0），15 个含独有提交的未合并分支保留待定。本地仅 main，远端剩 main+15，工作树干净已同步。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `HEAD` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 25: 15 个残留分支审计与清理

**Date**: 2026-09-23
**Task**: 15 个残留分支审计与清理
**Branch**: `main`

### Summary

10 条 cherry-clean（补丁已在主干）+ 5 条内容核对（探针/showcase 初始化移除/风险能力/前端基建均已等价落地，唯一独有测试文件 import 已死路径作废）。用户确认后删除全部 15 个远端分支并 prune，远端仅剩 main。分析方法：git cherry + merge-base 文件存在性 + 关键符号抽查。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `HEAD` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 26: 架构任务核验 + 重试撞重试闸门（票 5an）

**Date**: 2026-10-31
**Task**: 架构任务核验 + 重试撞重试闸门（票 5an）
**Branch**: `main`

### Summary

拉取最新代码（546c99c0）后四路核验：票 5a–5am 39/39 全部合入、Trellis 无活动任务、无未合并分支承载未完成工作；但架构路线图仍有 P2/P3 延后项与 1 条无票实锤缺口（execution-plane §7.1 重试撞重试无闸门）。本轮补完该缺口：新增 _runner._retry_tasks + claim/attach/abandon（claim 先于 create_task，done callback 释放，is 身份守卫），两入口守卫加 retry_in_flight，不扩宽通用 busy 谓词；测试 15 例 + 6 条 claim 值；§7.1 清空并将 §6 由 34 修正为 38；顺带修正 agent-os / memory-promotion 的已核实漂移。独立复审后补 publish 并发行为测试、收紧「不扩宽」断言（谓词两种拼法都扫），M1–M7 突变自检全部变红。定向 42 passed，ruff/format 绿；沙箱 tmp_path ACL 造成的 ERROR 属环境性。未 push。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `cfc33d7e` | (see git log) |
| `e0930d96` | (see git log) |
| `8af9094d` | (see git log) |
| `07910523` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete


## Session 27: 架构遗留收口：EVENT_KINDS 退休 + 记录纠偏（票 5ao / 5ap）

**Date**: 2026-10-31
**Task**: 架构遗留收口：EVENT_KINDS 退休 + 记录纠偏（票 5ao / 5ap）
**Branch**: `main`

### Summary

继续完成未完成的架构任务中仅剩的可执行项。票 5ao：把从未有发射者的 cost/error 两条 kind 从 EVENT_KINDS 退休（13->11）——成本已在 kind:llm 的 cost_usd、错误已在 realtime WORKFLOW_ERROR 与 kind:node 的 status/error，补发射端会造第二份真相；新增 tests/unit/db/test_workflow_events_kinds.py 钉住完整声明集，突变回加 cost 令两断言变红；publish-action-protocol 已知残留收口且 claim 值不变。票 5ap：给 09-11 runtime-upgrade 归档 notes 追加 CORRECTION 2（(1)(6) 已由 #635/#636、票 5p #709 关闭；(2)(4)(5)(7)(8) 仍为 B 类；(3) 保持回撤；原文未改），并订正 promotion_observations.py 的 PRD §9 旧措辞。验证：db/state/signal_inventory/retry-gate/memory 756 passed（9 个 tmp_path ERROR 为沙箱环境性），docs anchors/claims/citations 8 passed，ruff/format 绿。仍未做：P2/P3（需证据/评测集）与 B 类裁决（控制面迁移等，需拍板）。

### Main Changes

(Add details)

### Git Commits

| Hash | Message |
|------|---------|
| `cc92b052` | (see git log) |
| `cb6e4876` | (see git log) |
| `a4c48e7b` | (see git log) |
| `5d2d4e07` | (see git log) |

### Testing

- [OK] (Add test results)

### Status

[OK] **Completed**

### Next Steps

- None - task complete
