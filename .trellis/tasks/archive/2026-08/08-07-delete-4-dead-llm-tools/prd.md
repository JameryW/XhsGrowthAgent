# Delete 4 dead LLM tools + tests + prompt yamls

## Goal

Remove 4 dead LLM tools that have **zero production callers** (verified by
investigator grep across `backend/agents|services|api|graph|nodes|omp|cli`).
They are vestigial — only referenced by their own test file
(`test_llm_tools.py`). Per memory `stale-prompt-path-4-llm-tools`, PR#480
fixed their broken prompt paths (they read `xhs_growth/` stale paths) — but
they were never wired into any agent. They're dead weight: 4 tool files +
4 prompt yamls + 1 test file (~415 LOC) that test dead code.

This is **cleanup, not perf** — no runtime benefit. Value: smaller codebase
surface, fewer files to maintain, no dead code misleading future readers.
Honest framing per "不发布 fake 优化" — PR title will say "delete dead tools"
not "optimize".

## The 4 dead tools (verified 0 prod callers)

| tool file | `@tool` fn | prompt yaml (actual) |
|-----------|-----------|----------------------|
| `backend/tools/content/title_generator.py` | `title_generator` | `prompts/tools/title_generator.yaml` |
| `backend/tools/content/hashtag_researcher.py` | `hashtag_researcher` | `prompts/tools/hashtag_researcher.yaml` |
| `backend/tools/content/image_prompt.py` | `image_prompt_generator` | `prompts/tools/image_prompt.yaml` |
| `backend/tools/scheduling/calendar.py` | `timing_optimizer` | `prompts/tools/timing_optimizer.yaml` |

NOTE: `calendar.py` reads `timing_optimizer.yaml` (NOT `calendar.yaml`) via
its `_load_prompt`. Investigator confirmed: no `calendar.yaml` exists.

## What I already know (investigator findings)

- **Prod callers: ZERO.** Only grep hits: `llm_enrichment.py:173` docstring
  ("for title_generator, etc." — generic comment, not a call); `image_prompts`
  state-field hits (unrelated plural field in substructures/review/evaluator);
  omp TS `review_versions.ts:11` (state field, not tool). No
  `from backend.tools.content/scheduling import <tool>` outside the tools
  themselves.
- **`de_ai_taste` is LIVE and MUST be kept**: copywriter imports
  `polish_copy`/`algorithmic_de_ai` from it. `de_ai_taste.yaml` is NOT among
  the 4 dead yamls. Isolated + safe.
- **`test_llm_tools.py` is the sole test ref** for all 4 tools. It tests ONLY
  these 4 + 1 unrelated `test_manual_engagement_tools_remain_importable`
  (tests xhs manual tools: comment_replier/dm_handler/escalation_flagger/
  fetch_pending_comments). That 1 test must be RELOCATED (not silently
  dropped) to preserve xhs manual-tool import coverage.
- **PEP 562 lazy `__getattr__`**: `content/__init__.py` uses a `_LAZY_EXPORTS`
  map (L31-44) resolved via `__getattr__` (L61) — per memory
  `lazy-init-submodule-symbol-clash`. Removal must DELETE map entries (not
  import lines). `scheduling/__init__.py` uses EAGER import (L7) — plain
  delete.
- **`scheduling/` package**: contains ONLY `calendar.py` + `__init__.py`.
  Nothing else imports `backend.tools.scheduling` (only `test_llm_tools.py`).
  → delete the ENTIRE `backend/tools/scheduling/` package (dir + file).
- **`content/` package stays**: has live tools (de_ai_taste, layout,
  style). Only remove the 4 dead entries from `_LAZY_EXPORTS` + `__all__`.
- **test_visual_integration.py** refs `content.layout`/`content.style`
  (VisualAnalysisService) — LIVE, untouched.

## Deletion checklist

### Delete files (4 tools + 4 yamls + 1 test + scheduling package)
- `backend/tools/content/title_generator.py`
- `backend/tools/content/hashtag_researcher.py`
- `backend/tools/content/image_prompt.py`
- `backend/tools/scheduling/calendar.py`
- `backend/tools/scheduling/__init__.py` (package now empty — delete whole dir)
- `backend/config/prompts/tools/title_generator.yaml`
- `backend/config/prompts/tools/hashtag_researcher.yaml`
- `backend/config/prompts/tools/image_prompt.yaml`
- `backend/config/prompts/tools/timing_optimizer.yaml`
- `tests/unit/tools/test_llm_tools.py` (delete entirely AFTER relocating
  the 1 manual-tool test)

### KEEP (do NOT touch)
- `backend/config/prompts/tools/de_ai_taste.yaml` (live)
- `backend/tools/content/de_ai_taste.py` + layout + style (live)
- `backend/tools/content/__init__.py` machinery (`__getattr__`/`__dir__`)
  — only remove the 4 dead entries from `_LAZY_EXPORTS` + `__all__`

### `__init__.py` edits
- `content/__init__.py`:
  - Remove from `_LAZY_EXPORTS`: `hashtag_researcher`, `research_hashtags`
    alias, `image_prompt_generator`, `title_generator` entries.
  - Remove from `__all__`: `hashtag_researcher`, `research_hashtags`,
    `title_generator`, `image_prompt_generator`.
  - Update docstring (remove bullets for the 4 dead tools).
  - KEEP de_ai_taste/layout/style entries + `__getattr__`/`__dir__` machinery.
