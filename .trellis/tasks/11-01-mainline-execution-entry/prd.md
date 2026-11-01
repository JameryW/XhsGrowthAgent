# P3b-2：主链单一控制面执行入口（票 5bg）

> P3 的收口切片：三条主链发布路径（workflow 节点 / publish-retry / free）不再各自直调
> `run_publish`，而是统一经控制面执行入口；入口负责**决定身份**，实现体私有化。
> 这是 `mainline_run_publish_direct_call_sites` 3→0 的那一步。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 三处直调：`PublisherAgent.execute`、publish-retry、free publish | `run_publish(` AST scan（旧 claim=3） |
| 三条路径都经 Gateway `xhs.publish`，且 shared PublishRequest（P3a） | 票 5be + P1c-S3 |
| review 审批身份写在 `state["publish_decision"]`（票 5bc） | `review.py` |
| free 发布无 review、但有认证操作员（`user["id"]`） | `free.py` 的 `/free/publish` |
| 执行器已能执行 mainline-origin intent（票 5bf） | `execute_action` mainline 分支 |
| 单据身份纪律：不发明账号、不伪装 review | 待决问题 1 裁决 + P1b |

## 2. 决定（locked）

1. 新模块 `backend/creator_agent/mainline_publish.py`：
   - `execute_mainline_publish(state, store, *, agent=None, operator_id="")`：
     - 已有 `publish_decision` → **原样传递**，入口不改写审批；
     - 无 decision 且给了 `operator_id` 且发布有账号 → 合成操作员身份
       （`decision_id="mainline:operator:<uuid>"`、`source="free_publish_operator"`、
       thread/account/内容哈希/approved_by/at），**不伪装 review**；无账号则不合成；
     - 其余（legacy retry / 部署本体）无身份照旧执行（不产 intent）；
     - 合成身份只落在状态的浅拷贝上，**不修改调用方 mapping**。
2. `publisher._run_publish_attempt`：原 `run_publish` 改名私有化；`PublisherAgent.execute`
   改调入口。遗留 `run_publish` 别名仅为既有 import/测试保留（backend 内零调用）。
3. `_wf_actions`（retry）与 `free` 改调入口；retry 传 `operator_id=user["id"]`
   （显式重试本身就是操作员决定），free 同样传认证用户 id。
4. claim `mainline_run_publish_direct_call_sites` **3 → 0**；按 residue claims 规则补
   **zero-claim 阳性对照**（合成树里一个真调用 + 一个别名赋值，扫描器必须只数前者）。
5. 文档：残留条目、起点表、claim 表、P3/P4 段落同步；`docs/execution-plane.md` 的
   行号锚点随代码位移更新。
6. 不动 `EffectLedger` 六态/幂等语义；不假装已切到 `execute_action` 回执路径（P4）。

## 3. 要求

1. 新 `backend/creator_agent/mainline_publish.py`（入口 + 操作员身份）。
2. `backend/agents/publisher.py`：私有化 attempt、节点改调入口、补兼容别名说明。
3. `backend/api/routes/_wf_actions.py`、`backend/api/routes/free.py`：改调入口并传 operator。
4. 测试：
   - 新 `tests/unit/creator_agent/test_mainline_publish_entry.py`（5）：审批原样传递且
     不 mutation、free 操作员身份字段（source/id/account/thread/hash/by/at）、无 operator
     不造身份、无账号不造身份、已有审批不被 operator 覆盖；
   - 更新 retry/free 路由测试 patch 目标；
   - `test_residue_claims.py` 增加 `_run_publish_calls` 阳性对照。
5. 文档/锚点：claim 0 + 残留/起点/阶段段/执行平面锚点。
6. 验证：定向（retry/free/run_publish/entry/doc gates）+ 全量 + ruff 绿。

## 4. 结果（2026-11-01）

- [x] 单一入口 + 私有实现 + 三路径切换
- [x] free/retry 的操作员身份（账号绑定、不伪装 review）
- [x] claim 3→0 + zero-claim 阳性对照
- [x] 定向 181 + 5 + doc gates 98 绿；全量见 notes

## 5. 不做什么

- 不删遗留别名/claim 行（P4）、不把实现体移入入口背后（P4）、不改六态语义。
- 不把 free 发布伪装成 review 审批。
