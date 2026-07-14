# OMP Creator-Statistics Analysis Tools

## Goal

Expose imported Creator Center account and note data to OMP so an agent can
inspect real performance, run the existing deterministic analysis, and retrieve
mode-specific creation advice without triggering a live account sync.

## Scope

Add the following read-only tools to both OMP surfaces:

1. `xhs_creator_stats` — fetch imported account/note metrics and present a
   compact performance summary, including top notes and engagement rates.
2. `xhs_creator_analysis` — call the existing creator-statistics analysis API
   and return findings plus evidence and recommendations.
3. `xhs_creator_suggestions` — retrieve persisted creation suggestions for
   `trend`, `brief`, or `free` mode.

Both the TypeScript extension and Python OMP host-tool bridge must expose the
same tool names, parameter shapes, routes, and concise text output. Update the
`/xhs-analytics` discovery command so users and agents can find the tools.

## Non-goals

- Do not invoke the live Creator Center sync endpoint from an analysis tool.
- Do not expose cookies, CDP endpoints, or raw platform request metadata.
- Do not duplicate backend analysis algorithms in TypeScript; use existing
  read-only API endpoints as the source of truth.

## Acceptance Criteria

- OMP can retrieve imported note/account statistics for an account and safely
  handle an empty dataset.
- OMP can return existing analysis findings and mode-specific suggestions.
- Extension and bridge schemas/routes stay aligned and bridge tests cover all
  three tools.
- OMP TypeScript typecheck and affected Python tests pass.
