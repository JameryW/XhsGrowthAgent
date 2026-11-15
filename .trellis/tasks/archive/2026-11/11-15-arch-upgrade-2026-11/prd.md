# 架构升级：因果预测、搜索质量门、PLAD、记忆效用、排水契约与仿真

## 背景

基于 2026 年小红书算法论文（OranSim / SearchLLM / GRM-SAM / RedNote-Vibe-PLAD）、LangGraph 生产运行契约（arXiv:2610.34620）与 MCP-Persona，对 XhsGrowthAgent 做全面架构升级。目标是在**不破坏现有确定性内核与发布安全**的前提下，新增六个可独立测试的能力层。

## 需求（六条工作流）

### 1. Collect-First 预测引擎（`backend/tools/analysis/collect_first.py`）
- 四头 `log(1+y)` 预测：reads / likes / collects / comments。
- 特征：文本 64 维压缩表示（无外部模型时用确定性字符 n-gram 投影）、粉丝数对数、媒体类型、标签数、发布时间周期、笔记年龄 γ/180。
- 排序契约：预测收藏量优先；同分按 14 天累积模拟响应质量（cumulative simulated response mass）排序。
- 指数核 Hawkes：`fit_hawkes(snapshots)` 从 `/analytics <id>` 最近 10 次快照估计 μ、β；`diffusion_curve` 生成 14 天曲线。
- 固定随机种子的配对特征替换（paired feature substitution）用于低方差反事实比较。
- 接入 `topic_scorer`：输出 `predicted_collect` 与 `collect_first_rank` 字段（附加、不破坏旧字段）。

### 2. SearchLLM 双层质量门（`backend/services/quality_gate.py` + evaluator）
- Layer I Soft-AND：`gate = ∏ σ((s_k − τ_k)/T)`；任一底线维度显著低于阈值时总分趋近 0。
- Layer II：加权效用和（保留原 evaluator 权重）。
- `R_RQGM = gate × Σ w_j u_j`；默认 gate 仅在存在低于阈值的 Layer I 维度时生效，保持既有测试/历史分数兼容。
- 新增确定性 `search_geo` 维度（标题长度、Answer-First 前三行、长尾搜索词/分点结构、标签合规），作为非加权 advisory 维度输出。
- evaluator 结果增加 `quality_gate` 字段（layer1_scores、gate_factor、geo_readiness）。

### 3. PLAD 心理语言学体检（`backend/tools/content/plad.py`）
- 31 项可计算特征，覆盖 4 组：情感与社会锚定、认知架构、词汇身份与风格签名、文本衔接流。
- 输出 `PladReport`：`ai_likelihood`（0-1）、`burstiness`、`connective_density`、`first_person_scene_ratio`、`emotion_volatility`、`violations`。
- `plad_constraints(report)` 生成可注入 `TaskType.POLISH` 的结构化约束。
- 接入 `de_ai_taste.polish_copy`：润色前计算 PLAD，把超标维度写入 revision_hints。
- 账号历史新颖度惩罚：`backend/tools/content/novelty.py` 计算最近 30 篇最大余弦相似度，>0.82 扣分并换角度（接入 `topic_scorer` 可选参数）。

### 4. 上下文记忆效用与双库聚合
- `backend/context/compiler.py` 的 `apply_item_budget` 新增 `overlap_penalty`：按已选片段 token 重叠率惩罚边际效用（`Δ̂_i / d_i(S)`），默认 0.15，可通过 `XHS_CONTEXT_OVERLAP_PENALTY` 覆盖。
- `backend/memory/hy/bridge.py` 的 `list_memories` 聚合 chat 向量库与 working/coding store；失败时返回已获得的一侧并记录警告。
- `pyproject.toml` 的 `memory-hy` extra 升级为 `hy-memory>=2.0.16`。
- 新增 `backend/memory/hy/promotion.py` 的 Outcome-Verified Epistemic Gate：绩效高于近 10 篇中位数 1.2× 或人工批准才可晋升 `verified_pattern`，否则进 `negative_pitfalls`。

### 5. 容器排水契约与幂等读回（`backend/db/execution_leases.py` + API lifespan）
- `start_drain()` / `is_draining()` / `drain_release_all()`：SIGTERM 时标记 draining、拒绝新租约、释放本实例持有的租约。
- `acquire_outcome` 在 draining 时返回 `DRAINING`（新增枚举值）。
- `backend/api/app.py` lifespan shutdown 最先调用 `drain_release_all()`（5–10 秒上限），再执行其他关闭。
- `backend/services/publish_intent.py` 或 publisher 提供 `readback_unknown_publishes()`：启动/接管时对 `UNKNOWN` 发布记录读回核实，已发出则补 CONFIRMED，绝不重发。

### 6. 视觉衰减与 Context-Tree 仿真
- `backend/services/visual_analysis.py`：`decay_weight(observed_at, now, half_life_days=14)` + `weighted_distribution`；`SceneAnalysisResult` 增加可选 `as_of` 字段，推荐排序使用时间衰减权重。
- `backend/services/context_tree_sim.py`：MCP-Persona 式有状态实体树 `User → Account → Post/Draft → Comment/DM`，确定性校验标题 ≤20 字符、正文 ≤1000、违禁词、`signature_unavailable`、频控/私信配额；`simulate_publish()` 返回结构化模拟结果。
- `PublisherAgent.execute` 的 dry-run 分支调用 `simulate_publish`，结果中带 `simulator` 轨迹，保持 `status="mock_published"` 兼容。

## 验收标准

- 新增单元测试覆盖每个模块的核心契约（≥ 6 个测试文件）。
- `pytest` 相关既有测试（evaluator、context compiler、execution leases、publisher）全部通过。
- `ruff check` / `ruff format --check` 通过。
- 所有新代码默认配置下不改变既有生产路径行为（质量门默认仅对低于阈值的维度生效；上下文重叠惩罚默认温和；dry-run 仍返回 mock_published）。
- 文档：README.zh-CN.md 增补「2026-11 架构升级」章节，列出六个能力与开关。
