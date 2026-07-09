# TUI tool_result multiline display

## Goal

AgentTUI `formatResult` (AgentTUI.vue:641) collapses all tool results to a single line (`str.replace(/\s*\n\s*/g, ' ')`) and truncates at 160 chars. Multi-line structured results — `xhs_free_evaluate` (6-dimension RQGM scores + decision + revision_hints), `xhs_free_guide` (orchestration steps), `xhs_evaluation_run`, `xhs_workflow_status` — get flattened into a truncated single line, losing the 6-dimension breakdown, hints, and guide steps. Let multi-line/structured results render readably in the TUI while keeping short results single-line and scannable.

## What I already know

- `formatResult` (AgentTUI.vue:641): `str.replace(/\s*\n\s*/g, ' ').trim()` + `flat.slice(0,160)` cap. Designed for single-line scannability (fine for short results).
- `tool_result` display (609-615): `  ↳ ✓ toolName {resultStr}`, resultStr from formatResult. `writeLine` → `term.writeln`, which renders embedded `\n` as real line breaks. So multi-line resultStr already renders correctly — only `formatResult` flattens it.
- Multi-line/structured bridge tools: `xhs_free_evaluate` (returns JSON `{draft_id, evaluation_result:{overall_score, dimensions[6], decision, revision_hints}}`), `xhs_free_guide` (multi-line orchestration text), `xhs_evaluation_run` (same shape as evaluate), `xhs_workflow_status` (multi-line snapshot).
- Tool definitions live in `backend/services/omp_bridge.py` (`_HOST_TOOL_DEFINITIONS`) and route handlers in `backend/api/routes/free.py`.

## Open Questions (resolved)

- **Scope**: Global `formatResult` change — any tool returning multi-line/structured JSON benefits, and the short-result path is unchanged (only results that contain newlines or nested JSON go multi-line). Most consistent, least special-casing.
- **Threshold**: Detect by content, not tool name. Result string contains a newline → multi-line render. JSON object/array with >1 key/element → pretty-print multi-line. Otherwise single-line + 160 cap as today.
- **Truncation for multi-line**: Cap total height (~12 lines) rather than 160 chars; append a dim `… (N more lines)` suffix when truncated. Width already handled by terminal wrapping.

## Requirements

- `formatResult` keeps short single-line results as-is (single line, 160-char cap).
- Results containing newlines, or JSON objects/arrays with >1 key/element, render multi-line with indentation aligned under the `↳` result block.
- Multi-line output capped at a line budget (~12 lines); overflow shows a dim `… (N more lines)` footer.
- Error results (`is_error`) render multi-line too (full error text, not truncated).
- No tool-name special-casing in the TUI — detection is content-based.
- Non-free, short tool results behave exactly as before (regression-safe).

## Acceptance Criteria

- [ ] `xhs_free_evaluate` result shows overall_score, decision, and all 6 dimensions with scores in TUI (not a single truncated line).
- [ ] `xhs_free_guide` result shows orchestration steps across multiple lines.
- [ ] Short results (e.g. `xhs_free_draft_create` returning `{draft_id}`) stay single-line, truncated at 160 as before.
- [ ] Multi-line results exceeding the line budget show a `… (N more lines)` dim footer.
- [ ] `npm run build` + `vue-tsc` typecheck pass; CI green.

## Definition of Done

- Frontend build + typecheck pass; CI green.
- Spec note added to `.trellis/spec/frontend/component-patterns.md` recording the multi-line tool_result convention.

## Out of Scope

- Collapsible/expandable results (toggle on click) — YAGNI; always-expand is simpler and fits a terminal.
- Per-tool formatters — content-based detection only.
- Changing backend tool return shapes — purely a frontend display fix.

## Technical Notes

- File: `frontend/src/views/AgentTUI.vue` — `formatResult` (641) + `tool_result` display (609-615).
- `writeLine` → `term.writeln` already handles `\n`; only `formatResult` needs to stop collapsing newlines and instead pretty-print structured results.
- Use `JSON.stringify(result, null, 2)` for object/array results with >1 key/element; keep `String(result)` for primitives.
- Align multi-line body under the `↳` column with a 4-space indent prefix per line.
- Constraint: don't break single-line scannability for short results; non-free behavior unchanged.
