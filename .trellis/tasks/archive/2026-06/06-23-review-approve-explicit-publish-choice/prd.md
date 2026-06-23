# 审批通过强制选择试运行/真实发布

## Goal

审批通过（approved）时，发布模式必须由用户显式选择，不能有预选默认值偷偷走 mock 发布。
解决痛点：当前 `publishDryRun = ref(true)` 默认试运行，用户没注意开关就直接 mock_published，
工作流 completed 却没真发。

## Requirements

- 审批通过弹窗中，发布模式无预选默认（每次打开重置为「未选」）
- UI：两张可选卡片（试运行 / 真实发布），点击高亮选中
- 用户未显式选择时，确认按钮 disabled
- 选择"真实发布"时显示实时警告
- 选"真实发布"且 `use_browser=false` 时，额外提示"当前环境无法真实发布"
- 选择器结构可扩展（后续可加定时/私密发布卡片）
- 后端 `_check_xhs` health payload 暴露 `use_browser` 给前端

## Acceptance Criteria

- [ ] 审批通过弹窗打开时，发布模式为未选，确认按钮 disabled
- [ ] 选"试运行"→ 确认可点，后端收到 `dry_run=true`
- [ ] 选"真实发布"→ 显示实时警告，确认可点，后端收到 `dry_run=false`
- [ ] `use_browser=false` 且选真实发布时，提示环境无法真实发布
- [ ] 每次重新打开弹窗，选择重置为未选
- [ ] zh-CN + en 两套 i18n key 补齐
- [ ] `/api/system/health` 的 `xhs_platform` 含 `use_browser` 字段

## Definition of Done

- 前端 lint/typecheck/build 通过
- 后端 ruff/mypy 通过
- i18n 双语补齐
- 行为变更不影响非审批调用方（后端 review.py 默认 dry_run=True 保留作安全兜底）

## Technical Approach

### 前端 `frontend/src/views/Review.vue`
- `publishDryRun = ref(true)` → `publishMode = ref<'dry' | 'live' | null>(null)`
- 弹窗内 toggle 替换为两张卡片（dry / live），点击设值
- `executeDecision`（:318-319）发 `{dry_run: publishMode.value === 'dry', account_id}`
- confirm 按钮 `:disabled="publishMode === null"`
- 打开弹窗时（approved 分支 :304-308）重置 `publishMode.value = null`
- `use_browser` 状态从 system health 的 `xhs_platform.use_browser` 读（已有 system store/api 可复用）
- 选 live 且 use_browser=false → 显示第二条警告

### 后端 `backend/api/routes/system.py`
- `_check_xhs` 返回值加 `"use_browser": os.environ.get("XHS_USE_BROWSER","").lower()=="true"`

### i18n `frontend/src/locales/{zh-CN,en}.json`
- 复用 dryRun / dryRunHelp / liveWarning
- 新增：modeLabel / modeRequired / liveCardTitle / dryCardTitle / dryCardDesc / liveCardDesc / useBrowserOffWarning

## Decision (ADR-lite)

**Context**: 默认 `publishDryRun=true` 导致审批通过后静默走 mock，用户以为发了其实没发。
**Decision**: 强制显式选择——两张卡片无预选，未选禁用确认；后端暴露 use_browser 让前端提示环境级拦截。
**Consequences**: 每次审批多一步点击；非 UI 调用方仍走后端 dry_run=true 安全默认；use_browser 关闭时即便选真实发布也只提示不阻断（实际由 publisher 兜底 mock）。

## Out of Scope

- `use_browser=false` 时 publisher.py:36 的强制 mock 本身（只提示，不改 publisher 逻辑）
- `auto_publish` 字段启用
- 发布账号 cookie 缺失校验（由后端 recovery 兜底）

## Technical Notes

- 前端单文件为主：`frontend/src/views/Review.vue` + i18n 两文件
- 后端单文件：`backend/api/routes/system.py`（_check_xhs 一行）
- `use_browser` 来自 env `XHS_USE_BROWSER`（settings.py:40，env_prefix XHS_）
- 现有可复用 i18n key：dryRun / dryRunHelp / liveWarning / confirm / account
