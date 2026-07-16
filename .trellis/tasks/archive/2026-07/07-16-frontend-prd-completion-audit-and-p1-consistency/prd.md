# 前端 PRD 收尾与全站 P1 一致性验收

## 目标

收口归档 PRD 中尚未完成的验收项：逐页核对 P1/P2 页面矩阵、统一关键交互规则，并在本地服务可用时完成 Showcase → Replay 的真实数据烟测。

## 范围

- P1：`/start`、`/dashboard/:threadId?`、`/review/:threadId?`、`/history`、`/analytics`、`/evaluation`。
- P2：`/settings`、`/help`、`/tui`、`/login`、404。
- 全局：页面焦点、返回路径、触控尺寸、错误/空态、双语和 reduced-motion。
- 真实数据验收：展示页筛选/打开回放/检查点切换/返回上下文。

## 验收标准

- 认证页面拥有清晰页面目的、唯一主动作和可恢复错误/空态。
- History 的查看、继续、回放动作语义一致，返回路径可预测。
- Analytics/Evaluation 明确数据范围、账号和新鲜度，空数据不伪装成 0。
- Settings/Help/TUI/Login/404 的键盘、移动端和错误恢复路径可用。
- `320/390/768/1024/1440` 宽度无页面级非预期横向溢出。
- `npm run type-check`、`npm run test:run`、`npm run build`、`git diff --check` 通过。
- 后端可用时完成真实公开数据闭环；后端不可用时记录明确阻塞，不伪造成功态验收。

## 收尾记录（2026-07-16）

- 已完成 P1/P2 一致性收口：Analytics/Evaluation/Review 的错误恢复、日期本地化和键盘语义；首页推荐主题关闭、设置页删除确认；全局主要按钮触控尺寸统一为至少 44px。
- 已移除设置页原生 `confirm()`，统一使用可聚焦、支持 Escape 的 `ConfirmModal`；继续保留页面级错误卡和重试入口。
- 真实数据烟测已完成：本机 `xhs-growth` 服务在 `:8889` 可用，`/api/system/health`、`/api/workflow/list`、`/api/workflow/status/:thread_id`、`/api/workflow/history/:thread_id` 均返回成功数据；公开工作流列表包含 3 条记录，回放检查点返回 5 条且存在分页游标。
- 质量门禁：`npm run type-check`、`npm run test:run`（39 files / 530 tests）、`npm run build`、`git diff --check` 全部通过。