- `scheduling/__init__.py`: delete entire file (part of package deletion).

### Test relocation (preserve xhs manual-tool coverage)
- `test_manual_engagement_tools_remain_importable` (test_llm_tools.py:369)
  imports `from backend.tools.xhs import (comment_replier, dm_handler,
  escalation_flagger, fetch_pending_comments)`.
- Relocate to `tests/unit/tools/test_xhs_manual_tools.py` (new file).
- Verify those 4 xhs manual tools still exist + importable.

## Recommended approach (ponytail)

1. Relocate the 1 manual-tool test to new file first (preserve coverage).
2. Delete `test_llm_tools.py` entirely.
3. Delete the 4 tool files + 4 yamls.
4. Delete `backend/tools/scheduling/` package (calendar.py + __init__.py).
5. Edit `content/__init__.py`: remove 4 dead entries from `_LAZY_EXPORTS` +
   `__all__` + docstring bullets. Keep machinery + live entries.
6. Run full suite — verify nothing imports the deleted symbols.

~9 file deletions + 1 new test file + 1 __init__ edit. Net LOC: large
deletion (~415 test LOC + ~400 tool LOC + 4 yamls). Pure cleanup.

**Rejected: keep the tools, just remove tests.** Dead code without tests is
worse — silently rots, misleads. Delete fully.

**Rejected: keep the prompt yamls.** Yaml without a consumer is dead config.
Delete with the tool.

**Rejected: keep scheduling/ package with empty __init__.py.** Nothing
imports `backend.tools.scheduling` after calendar.py deletion — empty
package is dead. Delete the dir.

## Requirements

- 4 dead tool files deleted.
- 4 dead prompt yamls deleted.
- `test_llm_tools.py` deleted (AFTER relocating the 1 manual-tool test).
- `backend/tools/scheduling/` package deleted entirely.
- `content/__init__.py` 4 dead entries removed from `_LAZY_EXPORTS` + `__all__`
  + docstring; machinery + live entries (de_ai_taste/layout/style) intact.
- `de_ai_taste` (tool + yaml) UNTOUCHED.
- `test_manual_engagement_tools_remain_importable` relocated to
  `tests/unit/tools/test_xhs_manual_tools.py` (coverage preserved).

## Acceptance Criteria

- [ ] 4 tool files + 4 yamls + `test_llm_tools.py` + `scheduling/` package
      deleted.
- [ ] `content/__init__.py` 4 dead entries removed; live entries + machinery
      intact.
- [ ] `de_ai_taste.py` + `de_ai_taste.yaml` untouched (verify copywriter
      still imports polish_copy/algorithmic_de_ai).
- [ ] `test_xhs_manual_tools.py` created with the relocated manual-tool test;
      passes.
- [ ] No `import` of deleted symbols anywhere (grep clean).
- [ ] `ruff format --check` + `ruff check .` + `mypy backend` + full `pytest`
      green (pre-push triple).

## Definition of Done

- 4 tools + 4 yamls + 1 test file + scheduling package deleted
- 1 test relocated (coverage preserved)
- content/__init__ pruned
- Pre-push triple green
- PR off `origin/main`, separate branch `fix/delete-4-dead-llm-tools`

## Out of Scope

- Other dead code (separate audits).
- Refactoring live tools (de_ai_taste/layout/style).
- Removing the `llm_enrichment.py:173` docstring mention (cosmetic, optional —
  can note in PR but not required).

## Technical Notes

- Files: see deletion checklist above.
- Precedent: PR#478 (dead agent mixins removed), #475 (ripple dead wrappers
  removed), #480 (fixed these 4 tools' prompt paths — now deleting the tools
  themselves since still 0 callers).
- Memory: `stale-prompt-path-4-llm-tools` (PR#480 context),
  `lazy-init-submodule-symbol-clash` (PEP 562 lazy __init__ — content/ uses
  it, must edit _LAZY_EXPORTS map not import lines).
- This is cleanup not perf — PR title says "delete dead tools" honestly.
- Scheduling package deletion: verified only test_llm_tools.py imports
  backend.tools.scheduling; deleting the whole package is cleanest.

## Decision (ADR-lite)

**Context**: 4 LLM tools (title_generator, hashtag_researcher,
image_prompt_generator, timing_optimizer) have 0 prod callers. PR#480 fixed
their broken prompt paths but they were never wired into any agent. Dead
weight: ~800 LOC (tools + tests) + 4 yamls. Only test_llm_tools.py references
them (plus 1 unrelated manual-tool test to relocate).
**Decision**: delete all 4 tools + 4 yamls + test_llm_tools.py + the empty
scheduling/ package. Relocate the 1 manual-tool test. Prune content/__init__
_LAZY_EXPORTS + __all__ (keep machinery + live entries). Keep de_ai_taste.
**Consequences**: smaller codebase, no dead code misleading readers. No
runtime perf change (cold/import-only paths). Coverage preserved (manual-tool
test relocated). ~9 deletions + 1 new test + 1 __init__ edit. Low risk
(zero prod callers verified).
