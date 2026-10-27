# Review UI pause copy + RQGM residual weaken

## Goal

Heavy residual (#720) 后：Dashboard / Review / Evaluation 把 `evaluator_fail_closed` 说清为人审决策；RQGM 降为 advisory（建议徽章 + 仅供参考），不再呈现为发布闸门。Panel 仍跑并写 hints。

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| RQGM residual | **Weaken** — keep panel; demote to advisory |
| UI surface | **Dashboard + Review + Evaluation** (AgentTUI/onboarding out unless shared i18n keys) |
| Fail-closed CTA | **Human decision** — 批准继续发布 / 要求修订；副文：AI 分仅供参考；发布=合规判定+人决定 |
| Decision badge | **Advisory wording** — 建议通过/建议修订/建议不发 + 仅供参考 |

## Requirements (MVP)

1. **i18n / Dashboard `ActionButtons`**
   - Rewrite `evaluatorGate*` (en + zh-CN): no 「质量门 / Override」; human-decision tone; mention advisory AI + eligibility.
2. **Review**
   - When `pause_reason=evaluator_fail_closed` (or equivalent status), surface approve/revise aligned with Dashboard.
   - RQGM decision badges → advisory labels; optional small 「仅供参考」 chip near score.
3. **Evaluation**
   - Same advisory badge/labels; copy that scores are advisory, not publish gate.
   - Do not imply LLM decision alone unlocks publish.
4. **Shared types/comments** that still say “quality gate decides publish” → advisory / fail-closed human channel.
5. **Tests**: locale/key expectations; ActionButtons / Review / Evaluation specs if they assert old gate strings.
6. Backend API resume error text: soft-align if it still says 「评估质量门」as if LLM gate (keep require `human_decision`).

## Acceptance Criteria

* [ ] Fail-closed pause CTAs use human-decision wording (en+zh)
* [ ] Review + Evaluation decision badges read as suggestions, not hard gates
* [ ] No primary-path copy claims AI self-eval alone decides publish
* [ ] RQGM panel still runs; hints still available for revise
* [ ] Unit/component tests + CI green

## Out of Scope

* Deleting RQGM node / feature-flag off panel
* AgentTUI / onboarding redesign
* Changing judgers / `publish_eligibility` / Action stamp loader
* Large Review layout redesign beyond copy + badge demotion

## Technical Notes

* `frontend/src/locales/{en,zh-CN}.json` — `dashboard.actionButtons.evaluatorGate*`
* `frontend/src/components/dashboard/ActionButtons.vue`
* `frontend/src/views/Review.vue`, `EvaluationView.vue` (+ related components/panels)
* `frontend/src/stores/workflow.ts`, `types/workflow.ts` comments
* Possibly `backend/api/routes/_wf_runtime.py` resume error copy
* Specs: `.trellis/spec/backend/compliance-baseline.md`, frontend review/i18n if present

## Definition of Done

* Tests/CI green; PR; Trellis archive after merge
