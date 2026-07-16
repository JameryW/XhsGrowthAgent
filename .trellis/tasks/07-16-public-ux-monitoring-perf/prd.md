# 公开页性能审计与遥测基线补齐

## 目标

在不改变公开案例默认私有策略的前提下，补齐 Showcase / Workflow Replay 的可重复性能证据，并把现有匿名聚合遥测接入认证后的 Settings 基线面板。

## 范围

- 审计脚本采集 LCP、CLS、warm reload 和缓存步骤切换耗时，并保留 axe serious/critical、键盘和横向溢出检查。
- 优化 Replay 步骤切换，使结果加载与 URL 同步不互相阻塞。
- 在 Settings 增加仅认证可见的公开页遥测聚合面板；不展示原始 case/public id、正文或用户内容。
- 为新增 API 类型、面板行为和性能门槛补充测试与部署证据。

## 验收标准

- 前端全量测试、type-check、生产构建通过。
- 全矩阵公开页审计：live empty 通过；96 个合成非敏感 fixture 页面通过；axe serious/critical 为 0；无横向溢出；键盘阶段切换通过。
- 审计 JSON 明确记录 LCP、CLS、warm reload、cached select-to-render 分布；缓存步骤切换超过 100ms 时失败。
- Settings 面板可按 1/7/14/30 天刷新并展示匿名聚合数量、p50/p75；请求可取消，接口失败可重试。
- 不发布真实案例；真实案例负责人授权、真实截图/视觉签字、真实冷/热性能和真实内容 axe 仍作为业务发布门槛保留。

## 非目标与风险

- 本任务不修改任何真实案例的 public/featured 状态。
- 合成 fixture 只能证明实现和回归路径，不能替代真实案例授权及最终视觉验收。
- 生产遥测接口继续依赖认证和现有隐私聚合逻辑；无有效管理员凭据时只验证未授权保护和前端失败态。
