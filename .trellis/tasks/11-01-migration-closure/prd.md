# P4：主链迁移收口（删遗留符号/claim 行/残留）（票 5bh）

> 5au 四阶段迁移的最后一步：P1（intent/material）、P2（policy）、P3a（共享请求）、
> P3b-1（mainline 执行器）、P3b-2（单一入口）已完成。P4 负责删除 P3 期保留的兼容面，
> 并让文档/claim 与代码形状一致。

## 1. 已核实的事实

| 事实 | 证据 |
|---|---|
| 三条主链路径已统一经 `execute_mainline_publish` | 票 5bg；`backend/creator_agent/mainline_publish.py` |
| 实现体 `_run_publish_attempt` 私有 | `backend/agents/publisher.py` |
| 遗留 `run_publish` 别名仅测试使用（backend 零调用） | AST scan（旧 claim=0） |
| claim 行 `mainline_run_publish_direct_call_sites` 仍发布 0 | 票 5bg 文档 |
| residue-claims 规则：zero claim 必须有阳性对照 | `tests/unit/scripts/test_residue_claims.py` 头注释 |
| P4 验收允许分支 A：实现体在入口背后（不强制 execute_action 回执路径） | 票 5bg 更新后的 P4 段 |

## 2. 决定（locked）

1. **删除 `run_publish` 别名**；实现体只被 `execute_mainline_publish` 调用。
   测试改用 `from backend.agents.publisher import _run_publish_attempt as run_publish`。
2. **新增 AST 不变量测试**：`_run_publish_attempt` 在 backend 中唯一调用点是
   `creator_agent/mainline_publish.py`；任何人绕过入口直接调用即红。
3. **删除 claim 行** `mainline_run_publish_direct_call_sites`（连同 `_run_publish_calls`
   扫描器、`_CLAIMS` 条目、对应阳性对照）；为仍存在的 zero claim
   `ripple_service_direct_call_sites_in_api_routes` 补阳性对照，保持“zero claim 可被
   证明扫描器没坏”的规则。
4. **文档收口**：`publish-action-protocol.md` 的残留/起点表/claim 表/P3/P4 段；`execution-plane.md`
   与 `agent-os-upgrade-2026q4.md` 中提到旧符号的执行边界描述；代码 docstring 同步。
5. **明确未采用的分支**：入口直接落到控制面 `execute_action` 回执路径（P4 分支 B）不做，
   因为主链需保留 `EffectLedger` 六态/幂等键语义；写在 P4 段落，供将来单独开票。

## 3. 要求

1. `backend/agents/publisher.py`：删别名与相关注释。
2. `tests/unit/agents/test_run_publish.py`：私有导入别名。
3. `tests/unit/creator_agent/test_mainline_publish_entry.py`：新增单调用点 AST 测试。
4. `tests/unit/scripts/test_residue_claims.py`：删旧扫描器/claim/阳性对照；补 ripple 阳性对照。
5. 文档四处同步；`docs/execution-plane.md` 锚点随格式变化更新。
6. 验证：定向 + 全量 + doc gates + ruff 绿。

## 4. 结果（2026-11-01）

- [x] 别名删除；单调用点不变量测试
- [x] claim 行/扫描器/残留声明删除；ripple zero-claim 阳性对照补齐
- [x] 文档/锚点/代码 docstring 同步
- [x] 定向（run_publish+api+entry）与全量见 notes

## 5. 不做什么

- 不做 P4 分支 B（executor `execute_action` 回执接管主链）——需要先让执行器吸收六态账本。
- 不动 `EffectLedger` 语义/公开 API。
