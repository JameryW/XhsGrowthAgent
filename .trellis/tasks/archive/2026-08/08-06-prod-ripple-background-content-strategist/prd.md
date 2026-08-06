# prod 开启 RIPPLE_BACKGROUND — content_strategist 异步化

## 背景
content_strategist 是工作流最慢节点（memory 记 prod 352s），根因：`RIPPLE_BACKGROUND` 未设 → 默认 `background=False`（`backend/config/settings.py:89`）→ `content_strategist.execute` 走同步路径（`content_strategist.py:210` `asyncio.gather(_predict(), _validate_pmf())`），主链阻塞等两个 Ripple 调用，最多 `RIPPLE_WORKFLOW_TIMEOUT=1800s`。

代码已完整支持 background mode：
- `content_strategist.py:165` background 分支 fire-and-forget（`_schedule_ripple_background`）
- graph 已接 `ripple_finalize` + `ripple_late_recheck` 节点（`graph/builder.py:105,110`）
- PR#466 修了 background 丢数据漏洞 + stale-store race（memory: ripple-background-late-recheck）

**只差 env 开关**。deploy.sh / .env.example / 容器 env 均未设 `RIPPLE_BACKGROUND`。

## 需求
prod 开启 `RIPPLE_BACKGROUND=1`，content_strategist 不再阻塞主链等 Ripple，改后台跑 + late_recheck 恢复结果。

## 方案
1. `scripts/deploy.sh` 加 `-e RIPPLE_BACKGROUND="${RIPPLE_BACKGROUND:-1}"`
2. `.env.example` 加 `RIPPLE_BACKGROUND=1` + 注释
3. （可选）`settings.py:89` 默认 `background=True` — 让默认行为即安全异步。讨论：env 显式更可控，还是改默认？倾向改默认（部署即安全，避免漏配）。
4. 零代码逻辑改动（background 分支已实现 + 测试）

## 风险
- **数据正确性**：background mode 曾丢数据（PR#466 前）。需确认 PR#466 修复完整：
  - late_recheck 节点 bounded poll 恢复晚到预测
  - stale-store race（reangle 时清旧结果，`_safe_store_delete` line 368）
  - interrupt 只能节点内
- **测试覆盖**：`tests/unit/agents/test_content_strategist*` 需覆盖 background 路径
- **降级**：background 失败不能丢结果——`_schedule_ripple_background` `_on_done` callback 已 log error，late_recheck 兜底

## 验收
- prod `RIPPLE_BACKGROUND=1` 生效，content_strategist 秒级返回（Ripple 后台跑）
- 跑一个完整工作流，确认 Ripple 结果经 late_recheck 正确写入 state（非丢数据）
- 现有 content_strategist 测试全绿，新增 background 路径测试
- `/health` ripple_cas ok
- before/after：content_strategist 节点耗时 352s → <10s（Ripple 后台）

## 非目标
- 不改 Ripple 调用逻辑本身
- 不改 late_recheck 节点逻辑（PR#466 已实现）
- 不动 sync mode 代码（保留 fallback）

## 待定（brainstorm）
- 改 `settings.py` 默认 vs 仅 env？倾向改默认 + env 覆盖。
- 是否需先补 background 路径测试再开？是——先验证 PR#466 修复完整。
