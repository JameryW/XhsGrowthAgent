# Public UX 技术收尾与发布门槛

## 目标

在真实案例和人工业务签字尚未具备的前提下，继续完成 Showcase / Workflow Replay 的可执行技术优化：让匿名监控能够区分缓存与非缓存回选，Settings 面板直接呈现性能预算状态；补齐请求竞态、失败恢复和路由入口的回归证据；把线上发布检查和回滚预演写成可重复、无破坏性的命令。不得伪造真实案例、管理员登录或视觉签字。

## 范围

1. Telemetry 聚合保留 `cached` 这一匿名布尔维度，前后端类型和 Settings 展示同步；不保存任何 public ID、账号、正文、URL 或原始错误。
2. Settings → 公开页体验监控：首个结果和缓存回选卡片显示预算、通过/超标/暂无数据状态；明确“缓存回选”只使用 `cached=true` 的聚合行，避免把网络请求混入 100ms 门槛。
3. 组件测试覆盖：缓存/非缓存分组、状态标签、空数据、刷新失败恢复、过期请求不覆盖新周期。
4. 更新公共页验收文档和 PRD 证据，说明真实案例授权、真实 Lighthouse、人工视觉验收和灰度回滚仍是外部门槛。
5. 仅做可重复的健康/私有默认/缓存条件请求/构建验收；不执行破坏性数据库恢复或未经授权的公开案例变更。

## 非目标

- 不创建或发布真实 public case。
- 不冒充管理员完成 Settings 真实登录验收。
- 不把合成 fixture 的性能数据写成真实案例数据。
- 不改变已有暗黑模式、favicon、公共 DTO 或发布 API 的隐私边界。

## 验收标准

- [x] telemetry summary 返回 `cached` 聚合维度，已有调用和旧数据（`NULL`）保持兼容。
- [x] 监控面板只将 `cached=true` 行用于 cached select-to-render p75；无该数据时显示“暂无数据”，不显示 0ms 假通过。
- [x] 两种语言、明暗模式、键盘可访问性和 44px 触控目标保持通过。
- [x] 前端全量测试（43 files/546 tests）、类型检查、构建；后端 telemetry 单测、ruff、mypy 通过。
- [ ] public UX audit online 全矩阵和 Slow 4G/Save-Data 代表性样本可重复；输出保留预算失败观测但不误判慢网发布门槛。
- [ ] PRD/部署文档记录本轮证据与未完成的真实业务门槛。

## 当前验证记录

- 前端：`npm -C frontend run test:run` 通过（43 files、546 tests）；`npm -C frontend run type-check` 和 `npm -C frontend run build` 通过，保留既有 chunk warning。
- 后端：`pytest -q tests/unit/api/test_public_telemetry.py tests/unit/db/test_public_telemetry.py` 通过（4 tests）；`python -m mypy backend`、ruff、format、`git diff --check` 通过。
- 全量 `pytest -vv --maxfail=1` 在既有集成探针 `tests/integration/test_api_routes.py::TestHealthCheck::test_health_returns_success` 等待本机服务，未产生断言失败；线上部署后的 health/audit 作为最终证据。

## 发布与回滚

本任务只允许 additive 变更。发布前执行构建、健康检查、私有默认和 audit；若面板或聚合返回异常，前端可回滚到上一版本，telemetry 接收端继续 best-effort。数据库恢复仅在明确批准后执行，本任务不自动触发。
