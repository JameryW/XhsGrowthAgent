# Fix Web TUI Chinese Input and Interaction Experience

## Goal

Web TUI 体验和原生终端一致：中文输入完整支持、交互功能（搜索/快捷键/复制粘贴/右键菜单）对齐原生终端、移动端可用、渲染性能接近原生。

## Requirements

### P0: 中文输入 + xterm v6 升级

* 升级 `xterm@5` → `@xterm/xterm@6`（修复五笔输入法重复 bug，import 路径变更）
* 修复 `handleTermData` ASCII 过滤 bug（`code >= 32 && code < 127` → 接受所有可打印字符）
* 支持 IME 组合输入（拼音、五笔等），组合期间不泄漏多余字符
* CJK 字符宽度=2，光标定位/退格/删除按显示宽度计算
* 中文字体 fallback：fontFamily 添加 CJK 字体栈
* 中文标点（全角逗号、句号等）正确处理

### P1: 交互体验对齐原生终端

* **搜索**：`@xterm/addon-search` + 搜索栏 UI，Ctrl+Shift+F 触发
* **快捷键**：Ctrl+L 清屏、Ctrl+U 清行、Ctrl+W 删词、Ctrl+A/E 行首/行尾、Ctrl+K 删到行尾、Home/End、Delete
* **复制粘贴**：Ctrl+Shift+C/V，右键菜单（Copy/Paste/Select All/Search）
* **渲染加速**：`@xterm/addon-webgl`（优先），DOM fallback（v6 无 canvas addon）
* **平滑滚动**：`smoothScrollDuration: 100`
* **行高**：`lineHeight: 1.15` 提升 CJK 可读性
* **对比度**：`minimumContrastRatio: 4.5` WCAG AA
* **overview ruler**：搜索匹配高亮 + 右侧滚动条标记

### P2: 移动端适配

* **独立移动输入栏**：移动端显示原生 `<input>` 输入框（IME 兼容性好），桌面端保持 xterm 内输入
* **软键盘适配**：`visualViewport` API + `dvh` CSS 单位，终端不被键盘遮挡
* **触摸滚动**：xterm 内置触摸滚动已支持
* **WebGL 禁用**：移动端禁用 WebGL（context 创建常失败），用 DOM 渲染
* **响应式布局**：状态栏 + 终端 + 输入栏适配小屏

## Acceptance Criteria

* [ ] 中文输入法可输入中文字符（拼音、五笔）
* [ ] IME 组合过程无多余字符泄漏
* [ ] 中文字符显示正常（非方块）
* [ ] 光标在中文混合文本中定位正确
* [ ] 退格键正确删除中文字符（删一个字不是半个）
* [ ] Ctrl+Shift+F 打开搜索栏，可搜索终端内容
* [ ] Ctrl+L/U/W/A/E/K/Home/End/Delete 快捷键工作
* [ ] Ctrl+Shift+C/V 复制粘贴工作
* [ ] 右键菜单有 Copy/Paste/Select All/Search 选项
* [ ] WebGL 渲染器生效（桌面端）
* [ ] 滚动平滑
* [ ] 移动端：输入栏可输入中文，终端不被软键盘遮挡
* [ ] 移动端：触摸滚动正常

## Definition of Done

* Lint / typecheck 绿色
* 前端 build 通过
* 桌面端手动测试：中文输入 + 搜索 + 快捷键 + 复制粘贴 + 右键菜单
* 移动端手动测试：中文输入 + 触摸滚动 + 软键盘适配

## Technical Approach

### xterm v6 升级

* `xterm@5` → `@xterm/xterm@6`，import 路径 `from 'xterm'` → `from '@xterm/xterm'`
* CSS `xterm/css/xterm.css` → `@xterm/xterm/css/xterm.css`
* `@xterm/addon-canvas` 不可用（v6 移除），WebGL + DOM fallback
* 现有 addon（fit, web-links）版本兼容 v6

### 中文输入修复

1. 移除 ASCII 过滤：`code >= 32 && code < 127` → `code >= 32`
2. IME 组合状态：`term.textarea` 监听 `compositionstart`/`compositionend`，组合期间忽略 `onData`
3. CJK 宽度：`term.unicode.getStringCellWidth(str)` 计算显示宽度
4. 字体栈：`'Menlo', 'Consolas', 'Courier New', 'Noto Sans Mono CJK SC', 'PingFang SC', 'Microsoft YaHei', 'WenQuanYi Micro Hei Mono', monospace`

### 交互体验

1. 搜索：`@xterm/addon-search` + `TuiSearchBar.vue`，Ctrl+Shift+F
2. 快捷键：`term.attachCustomKeyEventHandler()` 拦截
3. 右键菜单：`TuiContextMenu.vue`，`contextmenu` 事件
4. 渲染：`@xterm/addon-webgl`，`onContextLoss` → dispose → DOM fallback
5. 配置：`smoothScrollDuration: 100`, `lineHeight: 1.15`, `minimumContrastRatio: 4.5`

### 移动端

1. 检测移动端（`navigator.maxTouchPoints > 0` 或屏幕宽度 < 768）
2. 移动端显示独立输入栏（`<input>` + 发送按钮），用 `term.input(data, true)` 注入
3. `visualViewport` resize 事件调整终端高度
4. 移动端禁用 WebGL
5. CSS `dvh` 单位 + `overflow: hidden` 防止页面滚动

## Research References

* [`research/xterm-cjk-input.md`](research/xterm-cjk-input.md) — CJK/IME 输入方案、CompositionHelper 原理、宽度计算、已知 bug
* [`research/xterm-ux-addons.md`](research/xterm-ux-addons.md) — 13 个官方 addon API、配置选项、快捷键最佳实践、渲染策略
* [`research/xterm-v6-upgrade.md`](research/xterm-v6-upgrade.md) — v5→v6 破坏性变更、import 路径、addon 兼容性
* [`research/xterm-mobile-touch.md`](research/xterm-mobile-touch.md) — 移动端触摸、软键盘、输入栏方案、响应式布局

## Out of Scope

* 内联图片渲染（需后端支持 SIXEL/IIP/Kitty 协议）
* 富文本复制 / 会话恢复（serialize addon）
* 编程字体连字（ligatures addon）
* OSC 52 远程剪贴板（clipboard addon）
* Web 字体加载（web-fonts addon）
* iOS 中文 IME 标点 bug（xterm 上游未修复 #5835）
