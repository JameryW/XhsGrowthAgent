# 文档可验证陈旧内容修正（票 5ar）

> 来源：本轮继续收口时的实测 —— 多处文档仍写**旧包名** `xhs_growth` 的 Python 导入/路径
> （照抄即报错）、`error-handling.md` 的错误类表与实际类不符、agent-os 对
> `engagement_effects` 账本形状与 `expect_version` 使用现状描述过宽、未提已存在的
> `scripts/benchmarks/llm_route_benchmark.py`。全部是“拿代码一验就知”的 C 类问题。

## 1. 目标

把**可被代码验证**的陈旧文档内容修正到与树一致；不碰真实数据值（数据库名 `xhs_growth`、
日志命名空间 `xhs_growth.*`、HY-MEMORY source 标签等**是值，不是包路径**，保持不动）。

## 2. 已核实的事实（修前）

| 文档 | 陈旧内容 | 代码事实 |
|---|---|---|
| `docs/deployment.md` | `uvicorn xhs_growth.api.app:app`（3 处）、`# xhs_growth/api/app.py` | 包已改名 `backend`；`backend.api.app:app` 可导入 |
| `docs/testing-guide.md` | `--cov=xhs_growth`、`from xhs_growth.state.enums import WorkflowPhase` | 覆盖率源应为 `backend`；`backend.state.enums.WorkflowPhase` 存在 |
| `docs/configuration.md` | `from xhs_growth.config.settings import Settings`、`from xhs_growth.models.router import get_model` | `backend.config.settings.Settings`、`backend.models.router.get_model` 均存在 |
| `docs/error-handling.md` | 路径 `xhs_growth/api/errors.py`、`xhs_growth/services/xhs_client.py`；表里有 `NotFoundError` / `WorkflowError` / `RateLimitError` / `InternalError` | 实际类：`APIError`、`ValidationError`(400)、`WorkflowNotFoundError`(404)、`ReviewNotPendingError`/`ChoiceNotPendingError`(400)、`AuthenticationError`(401)+`TokenMissingError`/`TokenInvalidError`/`LoginFailedError`，另有 creator-agent 专属错误；`backend/api/errors.py` 无表里那四个类 |
| `docs/agent-os-upgrade-2026q4.md` | 互动 Effect 只写“`engagement_effects`（提交前 claim）” | 实际是 **DB 级唯一约束账本**（`(account_id, idempotency_key)` UNIQUE + `INSERT ... ON CONFLICT DO NOTHING`）+ CAS 状态迁移（`backend/db/engagement_effects.py`、`backend/services/xhs_effect_ledger.py`） |
| 同上 §5.1 | 只写 `mark(..., expect_version=N)` 能力与 BaseStore 无 CAS | `backend/agents/publisher.py` 的 publish 写入点**不传** `expect_version`（并发正确性靠租约 + DB 唯一约束），doc 应写明现状 |
| 同上 P3 | 未提已存在的评测铺垫脚本 | `scripts/benchmarks/llm_route_benchmark.py` 存在（P3 评测集铺垫） |

## 3. 要求

1. `docs/deployment.md`：只改 Python 模块路径 4 处（保留 `xhs_growth` 数据库名/用户等值）。
2. `docs/testing-guide.md`：改覆盖率源与 import 路径。
3. `docs/configuration.md`：改两条示例 import。
4. `docs/error-handling.md`：改路径；把 API 错误表换成本仓真实类（并说明 creator-agent 专属错误家族只列代表），XHS 平台错误表补 `XHSSignatureUnavailableError`。
5. `docs/agent-os-upgrade-2026q4.md`：
   - 互动 Effect 形状改为“DB 级唯一约束账本 + 提交前 claim + CAS 状态迁移”（`docs/tool-gateway-engagement-migration.md` §5 已是权威描述，这里只补形状）；
   - §5.1 乐观锁行补诚实边界：publish 写入点今天不传 `expect_version`；
   - §5 P3 行补一句 `scripts/benchmarks/llm_route_benchmark.py` 是评测铺垫。
6. `docs/execution-plane.md`：票 5aq 的等价重构（`ripple_service.py` 把两处函数内 `import time as _time`
   提升到模块级，净行数 -2/+1）令 §6 三条 `ripple_service.py` 锚点漂移，按实际行号重映射
   （`:821→:818`、`:280→:281`、`:230→:231`）——这是 5aq 引入的文档漂移，在本票一并修掉。
7. 验证：`python -c` 导入文档里写的每个模块；`pytest tests/unit/scripts/test_docs_citations.py::test_the_corpus_is_the_markdown_we_own ...::test_every_cited_line_number_in_the_corpus_resolves`、`test_docs_anchors.py` 绿；`ruff` 不适用（md）。

## 4. 验收

- [x] 文档中不再有 `xhs_growth.` 形式的 Python import（数据库名/日志命名空间/source 标签除外；复查仅剩 `xhs_growth.memory.hy` logger 命名空间，属真实值）
- [x] error-handling.md 的表里每个类都能在代码里找到（AST 校验 8 个 API 类全部存在；XHS 5 类存在）
- [x] agent-os 两条描述与代码一致（账本形状、expect_version 现状）
- [x] 文档门禁测试绿（anchors + execution-plane claim 重算 + residue claim 重算 + citation corpus 共 8 passed）

## 5. 不做什么

- 不改代码；不改数据库名 / logger 命名空间 / HY-MEMORY source 等真实值。
- 不重写整篇 guide 的结构。
