# UI Layout & Button Consistency Polish

## Goal

Fix three layout/consistency issues visible across all pages:

1. **Dashboard 两侧空白过多** — `max-w-5xl` (1024px) 限制了内容宽度，在 1440px+ 屏幕上右侧有大片空白
2. **Home 页面顶部 logo 重复** — 左侧 Navbar 已有完整 logo+app name，Home 页面 hero 又重复显示 Rocket icon + title
3. **Review 页面按钮与整体风格不一致** — 审核页面的操作按钮样式（3列 grid + flex-col icon+text）与 Dashboard 的 NeonButton 行内 icon+text 风格不同；全站按钮尺寸和布局需要统一

## What I already know

* Dashboard.vue uses `max-w-5xl mx-auto` constraining content to ~1024px
* Home.vue hero section has Rocket icon + title that duplicates Navbar logo
* App.vue main content area uses `flex-1 overflow-y-auto` with padding based on breakpoints
* Navbar.vue is 256px wide on desktop, 68px on tablet
* NeonButton component supports variants: pink, cyan, purple, ghost, peach and sizes: sm, md, lg
* Review page uses a 3-column grid for approve/revise/reject with flex-col icon layout
* Dashboard ActionButtons uses inline icon+text layout with flex-wrap gap
* Home page WorkflowStartForm uses toggle switches with custom styling (not NeonButton-based)

## Requirements

### 1. Dashboard width expansion
* Change `max-w-5xl` to `max-w-7xl` (1280px) or remove max-width constraint entirely to fill available space
* On wide screens content should use most of the available area between Navbar and right edge

### 2. Home page hero simplification
* Remove the duplicate Rocket icon + title/subtitle hero section from Home.vue
* Replace with a simpler, compact header — just a small tagline or nothing (since Navbar already identifies the app)
* The "启动新工作流" card becomes the primary visual focus

### 3. Review page button unification
* Review action buttons (approve/revise/reject) should use the same NeonButton inline icon+text pattern as Dashboard
* Remove the flex-col stacked layout; use horizontal icon+text like other pages
* All pages should consistently use the same button sizes for equivalent actions

### 4. Cross-page button consistency
* Primary actions: `NeonButton variant="pink" size="md"` (start workflow, approve, confirm)
* Secondary actions: `NeonButton variant="cyan" size="sm"` (refresh, navigate, view)
* Destructive actions: `NeonButton variant="ghost"` with rose border/text override (reject, cancel)
* Toggle switches remain as-is (they're not NeonButton-equivalent)

## Acceptance Criteria

* [ ] Dashboard content fills available width without excessive whitespace on 1440px screens
* [ ] Home page no longer shows duplicate logo/icon in hero section
* [ ] Review page action buttons use the same inline icon+text pattern as Dashboard
* [ ] All pages use consistent NeonButton sizes and variants for equivalent action types
* [ ] No visual regressions on tablet (768px) or mobile (375px) breakpoints

## Definition of Done

* Lint passes
* All pages visually verified in browser at desktop/tablet widths
* Deployed and verified

## Out of Scope

* NeonButton component refactoring (just standardize usage)
* Color palette or theme system changes
* New page designs