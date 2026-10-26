# Publish judgers on Action path + light workflow residual

## Goal

统一「能不能发」口径：creator-agent Action 与工作流共用 `decide_publish_eligibility`；工作流保持 #717 轻收语义；Action 在 plan / execute 分层接入判定器 + 审计。

## Decisions (locked)

| Topic | Choice |
|-------|--------|
| Scope | Action 接线 + 工作流轻收（不改 cap-force / auto-revise） |
| Workflow LLM residual | 轻收 — #717 行为保留；本片以契约/防回退测试 + docs/spec 对齐为主 |
| Content judgers placement | **plan**：账号级 + 已 stamp 的 `publish_eligibility`；**execute**：读 artifact 正文后跑全套判定器，Gateway 前 fail-closed |

## Requirements (MVP)

1. **Shared engine**: 两边只调用 `backend.services.compliance.judgers.decide_publish_eligibility`（可加薄投影 helper，不复制规则表）。
2. **Plan (`evaluate_action_policy` / `build_action_policy_snapshot`)**:
   - Keep existing account / risk-cooldown gates.
   - If snapshot can supply stamped eligibility (e.g. from thread workflow state) and `allowed is False` → deny, no intent; stable `policy_id` (e.g. `policy.action.publish_eligibility_denied`) + judger reason in audit.
   - Account-level judgers that need no body (dual_auto, high_risk_auto when niche known) may run at plan.
   - Do **not** require artifact read at plan.
3. **Execute (`execute_action` publish branch)**:
   - After artifact readable + hash match, project body → state-like dict, run full `decide_publish_eligibility`.
   - Blocking failure → deny before Tool Gateway; no receipt; audit event with verdicts.
4. **Workflow light residual**: document shared contract; add/keep tests that LLM `approved` cannot override eligibility; no router behavior change beyond what’s already on main.
5. **Docs/specs**: update `docs/publish-action-protocol.md` + `.trellis/spec/backend/compliance-baseline.md`.

## Acceptance Criteria

* [ ] Plan publish: stamped eligibility deny / dual-auto / high-risk-auto → `ActionPolicyDeniedError`, no intent, auditable policy_id
* [ ] Execute publish: lexicon/disclosure hit on artifact body → fail-closed before Gateway, no receipt
* [ ] Single `decide_publish_eligibility` implementation shared
* [ ] Workflow #717 router semantics unchanged (tests still green)
* [ ] Unit tests for policy + execution deny paths; lint/mypy/CI green

## Definition of Done

* Tests + CI green; specs/docs updated; PR opened; Trellis archive after merge

## Out of Scope

* Removing RQGM panel code
* Medium/heavy residual (no cap-force removal, no disabling auto-revise routing)
* Reading artifact inside plan policy
* Legal sign-off board / large UI work

## Technical Notes

* `backend/creator_agent/policy.py`, `advisor.py`, `execution.py`
* `backend/services/compliance/judgers.py`
* `backend/graph/routers.py` (read-only for light residual)
* `docs/publish-action-protocol.md`, `.trellis/spec/backend/compliance-baseline.md`
* Prior: #717
