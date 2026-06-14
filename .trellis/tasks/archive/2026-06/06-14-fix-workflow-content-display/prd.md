# 修复工作流内容不展示

## Goal

Find and fix why workflow content is not shown in the frontend.

## Scope

- Inspect workflow list/detail API responses and frontend rendering paths.
- Identify whether the issue is data loading, field mapping, conditional rendering, or layout.
- Apply a narrow frontend/backend fix if the root cause is clear.

## Acceptance

- Workflow content is visible for existing workflow data.
- The fix is limited to the broken display path.
- A relevant build or browser/API verification is run.
