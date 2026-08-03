# QR 登录验证码显示条件优化

## 背景

扫码登录弹窗在 `scanned` 状态下无条件显示数字验证码输入框。后端返回
`verification_required: false` 时，用户已经完成扫码且不需要二次校验，但仍会
看到“输入验证码”的表单，造成误导。

## 目标

让验证码输入框严格跟随后端的 `verification_required` 信号：只有后端明确要求
二次校验时才显示。

## 范围

- 修改 `frontend/src/components/settings/QrLoginModal.vue` 的派生显示状态。
- 新增组件回归测试，覆盖无需验证码、需要验证码和已确认三种状态。
- 不调整 QR API、后端登录流程或验证码提交逻辑。

## 验收标准

1. `scanned + verification_required=false`：显示扫码状态，不显示验证码输入框。
2. `scanned + verification_required=true`：显示验证码输入框及二次校验提示。
3. `confirmed`：不显示验证码输入框。
4. `waiting`、`expired` 等状态的二维码和刷新行为保持不变。
5. 前端类型检查和相关 Vitest 测试通过。

## 技术方案

将 `showVerificationCodeInput` 定义为 `verificationRequired` 与未确认状态的合取，
继续复用已有的 `verificationRequired` 文案和提交逻辑，避免在模板中重复判断。
