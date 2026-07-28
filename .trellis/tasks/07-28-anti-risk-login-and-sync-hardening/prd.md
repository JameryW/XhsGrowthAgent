# anti-risk-login-and-sync-hardening

## 目标

降低小红书登录/同步风控命中率，并在命中后阻止用户连点放大风险。

1. **扫码冷却**：同账号 N 秒内禁止再次 `POST /login/qr`
2. **300012 熔断**：检测到 IP/安全限制后封锁扫码 M 秒，前端禁用按钮并展示提示
3. **清 cookie 收敛**：www_only 时先暖 creator home 尝试补 token；失败再清 cookie 弹码
4. **出口探测**：启动扫码前/中识别 security page，结构化 `risk_code`
5. **同步 auth 失败退避**：AUTH_EXPIRED / 空壳页后加长 cooldown，避免短时连撞
6. **配置项**写入 `docs/configuration.md` + Settings

## 非目标

- 不解决机房 IP 本身（需用户换网络）
- 不引入第三方住宅代理
