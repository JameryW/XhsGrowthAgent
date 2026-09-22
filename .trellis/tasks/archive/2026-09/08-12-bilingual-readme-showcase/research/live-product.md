# Live product research

Date checked: 2026-08-12 (Asia/Hong_Kong)

## Public demo: `https://xhs.jameryw.dev/`

The public landing page renders as “小红书增长引擎 / 案例展示” and positions itself around a real case and an explainable creation process. The visible page includes:

- A CTA to start creating and a public case browser.
- A featured completed case named `vibe coding教程`.
- A case card showing the creation mode (`趋势创作`), status (`已完成`), update date, and topic direction.
- A public case list with filters for status and creation mode (`趋势创作`, `Brief 创作`) plus sorting by recent update or title.
- A “how it works” summary with trend discovery, content creation, and data analysis.

The page exposes one public case at the time of the check. The README should use “public sample case” rather than implying that all workspaces or all case data are public.

## Public Workflow Replay

The featured replay URL is:

`https://xhs.jameryw.dev/replay/case_c35a6559d23fd17cd832?from=%2F`

The visible replay organizes the case into four stages:

1. Trend discovery — “普通人搞钱与副业逻辑” and audience/trend evidence.
2. Strategy planning — an angle and audience strategy for the topic.
3. Content creation — a completed title and long-form body draft.
4. Content review — the review-stage version of the generated content.

The final result panel visibly includes the title, body, key takeaways, eight hashtags, image count `3`, and a palette with `#FFE4E1`, `#FFDAB9`, and `#FFFACD`. The replay also exposes step navigation, progress, copy-result actions, and a deep-linkable case URL.

## Authentication boundary

Navigating to `https://xhs.jameryw.dev/start` redirects to `/login?redirect=/start`. The README must therefore separate the public Showcase/Replay surfaces from the authenticated creation workspace and avoid promising anonymous workflow execution or publishing.

## Repository evidence

The frontend contains the following authenticated or operational surfaces: `Home`, `Dashboard`, `Review`, `Analytics`, `EvaluationView`, `History`, `Settings`, `HelpView`, and `AgentTUI`. The existing frontend UX acceptance record at `docs/acceptance/public-ux-2026-08-10.md` documents public Showcase/Replay verification and the same route families.

## Media captured

- `docs/assets/readme/live-home.png` — public Showcase landing page.
- `docs/assets/readme/live-replay.png` — public Workflow Replay page.

Both images were captured read-only from the public deployment and are intended as README evidence, not as a promise that the sample data is representative of every account.
