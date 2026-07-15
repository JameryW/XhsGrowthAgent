# 修复近期 PR 回归

## 目标

修复最近合入的免费模式、创作者统计调度、CDP 抓取和跨入口一致性问题，保持现有未提交 RQGM 改动不受影响。

## 必须完成

1. 免费模式 WebSocket 新建会话必须继承当前 `free`/`workflow` mode，不能在 `/new` 或 free `/start` 后泄漏工作流工具。
2. 创作者统计全量同步必须在多进程部署中使用 PostgreSQL 分布式互斥；无数据库时保留进程内锁。
3. TUI `/suggest` 必须使用当前 XHS 账号 ID，而不是控制台用户 ID。
4. CDP 统计抓取必须接收并应用请求周期，且单次详情 enrichment 有可控总耗时/并发边界。
5. Web bridge 和 TS extension 的 free-mode 流程说明与工具集策略必须一致：原子工具 + 明确的 mode-specific 编排提示，且 TS extension 不应注册 free 模式禁用的工作流工具。
6. 修复素材标签过滤的分页/limit 语义，避免高权重不匹配项遮蔽后续匹配项。
7. 所有用户可见的免费模式文案统一改为“自由创作模式”（英文为 “Free Creation Mode”）；`mode=free`、`xhs_free_*` 等协议标识保持兼容。

## 验收

- 增加覆盖上述回归的后端/前端单元或集成测试。
- 运行相关 pytest、前端 Vitest、类型检查、Ruff，并确认现有工作区改动未被覆盖。
- 不修改与本任务无关的用户未提交文件。
