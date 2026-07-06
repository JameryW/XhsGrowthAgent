# PRD: Start Creation Mode Split and Free Orchestration

## Goal

Change the current "启动工作流" entry into "开始创作". After clicking it, users choose between:

1. 简单模式（固定工作流）: continue through the existing fixed workflow behavior.
2. 自由模式（自动化编排）: navigate to the TUI agent page and use OMP for free orchestration.

In free mode, OMP must not trigger the fixed workflow. It should focus on free orchestration for creation, evaluation, and publishing. The evaluation portion must include AI-taste detection, image quality checks, and commercial-taste checks.

## Requirements

- Rename the user-facing workflow entry from "启动工作流" to "开始创作" in the relevant UI copy.
- Add a mode choice after the creation entry:
  - Simple mode starts the existing workflow path unchanged.
  - Free mode navigates to the TUI page.
- Adjust the OMP/XHS host tool behavior so the TUI free mode does not auto-trigger the fixed workflow.
- Ensure the free orchestration instructions/capabilities cover:
  - creation
  - evaluation
  - publishing
- Extend quality evaluation to include:
  - AI味儿检查
  - 图片质量检查
  - 商业味儿检查

## Acceptance Criteria

- The primary entry no longer shows "启动工作流" and uses "开始创作" in Chinese locale where applicable.
- Clicking the entry presents a two-mode choice instead of immediately starting the fixed workflow.
- Choosing simple mode preserves the existing workflow start behavior.
- Choosing free mode routes the user to the existing TUI page.
- The OMP bridge/tooling no longer auto-executes fixed workflow start in free orchestration mode.
- Quality evaluation output/state exposes the three new checks in a way the frontend can render.
- Focused frontend/backend tests or checks pass for the modified paths.
