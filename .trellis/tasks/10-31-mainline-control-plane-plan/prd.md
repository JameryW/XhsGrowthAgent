# 主链迁移控制面：分阶段方案（票 5au）

> B 类裁定（用户 2026-10-31 拍板：迁移）。本票交付**方案与阶段切分**，不改生产代码。
> 依据：`docs/publish-action-protocol.md` 的「已知残留」与控制面链路；claim 表 =
> `mainline_run_publish_direct_call_sites=3`、`mainline_action_intent_producers=0`。

## 1. 现状（已核实）

- 主链 3 处直接调 `run_publish(...)`：`backend/agents/publisher.py`、`backend/api/routes/_wf_actions.py`（publish-retry）、`backend/api/routes/free.py`。
- 控制面链路（intent → policy → confirm → execute → receipt）今天只在 creator_agent API 路径上；
  主链没有 `ActionIntent` 生产者（0 个），也没有 policy gate。
- 待决问题 1 已裁：迁移时 `account_id` 必须显式解析，**不得发明账号**。

## 2. 决定（locked）

1. 迁移分四阶段，每阶段独立可回滚；**不一次性替换发布执行器**。
2. 阶段顺序按「先让意图可表达、再让策略可执行、最后才换执行器」。
3. 每阶段结束更新 claim 表（`test_residue_claims.py` 会重算）；残留散文同步改。
4. 不引入 `PublishIntent` 这个不存在的名字；线上一律用 `ActionIntent`。

### 阶段划分（写入 `docs/publish-action-protocol.md`）

- **P1 账号解析 + 意图生产者**：主链发布前显式解析 `account_id`（缺失则拒绝，不落 `""`/`default`），
  构造 `ActionIntent`（kind=publish）但**仍由 `run_publish` 执行**；claim：producers 0→N，direct calls 3 不变。
- **P2 策略门禁**：在构造 intent 后调用 `creator_agent` 的 policy 评估（复用同一份规则，不复制），
  拒绝路径返回 typed 结果（不写 receipt）；claim 不变。
- **P3 换执行器**：publish 执行改走 Tool Gateway `xhs.publish` + `granted_scopes`（复用
  `creator_agent.execution` 的 dispatcher seam），`run_publish` 降为工具实现；direct calls 3→0。
- **P4 收口**：删除直调残留与旧分支，claim 归零，残留条目删除。

## 3. 要求

1. 在 `docs/publish-action-protocol.md` 插入「主链迁移控制面：阶段方案」章节（含每阶段验收、claim 迁移、回滚）。
2. 更新「已知残留」第一条：保留事实（主链仍不经控制面），追加「迁移方案见本文章节 + 票 5au」。
3. 不修改 claim 表数值（本票无代码）；`test_residue_claims.py`、doc citations、anchors 全绿。
4. 在 `.trellis/tasks/.../prd.md` 记录本票为「方案票」，后续代码票从 P1 开。

## 4. 验收

- [x] 方案章节含四阶段、每阶段 claim 变化与验收命令
- [x] 残留条目指向方案；doc gates 绿（residue claims + anchors + citations 共 7 passed）
- [x] 无生产代码改动（git diff 仅 docs/publish-action-protocol.md + task dir）
