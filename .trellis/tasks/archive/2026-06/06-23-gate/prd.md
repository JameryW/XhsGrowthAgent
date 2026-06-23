# 修复 gate 双重中断导致审核后无法发布

## Goal

修复 review_gate / choice_gate / draft_gate 的"interrupt_before 静态中断 + 节点内 interrupt() 动态中断"双重中断设计在 langgraph 1.2.6 下失效的问题。当前 review submit 后图直接 END，gate 节点不执行，human_feedback 为空，发布流程中断。采用**方案 B**：保留 interrupt_before，去掉节点内 interrupt()，改 submit 用 ainvoke(None) 推进 + aupdate_state 传递 decision，gate 节点从 state 读 decision。

## What I already know

### 根因（已排查确认）
- `interrupt_before=["review_gate","choice_gate","draft_gate"]`（builder.py:363/395-399）静态中断
- 这三个 gate 节点内又调 `interrupt(None)` 或 `interrupt(payload)` 动态中断
- submit 路径用 `Command(resume=decision.model_dump())` 恢复
- **langgraph 1.2.6**：`Command(resume=value)` 只对动态 `interrupt()` 生效，对 `interrupt_before` 静态中断无效
- 官方文档确认：interrupt_before 暂停后应 `ainvoke(None)` 推进；resume value 在 interrupt_before 阶段不被消耗
- 实测证据：4139ede5 submit 后 checkpoint_writes 只有 publish_options（aupdate_state）+ `__resume__`（END），review_gate 节点零写入，human_feedback={}

### 受影响 gate（双重中断 = bug）
| gate | interrupt_before | 节点内 interrupt | submit 路径 | resume value |
|------|------------------|------------------|-------------|--------------|
| review_gate | ✅ | `interrupt(None)` | review.py submit_review → Command(resume=decision) | ReviewDecision dict |
| choice_gate | ✅ | `interrupt(None)` | optimization.py select_version → Command(resume=choice) | VersionChoice dict |
| draft_gate | ✅ | `interrupt({gate:draft...})` | optimization.py submit_draft → Command(resume=draft) | DraftSubmission dict |

### 不受影响 gate（纯动态中断，正常）
- brief_gate / ripple_gate / blogger_gate：不在 interrupt_before 列表，纯 `interrupt(payload)` 动态中断，Command(resume) 正常工作

### choice_gate 特殊性
- 单版本时 auto-select，不调 interrupt（line 30），直接返回 —— 不受 bug 影响
- 多版本才走 interrupt(None) —— 受影响

## 方案 B 设计

**核心改动**：
1. 去掉三个 gate 节点内的 `interrupt()` 调用
2. gate 节点改为从 state 读 decision（decision 由 submit 通过 aupdate_state 写入）
3. submit 路径：先 `aupdate_state` 写 decision 到 state，再 `ainvoke(None)` 推进图（不再用 Command(resume=value)）

**state 字段**：
- review_gate：decision 写入 `human_feedback`（已有字段）
- choice_gate：decision 写入 `selected_version` + 相关字段（已有），或新增 `choice_decision`
- draft_gate：decision 写入 `draft_content`（已有字段）

## 方案 B 最终设计

**统一模式**（对 review_gate / choice_gate / draft_gate）：
1. submit 路径：先 `aupdate_state` 写 decision 到 state，再 `ainvoke(None)` 推进（不再用 `Command(resume=value)`）
2. gate 节点：去掉 `interrupt()` 调用，改为从 state 读 decision
3. 保留 `interrupt_before`（暂停仍由它触发，前端靠 state.next 判断 awaiting）

**各 gate decision 字段**：
| gate | submit 写入字段 | 节点读取 |
|------|-----------------|----------|
| review_gate | `human_feedback`（已有） | 从 state.human_feedback 读 decision |
| choice_gate | `selected_version`（已有，写 version_id） | 从 state.selected_version 读，找版本填 copy_content |
| draft_gate | `draft_content`（已有，source=user_submitted） | 已有跳过逻辑，仅去掉 interrupt() 调用 |

**关键自洽性**：review_outcome 路由读 `human_feedback.decision` —— submit 先写 human_feedback，ainvoke(None) 推进 review_gate_node（读 human_feedback），再 review_outcome（读 human_feedback.decision 路由）。链路通。

## Requirements

- review submit 后 review_gate_node 正常执行，human_feedback 写入 decision，图推进到 publisher
- choice_gate 多版本选择后正确写入 selected_title / copy_content
- draft_gate 提交草稿后正确推进（复用现有 draft_content 跳过逻辑）
- 不破坏 brief/ripple/blogger gate（纯动态中断，不改）
- 保留 interrupt_before 机制
- 旧卡住 workflow（6-15/6-16）作废，不尝试 resume

## Acceptance Criteria

- [ ] review submit 后图推进到 publisher，publish_result 非空（dry_run 时为 mock_published）
- [ ] choice_gate 多版本选择后 copy_content.selected_title 正确
- [ ] draft_gate 提交草稿后推进到 choice_gate/visual_designer
- [ ] brief/ripple/blogger gate 行为不变（单测覆盖）
- [ ] review_gate/choice_gate/draft_gate 节点内无 interrupt() 调用
- [ ] submit 路径用 ainvoke(None) 而非 Command(resume=value)
- [ ] 旧 workflow 标记作废（DB status 或文档说明）

## Out of Scope

- 方案 A（去掉 interrupt_before 改纯动态中断）—— 已选方案 B
- 多 gate 统一抽象（YAGNI）
- cookie/账号相关（PR #115 已处理）
- 旧 checkpoint 迁移脚本（作废处理）

## Out of Scope

- 方案 A（去掉 interrupt_before 改纯动态中断）—— 已选方案 B
- 多 gate 统一抽象（YAGNI，先修 bug）
- cookie/账号相关（PR #115 已处理）

## Technical Notes

- 关键文件：builder.py、review_gate.py、choice_gate.py、draft_gate.py、review.py、optimization.py
- langgraph 1.2.6，Command(resume) 只对动态 interrupt 生效
- 既有 commit b61dbf99（6-01）引入双重中断设计，本任务修正其错误假设
- spec：workflow-state.md 记录了 gate 契约，需同步更新
