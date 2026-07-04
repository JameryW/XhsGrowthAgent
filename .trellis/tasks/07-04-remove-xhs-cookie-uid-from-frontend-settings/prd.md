# PRD: Remove XHS_COOKIE/XHS_USER_ID from frontend settings

## Background
扫码登录（QR）已落地（PR #180），cookie 由后端扫码流程写入 `account_credentials` 表。前端设置页手动编辑 XHS_COOKIE / XHS_USER_ID 的入口已冗余，且手动粘贴 cookie 易出错、易泄露。删除手动凭据编辑入口，统一走扫码登录。

## Scope
仅前端 `frontend/src/components/settings/XhsAccountsPanel.vue`。后端凭据存储 / 读取 API（`backend/api/routes/accounts.py`、`backend/db/accounts.py`）保持不变——扫码登录仍依赖。

## Changes
1. 删 `XHS_KEYS` 常量（line 22）。
2. 删整个 credentials 卡片模板（line 354-418）：`v-if="editingAccount"` 的 credentials 区块。
3. 删相关仅服务于手动凭据编辑的函数与状态：
   - `credEdits` ref
   - `isSavingCreds` ref
   - `saveCredentials`
   - `deleteCred`
   - `getCredDisplay`
   - `isCredSet`
   - `startEditCred`
   - `cancelEditCred`
4. `watch(editingAccountId)` 简化：不再 `fetchCredentials` / 清 `credentials`，仅重置选中态。若 `editingAccount` computed 不再被模板引用则一并删。
5. i18n key（`settings.credentialsFor`、`settings.saveCredentials`、`settings.enterValue`、`settings.edit`、`settings.delete`、`settings.notSet`、`settings.willDelete`、`settings.toasts.credsSaved`、`settings.toasts.credDeleted`）若仅此文件用则删；跨文件用则留。

## Non-Goals
- 不动后端凭据表 / API。
- 不动 QrLoginModal。
- 不动 account 列表 / 创建 / 激活 / 删除 / 登录状态刷新逻辑。

## Out of Scope
`store.credentials`、`store.fetchCredentials`、`store.saveCredentials`、`store.removeCredential`（accounts store）——若删干净后 store 内仍保留这些方法但不被调用，留作后端 API 客户端能力，不强制清理（避免扩大 diff）。

## Verification
- `npm run build` 通过（无未使用变量 / 模板引用错误）。
- 设置页打开：account 列表正常，无凭据卡片，扫码登录按钮可用。
- 无控制台报错。
