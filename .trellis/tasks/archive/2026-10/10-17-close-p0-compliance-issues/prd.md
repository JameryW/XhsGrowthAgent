# Close completed P0 compliance GitHub issues

## Goal

对照 `main` 上已合并的 P0 实现，关闭仍 OPEN 的 GitHub issues #644–#656（实现已在 #657 交付，issue 未关）。

## Decision (ADR-lite)

| Topic | Decision |
|-------|----------|
| 范围 | 仅 #644–#656（当前全部 open issues） |
| 关单方式 | Agent 无 `gh issue` 写权限（403）→ 开 PR，body 使用 `Closes #N`，合并后自动关单 |
| 实现缺口 | 无；路径/命名与 issue 原文略有差异（如 lexicon 在 `backend/services/compliance/`，stealth 为默认关闭+opt-in）属已锁定 MVP |

## Requirements

1. 为每个 issue 写证据映射（文件/测试/PR）。
2. 提交 closeout 文档并开 PR，body 含全部 `Closes #644` … `Closes #656`。
3. 不改业务行为代码。

## Acceptance Criteria

* [x] #644–#656 均在 main 有对应实现证据
* [x] Closeout PR 打开且 body 含 13 条 Closes
* [ ] PR 合并后 issues 全部 closed（依赖 merge）

## Out of Scope

* 重做 P0 行为
* 真人 G1–G8 签字（仍为 waived）
* 新建 P1/P2 GitHub issues

## Technical Notes

* Delivered by #657 (+ specs #658, P1 #659/#660, P2 #661, signoff #663)
* `gh issue comment/close` → 403 Resource not accessible by integration
