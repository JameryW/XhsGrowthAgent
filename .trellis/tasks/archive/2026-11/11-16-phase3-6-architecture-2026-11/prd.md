# 第 3–6 期架构契约升级

## 目标

把「XhsGrowthAgent 架构演进台账」第 3–6 期方案 13–36 落成可测试、可回滚的确定性契约模块，并提供低风险接线。默认不改变既有工作流、模型路由、SSE 和发布行为。

## 范围

1. **第 3 期（13–18）**：`backend/services/content_launch.py`
   - 多模态图文协同冷启动评分（互补性、缩略图可读性、垂类美学）
   - TagLLM 三层标签蒸馏（核心/实体/长尾，5–8 个）
   - review 风险信号条（发布资格、质量门、新颖度、PLAD、Creator 规则）
   - Playwright/CDP 多账号三态熔断器
   - workflow 根因分类与单篇 Token 成本
   - durable workflow event 的 SSE 帧格式
2. **第 4 期（19–24）**：`backend/services/temporal_contracts.py`
   - 草稿 CAS revision 与 `DraftAnalyticsSnapshot`
   - TimePop 24h/7d 正余弦特征与 48 槽位
   - 非线性自抑制 Hawkes 核
   - `compile_jit_subgraph` 模式计划
   - A/B/C 三维叙事锚点
   - Ripple `timed_out` 分阶段抢救与 fallback
3. **第 5 期（25–30）**：`backend/services/evaluation_contracts.py`
   - 能力路由策略（默认保持 magpie）
   - GRS/GAR 组内相对评审
   - PTGS 动态温度
   - APMD 锚点重置与香农熵
   - 封面安全区/对比度/缩略图自检
   - SWA 冻结前缀 + ≤160 token 尾部锚点
4. **第 6 期（31–36）**：`backend/services/distribution_contracts.py`
   - EGMF 曝光限流诊断与可信度
   - SAIM trend/brief/free 场景权重
   - 多图滑动留存弧与 AVTP Token 分配
   - BreakoutLift 黑马挖掘
   - FanRelationStore 与置顶破冰
   - 公开 replay 确定性脱敏 bundle

## 接线

- evaluator 的 `publish_eligibility` 之后追加 `risk_signals` 字段，供 review 页使用。
- 其余模块先作为纯函数契约，由后续节点按需 opt-in；不改变默认图拓扑。

## 验收

- 4 个新模块各有单测，覆盖正常/边界/阻断路径。
- 既有 evaluator、context、publisher、API 测试通过。
- `ruff check` / `ruff format --check` / `mypy --python-version 3.12 backend` / 全量 `pytest` 通过。
- README.zh-CN.md 增加第 3–6 期契约表。
