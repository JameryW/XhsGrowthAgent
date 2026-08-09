# 继续优化：全方向优化活动

## Goal

冷启动 import 活动 (#451-#463) 已达框架地板 (prod 2.18s→0.44s)。用户要求"全部"方向继续优化：请求延迟 + LLM 成本/速度 + 可靠性/正确性 + 其他（前端运行时/内存/DX）。多 PR 推进，每个 PR 从 main 新建分支，可测量收益。

## What I already know

**已优化层（勿重复）：**
- 冷启动 import: PR #451-#463，prod 2.18s→0.44s (4.5x)，达框架地板 (fastapi 240ms + pydantic.v1 24ms + 路由 Pydantic 定义)
- 列表端点 N+1: inbox (#451) / evaluation (#450) / analytics 全部 asyncio.gather 并发 checkpoint 读
- 前端分包: manualChunks (vue-vendor/axios/echarts) + App.vue 6 个 defineAsyncComponent + 路由全懒加载 + addon-webgl 动态 import + 意图性 hover/idle prefetch
- 模型路由: get_router singleton + get_model cache (model_id:timeout key)
- with_retry: 已有完整测试 (test_retry.py 覆盖 429/4xx/5xx/connection/sync/delegation)

**待审查方向（全部）：**
1. 请求延迟 — 插桩实际端点，找真瓶颈（非猜测）
2. LLM 成本/速度 — Agent 调用链、token 用量、模型路由、prompt 优化
3. 可靠性/正确性 — 关键路径未覆盖逻辑、竞态、错误处理
4. 其他 — 前端运行时、内存占用、DX

## Requirements (evolving)

- 每个 PR 必须可测量收益（before/after 数据）
- 每个 PR 从 main 新建分支（stash 模式）
- 不发布 fake 优化（os.environ 缓存破坏 6 测试换微秒 = 净负，已排除）
- pre-push triple: ruff format --check + mypy backend + pytest

## Direction 1 — 请求延迟 (FIRST PR)

**目标:** `/api/workflow/status/{thread_id}` 轮询路径每次调用都写 DB，即使状态无变化。

**根因:** `get_workflow_status` (workflow.py:778) 每次调用 `await _db_upsert(thread_id, **update_fields)`。前端 5s 轮询 (`workflow.ts:1089`) → 每次轮询 = 1 次 DB 读 (db_get) + 1 次 DB 写 (db_update)，即使 phase/status/progress 完全没变。已完成工作流还会重写整个 history JSON 文件 (`_save_history_file` workflow.py:747)。

**修复 (ponytail minimal):** `_db_upsert` (_runner.py:38) 在 `db_get` 后比较 `fields` 与 `existing` row，所有字段相等则跳过 `db_update`。对 start/resume/pause/cancel 调用方无影响（那些路径状态总在变，必然写）。

**收益:** 轮询期无变化时省掉 DB 写往返。5s 轮询 × N 工作流 = 可测量的 DB 负载下降。

**验证:**
- 现有测试无断言 update 调用次数 (test_status_account_id/test_orphan_detection/test_api_routes 均未 assert update_workflow) → 不破坏
- 新增单测: 同状态连续 upsert 只写一次；状态变化才写
- prod 验证: 轮询期 DB 写次数下降

## Acceptance Criteria (evolving)

- [ ] 方向 1: `/status` upsert skip-unchanged PR + 测试 + 测量
- [ ] 方向 2: LLM 成本/速度优化 PR + 测量数据
- [ ] 方向 3: 可靠性 PR（测试覆盖或竞态修复）
- [ ] 方向 4: 视发现而定

## Definition of Done

- Tests added/updated
- Lint / typecheck / CI green
- 测量数据记录在 PR body
- 部署后 prod 验证

## Out of Scope

- 重复已优化层（冷启动 import / 列表 N+1 / 前端分包 / 模型缓存）
- 架构重构（高风险低回报，如路由注册改造）

## Technical Notes

- 测量运行 prod 容器非本地盒（import 活动教训）
- codegraph "no covering tests" 标记不可信（with_retry 实际有测试）
- DB 数据集小 (checkpoints 71 rows / workflows 2 rows)，规模不足以体现索引优化

## Progress

### PR #464 (Direction 1 — 请求延迟) ✅ MERGED+DEPLOYED
- `/status` 轮询路径 `_db_upsert` skip-unchanged：状态无变化时跳过 DB UPDATE（省 round trip + row lock）
- 新增 `tests/unit/api/test_db_upsert_skip.py` 8 tests
- prod 验证：同状态连续 upsert 0 写，状态变化 1 写
- 全量 2019 passed

### PR #465 (Direction 2 — LLM 成本/速度) ✅ MERGED+DEPLOYED
- content_strategist `_ripple_predict`/`_validate_pmf` 硬编码 `max_waves=3, simulation_horizon="12h", ensemble_runs=1` → 改读 `Settings().ripple.default_*`
- 根因数据：prod checkpoint perf_log 显示 content_strategist 节点 **352s**（两 Ripple CAS sim 同步阻塞，各 max_wait=1800s）
- env vars 此前对这些调用点无效；现在 RIPPLE_DEFAULT_MAX_WAVES/SIMULATION_HORIZON/ENSEMBLE_RUNS 生效，给运营降 352s 阻塞等待的杠杆
- 新增 3 tests；2022 passed；prod 验证两 call site 读 ripple_cfg.default_* 无硬编码
- trellis-implement + trellis-check 双 sub-agent 验证 green

## Direction 2b — Ripple background 模式正确性修复 (PR #466, OPEN)

**问题（已确认）：** `Settings().ripple.background=True` 时 content_strategist 触发后台 Ripple (`_schedule_ripple_background`) 后立即返回（设 `ripple_pending=True, ripple_reason="pending"`）。`ripple_finalize` 紧接运行，读 `store.aget(("ripple", thread_id), "result")` 为空（Ripple ~352s 未完成）→ pass-through (`ripple_pending=False, ripple_reason="pending"`)。后台 Ripple 完成后写 store + 发 `WORKFLOW_DATA_UPDATED data_type="ripple_ready"` 事件，**但无后端消费者**：
- `/review/ripple-pending/{thread_id}` 只读 `state.values`，不读 store → 工作流已过 finalize 不在 ripple gate → 报 "not awaiting Ripple decision"
- `ripple_ready` 事件只推 WebSocket 给前端，无后端 handler 重读 store / 重注入 state
- 结果：Ripple 预测数据**永久丢失**，发布内容不含传播预测，次优内容也不触发 reangle/retopic

**设计决策（ADR-lite，两轮确认）：**

**Context:** background 模式基建已搭好（fire-and-forget task 写 store + 发事件），但缺"晚到数据回收"消费者。bounded poll 仍半阻塞且超时丢数据；drop background 则 352s 阻塞无法消除。

**第一轮选 Accept-late via event handler — 否决：** LangGraph `interrupt()` 只能在节点执行内部调（raise 特殊异常被 checkpoint 捕获），事件 handler 在节点外 `aupdate_state` 可写 state 但**无法暂停图**。架构障碍，走不通。

**Decision（最终）：Late-recheck gate node** — 新增 `ripple_late_recheck` 节点插在 `visual_designer` 之后、`review_gate` 之前（background 模式专属路径）。这样 copywriter+visual_designer (~88s) 与 Ripple (~352s) **并发**，recheck 在 review_gate 前等剩余 Ripple 时间，次优则 `interrupt()` 复用 `/review/ripple-decision` 恢复路径。

**节点逻辑：**
- `ripple_finalize`：store 空时保持 pass-through，但保留 `ripple_pending=True`（让 recheck 知道要查 store）。当前 finalize 设 `ripple_pending=False` 需改。
- `ripple_late_recheck`（新节点）：
  - `ripple_pending=False`（blocking 模式或已处理）→ 直接 pass-through
  - bounded poll `store.aget(("ripple", thread_id),"result")`，cap = 新 setting `ripple.late_recheck_timeout`（默认如 300s，<= workflow_timeout）
  - Ripple 完成 → 写 `ripple_prediction`/`ripple_pmf` + 清 `ripple_pending`；次优且 `reselect_count<2` → `interrupt(payload gate="ripple")`
  - poll 超时仍未完成 → pass-through（`ripple_reason="pending"`, `ripple_pending=False`），不阻塞 publish（fail-open，同当前丢数据但至少不卡死）
- 恢复路径：`/review/ripple-decision` Command(resume) → `ripple_finalize_router` 语义路由（accept→review_gate, reangle→content_strategist, retopic→trend_scout）

**Consequences / 风险（实现须验证）：**
- copywriter/visual 已用空 Ripple 跑完 → reangle 回 content_strategist 会重跑（含 Ripple，但 background 模式 strategist 不再阻塞，OK）
- 真并发收益：352s 阻塞 → max(0, 352-88)=264s 在 recheck 等（仅当 Ripple 慢于 copywriter+visual）。若 Ripple <88s 则零阻塞
- review_gate 已过的边界（用户审稿慢于 Ripple）：recheck 在 review_gate 前，无此问题
- 幂等：recheck 节点只跑一次（图拓扑保证），finalize 已处理过 store 则 recheck 跳过（`ripple_pending=False`）
- `ripple_late_recheck_router` 需新增（镜像 ripple_finalize_router）

**实现范围：**
- 新增 `backend/agents/nodes/ripple_late_recheck.py`（节点 + router 或 router 入 routers.py）
- `ripple_finalize.py` 改：store 空时保留 `ripple_pending=True`（非 False）
- `graph/builder.py` 加节点 + background 模式边：`visual_designer → ripple_late_recheck → [review_gate | interrupt-resume path]`
- `config/settings.py RippleSettings` 加 `late_recheck_timeout: int = 300`
- 新增单测：recheck poll-成功/interrupt/超时-pass/幂等-skip/blocking模式-skip
- prod 验证：background 模式 copywriter+visual 并发、Ripple 完成后 recheck 写 state、次优 interrupt

**Out of scope（本 PR 不做）：**
- 启用 `RIPPLE_BACKGROUND=True` 的 config flip（修复验证通过后单独决策）
- env var 命名对齐（`RIPPLE_DEFAULT_MAX_WAVES` vs `RIPPLE_MAX_WAVES`，见 [[ripple-sim-params-read-settings]]）

## Direction 2c — copywriter 第二慢节点（FOLLOW-UP，待 Ripple PR 落地后）

**prod 实测（xhs_9eaec02e 线程, total 490s）：**
- content_strategist 352s（Direction 2b 修复中）
- **copywriter 60.5s** ← 第二慢，下一目标
- blogger_scout 25.7s, viral_matcher 21.8s, trend_scout 18s, visual_designer 12s

**根因（已查 codegraph）：** `CopywriterAgent.execute`（copywriter.py:29）做 **2 次顺序 LLM 调用**，均路由 `TaskType.WRITING` → `astron-code-latest`（models.py:107，注意 CLAUDE.md 文档说 claude-sonnet 已过时，实际 astron）：
1. `_llm_ainvoke`（:138）— 主草稿生成
2. `_apply_de_ai_taste` → `polish_copy(use_llm=True)`（:352, de_ai_taste.py:215）— 套话润色

两次串行，第二次是窄转换（去套话），用同款大模型过重。`polish_copy` 已有 `algorithmic_de_ai` 兜底（:218 fallback_fn）。

**候选优化（需设计+质量验证，非简单改）：**
- A: polish_copy 路由到更轻模型（新 TaskType 或复用 ROUTING 的 deepseek）— 砍一半 copywriter 时间+成本，但窄转换质量需样本验证
- B: 合并 draft+polish 为单次 prompt — 风险高，改变质量轮廓
- C: polish 默认降级 algorithmic（已有兜底），LLM polish 改为可选 opt-in — 最省但去套话效果可能降级

**前置：** 等 Ripple late-recheck PR 合并后从 main 新分支。需质量样本（before/after 去套话效果对比）才可交付，非纯性能 PR。

## Direction 2c — copywriter polish 降级轻模型 (PR #467, OPEN)

**用户确认选 "Lighter model for polish"（2026-08-05）。**

**实现方案（已查 codegraph）：**
- 新增 `TaskType.POLISH = "polish"`（config/models.py StrEnum）
- `resolve_model_id` 路由表加 `TaskType.POLISH: "deepseek-v4-flash"`（已配置 ModelConfig，models.py:73，便宜快）
- `polish_copy`（tools/content/de_ai_taste.py:215）的 `enrich_with_llm(task_type=TaskType.WRITING)` → `TaskType.POLISH`
- `llm_enrichment.py:_get_model` 已按 task_type 缓存，无需改
- 主草稿 `_llm_ainvoke`（copywriter.py:138）保持 WRITING→astron（草稿质量要求高，不动）

**收益：** polish 从 astron-code-latest → deepseek-v4-flash。copywriter 2 次串行 LLM：主草稿(astron) + polish(deepseek)。deepseek-v4-flash 比 astron 快/便宜，砍 polish 调用时间+成本。算法兜底已有（algorithmic_de_ai）。

**风险/验证：** polish 是窄转换（去套话），deepseek-v4-flash 质量需样本验证。fallback 机制保留（LLM 失败 → algorithmic）。pre-push triple + 相关 pytest。

**未做：** 质量样本对比（PR 验证后用户视效果决定是否回滚）。文档（CLAUDE.md TaskType 表已过时，本 PR 顺带更新）。

## Direction 2d — blogger_scout mock 生成降级轻模型 (PR #468, OPEN)

**用户确认选 "New MOCK_GEN task_type"（2026-08-05）。**

**实现方案（已查 codegraph）：**
- 新增 `TaskType.MOCK_GEN = "mock_gen"`（config/models.py StrEnum）
- `resolve_model_id` 路由表加 `TaskType.MOCK_GEN: "deepseek-v4-flash"`
- `BloggerScoutAgent.task_type = TaskType.SCOUTING` → `TaskType.MOCK_GEN`（blogger_scout.py:23）
- **不动 trend_scout**（保持 SCOUTING→astron，真实趋势分析质量要求高）

**根因：** blogger_scout 26s（第三慢，prod thread xhs_9eaec02e）。LLM 调用是 `_generate_mock_candidates`（虚构 mock_ 前缀博主候选，结构化输出）+ `_retry_mock_with_explicit_json`（重试）。纯虚构生成，astron 过重。但 trend_scout(18s) 共享 SCOUTING，不能改 SCOUTING 路由——故新增 MOCK_GEN 独立路由。

**收益：** blogger_scout mock 生成从 astron→deepseek-v4-flash，砍时间+成本。结构化虚构输出质量可比（hardcoded fallback 兜底）。

**风险/验证：** mock 候选虚构质量需样本（虚榦博主候选可用性）。fallback `_hardcoded_fallback_candidates` 保留（LLM 失败）。pre-push triple + 相关 pytest。

**未做：** 质量样本对比；CLAUDE.md 已在 PR#467 修正路由文档，本 PR 若加 MOCK_GEN 行需再更新（顺带）。

## Direction 2e — viral_matcher 降级轻模型 (PR in progress)

**用户确认选 "Route VIRAL_MATCHING→deepseek"（2026-08-05）。**

**实现方案（已查 codegraph）：**
- `resolve_model_id` 路由表 `TaskType.VIRAL_MATCHING: "astron-code-latest"` → `"deepseek-v4-flash"`（一行改动，不需新 TaskType——VIRAL_MATCHING 独立无共享 agent）
- 不动 viral_matcher.py 逻辑

**根因：** viral_matcher 22s（第四慢）。LLM 调用虚构爆款参考笔记（viral_posts JSON），无真实 XHS 搜索工具（prompt 说"自动搜索"但纯 LLM 生成）。VIRAL_MATCHING task_type 独立（无其他 agent 共享），可直接改路由。

**收益：** viral_matcher 虚构参考 astron→deepseek-v4-flash，砍时间+成本。结构化虚构质量可比，已有 skip_optimization 兜底（LLM 失败跳过优化）。

**风险：** viral_posts 是优化参考，质量影响下游优化方向。但虚构参考本身质量上限有限，deepseek 可接受。CLAUDE.md 路由表已含 VIRAL_MATCHING→astron，改后需更新该行（若 main 已合 #467/#468 则文档已有完整表，本 PR 改 VIRAL_MATCHING 行+加注释）。

## Direction 2f — deepseek-v4-flash 全局改 deepseek-v4-flash (PR in progress)

**用户指令（2026-08-05）：** "把所有使用 deepseek-v4-flash 的地方都改成 deepseek-v4-flash"。

**范围（grep 全量）：**
- `backend/config/models.py`: MODEL_REGISTRY key + model_name + MODEL_COST_PER_1K key
- `tests/unit/config/test_models.py` + `test_model_routing.py`: 断言值
- `api/spec/openapi.yaml` + `backend/api/generated/models.py`: cost example model names
- `CLAUDE.md` + `docs/configuration.md`: 文档路由表
- 不动 `.trellis/tasks/archive/`（历史归档）
- 本 PRD 的 2c/2d/2e 笔记也同步改 deepseek-v4-flash

**实现：** model_name 用 `deepseek-v4-flash`（用户给的名）。provider 保持 DEEPSEEK。cost 沿用 deepseek-v4-flash 的单价（v4-flash 真实价未知，估测时沿用，部署后按实际调）。CLAUDE.md 路由表此前 PR#467/#468 已修正为 astron 全局 + POLISH/MOCK_GEN→deepseek-v4-flash；本 PR 改为 deepseek-v4-flash（含 VIRAL_MATCHING 若 2e 已合）。

**风险：** deepseek-v4-flash 是否 DeepSeek 真实可调模型名未验证。部署后若 API 拒该 model_name 需回滚或改回 deepseek-v4-flash。pre-push triple 验证代码层，prod 实调验证模型名。

## 2026-08-09 收尾复核

当前 main 已包含本任务后续合入的可靠性、成本路由和数据库并发优化提交；全量质量门槛
已重新执行：`pytest -q` 为 2153 passed，`ruff format --check`、`ruff check` 和
`mypy backend` 均通过。此前仅记录到 PR #465 的进度已不能代表当前分支状态。

仍未满足本任务 Definition of Done 的外部证据：

- 方向 1 的代码和回归测试已有，当前环境没有可归档的生产轮询前后 DB 写入基线。
- 方向 2 的轻模型路由和 fallback 测试已有，但缺少真实调用的 token/时延 before-after
  样本与内容质量对照；`deepseek-v4-flash` 的真实 provider 可用性也必须由部署调用确认。
- 方向 3/4 的代码变更和单测已随 main 持续合入，但尚未建立统一的生产可靠性/运行时基线报告。

本次只读生产复核还确认：数据库有 2 个已完成 workflow、71 个 checkpoint 和近 30 天 1101 条
`public_ux_events`，但 checkpoint/metadata 没有可归档的 `performance_log`，容器日志也没有
可用于 LLM token/时延或可靠性 before/after 的完整样本。因此这些计数只能证明线上已有观测
数据，不能补足方向 1 的轮询写入基线、方向 2 的真实调用与质量对照，或方向 3/4 的统一可靠性报告。

所以本任务仍保持 `in_progress`：代码层已通过，但不能把“有测试”误写成“已完成可测量收益和
部署后验证”。完成任务还需要在目标部署环境补采样并把结果写入对应 PR/任务记录。
