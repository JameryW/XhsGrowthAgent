# README 同步架构与工程结构

## Goal

README.md / README.zh-CN.md 停留在 2026-08-12（架构升级前），多处与现主干不符。
本任务只更新两份 README 的**事实性内容**，不改产品截图、不改安装/启动流程、不重写文档体系。

## 已确认的过期点（2026-09-22 实测）

1. 首段 "built as a LangGraph multi-agent workflow" —— 现为 Kernel-centric，
   LangGraph 已降级为 Task Graph Executor（父任务结清口径）。
2. `Architecture/Runtime`：缺 state 三层、Context Compiler、Tool Gateway、
   Durable Scheduler、Decision/Action 一节；持久化描述未提 workflow_events /
   execution_leases。
3. `Model routing` 表：正文写 DeepSeek / Claude Sonnet 4 / GPT-4o / Qwen Plus，
   实际 `backend/config/models.py` 几乎全路由 astron-code-latest，
   仅 POLISH / MOCK_GEN / VIRAL_MATCHING 走 deepseek-v4-flash。
4. Agent 表缺执行平面语义：Publisher 现走 PublishIntent → 策略引擎 → 人工确认 →
   Action Executor → Tool Gateway（`docs/publish-action-protocol.md`）。
5. `Further guides` 缺新契约文档：planning / context-compiler-baseline /
   tool-runtime / outcome-learning / publish-action-protocol / creator-agent /
   execution-plane / architecture-conventions / testing-guide。

## 不做

- 不重拍截图、不改 docs/assets。
- 不改安装命令、环境变量表（以 docs/configuration.md 为准，只修明显过期项）。
- 不动前端 i18n（README 双语对齐靠人工逐段对照，不走脚本）。

## 验收

- 中英两份 README 同结构、同事实（段落一一对应）。
- 文中所有相对链接存在（脚本校验）。
- 提及的模块路径在主干存在（backend/state、backend/context、backend/tools/runtime、
  backend/creator_agent、backend/db/execution_leases.py、backend/graph/plan.py）。
- ruff/mypy/pytest 不受影响（文档任务）；`git diff --check` 通过。
