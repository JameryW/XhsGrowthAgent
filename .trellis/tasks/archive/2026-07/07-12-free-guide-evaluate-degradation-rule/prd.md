# Free guide: document evaluate-degradation rule (cross-audit sync, follow-up to #242)

## Problem

#242 (surface degraded/failed evaluation) shipped the evaluator `degraded`
flag + persistence + render + list badge + TUI display, but the
`xhs_free_guide` text rule for evaluate-degradation was lost: the #242 branch
was force-pushed (rebased onto main to pick up #241's guide changes) AFTER the
PR was already squash-merged — so the squash captured the pre-force-push state
without the guide rule. `main`'s guide documents the evaluate→revise loop
(#234) and the publish-failure recovery loop (#241) but NOT the
evaluate-degradation loop (#242).

So an agent reading the guide first still has no rule for a degraded
(fake-100-approved) evaluation: it may publish an unevaluated draft thinking
it passed 100. The cross-audit convention (guide text mirrors the renders'
cues) is broken for the evaluate-degradation case.

## Fix

Add the evaluate-degradation rule to `xhs_free_guide` (mirrors #241's
publish-failure rule + #234's evaluate→revise rule):

> Evaluate can degrade (LLM timeout → pass-through fallback with degraded=True,
> overall_score=100/decision=approved): the 100/approved is a FAKE fallback,
> NOT a real score. The render flags it (⚠ Evaluation degraded); do NOT
> publish on a degraded verdict — re-run xhs_free_evaluate (keep draft_id)
> once the LLM is available. The draft list shows a [degraded] badge.

Also add `[degraded]` to the draft-management badge list in the guide.

This is the exact change that was on the #242 branch's post-merge force-push
(commit 9231ee56) but never landed on main.

## Scope

- `backend/services/omp_bridge.py` — `xhs_free_guide`: evaluate-degradation
  rule + `[degraded]` badge in the draft-management list.
- `.trellis/spec/backend/free-creation.md` — note the guide documents the
  evaluate-degradation loop (cross-audit sync with #242).
- `tests/unit/services/test_omp_bridge.py` — guide test asserts the
  evaluate-degradation rule.

## Verification

- `ruff check .` + `ruff format --check .` clean.
- `mypy backend` clean.
- full `pytest`.

## Non-goals (YAGNI)

- No code/render/persistence changes — those shipped in #242. This PR only
  fixes the guide-text gap.
