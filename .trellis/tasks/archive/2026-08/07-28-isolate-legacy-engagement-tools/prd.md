# 隔离旧版互动工具映射

## 背景

自动评论和自动私信已经从工作流图中移除，但 `ToolRegistry._agent_tools` 仍保留旧的 `engagement` agent 映射。该死映射会让后续维护者误以为存在可调度的互动 agent，也可能在未来重新注册工具时意外恢复自动互动入口。

## 目标

1. 从 agent 工具映射中移除旧的 `engagement` agent，确保工作流 agent 无法通过注册表获得评论、私信工具。
2. 保留明确的人工调用工具，以兼容人工审核后的单次评论/私信操作。
3. 用回归测试和开发规范明确“工作流不自动互动、互动工具仅人工显式调用”的边界。

## 非目标

- 不删除人工互动工具本身。
- 不改动创作者中心统计、登录、发布或分析能力。
- 不修改历史 checkpoint 中的 `ENGAGING`/`engagement_actions` 兼容字段。

## 验收标准

- `ToolRegistry.get_tools_for_agent("engagement")` 返回空列表，且注册表不再声明该 agent。
- 普通工作流 agent 的工具集合不包含 `comment_replier`、`dm_handler` 或 `fetch_pending_comments`。
- 人工工具模块仍可导入，且其文档明确要求人工显式触发。
- 相关单元测试、ruff、mypy 通过。
