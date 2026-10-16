# 合规与账号安全底线（MVP = P0）

## Goal

上线前补齐平台规则与账号安全底线：删除伪签名、隔离 stealth、堵住全自动无人发布、限制互动骚扰面、确定性违禁词扫描（含垂类词库扩展点）、商单披露强制确认。

## Decision (ADR-lite)

### 范围
**Decision**: 仅 P0-1～P0-5。P1/P2 另开任务。  
**Extra**: 词库按 `niche` 选库的最小扩展点（无 P2 分级 UI）。

### 伪签名
**Decision**: 删除 `XHSSignature` 及 HTTP 加伪签；保留 `XHSCookieParser`（可拆模块）。旧 HTTP 依赖伪签的调用返回明确错误码，不静默空结果。

### 双自动门
**Decision**: `AUTO_APPROVE_LOW_RISK` ∩ `auto_publish` → 启动硬拒绝（API 与 CLI 一致）。

### 私信仅回复
**Decision**: 未读/入站白名单；默认禁「新建私信」冷启动；主动私信需显式开关 + 逐条人工确认。

## Requirements

1. **P0-1 反检测与伪签名**
   - 主依赖移除 `fake-useragent`；默认路径不调用 `_apply_stealth`（stealth 仅 optional `[browser]` 且默认不注入）。
   - 删除 `XHSSignature`；`XHSCookieParser` 保留。
   - CI：默认配置下 grep 不到 stealth 注入调用。
   - 伪签删除后的 HTTP 路径：明确错误（如 `signature_unavailable`），不静默。

2. **P0-2 全自动发布留痕与硬拒绝**
   - `AUTO_APPROVE_LOW_RISK` + `auto_publish` 同时 true → `POST /start` 与 `xhs-growth run` 硬拒绝。
   - 合规 `is_blocking` / `is_commercial` / 高风险垂类：永不 `auto_low_risk`。
   - 发布回执：确认人、来源（`human` / `auto_*`）、时间。

3. **P0-3 互动频控与范围**
   - 默认上限：私信 20/日、评论回复 50/日（账号可配）。
   - `send_dm`：target 须在未读/入站 peer 缓存；否则拒绝。主动私信开关 + 逐条确认才可冷启动。
   - `_RISK_MARKERS` 命中 → 互动暂停默认 6h；Settings 可见原因与剩余时间。

4. **P0-4 确定性违禁词**
   - 可维护词库（极限词/医疗/金融/平台违禁）+ **按 niche 叠加扩展库**。
   - 在 LLM evaluator 之前扫描；命中 → blocking；Review 高亮。
   - ≥50 正例 + ≥50 反例；结果写入质量评估记录。

5. **P0-5 商业合作披露**
   - `workflow_mode=brief`（商单）→ `is_commercial=true`。
   - 发布确认前必须勾选「已报备/已标注」；文案不得去掉合作标注；缺失 → blocking。

## Acceptance Criteria

* [ ] `fake-useragent` 不在主依赖；默认无 `_apply_stealth` 调用；CI grep 检查存在
* [ ] `XHSSignature` 删除；依赖处返回明确错误；`XHSCookieParser` 可用
* [ ] API+CLI：双自动同时开 → 硬拒绝
* [ ] blocking / commercial / 高风险垂类：永不 auto_approve
* [ ] 发布回执含确认人/来源/时间
* [ ] 私信日上限 + 入站白名单；冷启动默认拒；风险暂停 Settings 可见
* [ ] 词库扫描在 LLM 前；niche 扩展库可加载；50+50 测试；结果入评估
* [ ] 商单 `is_commercial` + 披露勾选；缺标注 blocking

## Definition of Done

* 单测/必要集成测通过；lint / CI green
* README 或相关 docs 简述行为变更（人工门、私信策略、伪签删除）
* 默认配置偏安全

## Technical Approach

* **P0-1**: 拆 `xhs_signature.py` → cookie-only 模块；`xhs_client` 去掉加签；`xhs_login` 默认跳过 stealth（或仅显式 env）；`pyproject.toml` 去 `fake-useragent`；CI script/test。
* **P0-2**: `_wf_application.start_workflow` + CLI run 入口校验；`review_gate._should_auto_approve` 加 commercial/blocking/高风险否决；publish 回执字段扩展 + 测试。
* **P0-3**: `xhs_risk_gate` / engagement 层日配额 + inbound peer set；Settings API 暴露 pause 状态；错误码稳定。
* **P0-4**: `backend/tools/compliance/` 或 `backend/services/compliance_lexicon.py` + YAML/JSON 词库；evaluator 节点前插入确定性扫描；前端 Review 高亮（若现有 Review 组件易接）。
* **P0-5**: brief 启动置 `is_commercial`；publish_gate / review UI 勾选；evaluator 检查标注模式。

## Implementation Plan (small PRs / slices)

* Slice A: P0-1 伪签删除 + stealth/依赖/CI
* Slice B: P0-2 双门硬拒绝 + 回执 + auto 否决
* Slice C: P0-3 互动配额/白名单/风险暂停
* Slice D: P0-4 词库 + niche 扩展 + 测试语料
* Slice E: P0-5 商单披露 + Review/Publish UI 勾选

## Out of Scope

* P1 健康面板产品化（Settings 仅暴露暂停/冷却所需最小字段）、抓取预算、个保 API、AI 标识、auth Redis
* P2 学习回流、垂类分级 UI、G1–G5 签字看板
* 法务意见书；官方开放 API

## Open Questions

* （无阻塞项；默认数值已写入 Requirements，实现期可微调）

## Technical Notes

* Key files: `xhs_login.py`, `xhs_signature.py`, `xhs_client.py`, `xhs_engagement.py`, `xhs_risk_gate.py`, `review_gate.py`, `publish_gate.py`, `_wf_application.py`, CLI run, evaluator nodes/prompts, brief/workflow_mode, Settings UI
* Repo @ `855bb67`
* Specs: `.trellis/spec/backend/`, `.trellis/spec/guides/`
