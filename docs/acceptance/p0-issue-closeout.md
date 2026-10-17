# P0 GitHub issue closeout (#644–#656)

Implementation landed in [#657](https://github.com/JameryW/XhsGrowthAgent/pull/657)
(`feat(compliance): P0 合规与账号安全底线`). Specs: [#658](https://github.com/JameryW/XhsGrowthAgent/pull/658).
Follow-ons: P1 [#659](https://github.com/JameryW/XhsGrowthAgent/pull/659)/[#660](https://github.com/JameryW/XhsGrowthAgent/pull/660),
P2 [#661](https://github.com/JameryW/XhsGrowthAgent/pull/661), signoff waiver tracking [#663](https://github.com/JameryW/XhsGrowthAgent/pull/663).

This document is the evidence map used to close the still-open tracking issues.
Contract source of truth: [`.trellis/spec/backend/compliance-baseline.md`](../../.trellis/spec/backend/compliance-baseline.md).

| Issue | Title | Evidence on `main` | Notes vs issue text |
|------:|-------|--------------------|---------------------|
| [#644](https://github.com/JameryW/XhsGrowthAgent/issues/644) | T1-1 stealth | `xhs_login._stealth_enabled` / `_apply_stealth` only when `XHS_BROWSER_STEALTH=1`; `scripts/gates/stealth_default_off.py`; `tests/unit/services/test_stealth_default_off.py` | MVP = default-off + opt-in (not hard-delete of optional dep) |
| [#645](https://github.com/JameryW/XhsGrowthAgent/issues/645) | T1-2 CI gate | CI job **Compliance Baseline Gate** runs `python scripts/gates/stealth_default_off.py` | — |
| [#646](https://github.com/JameryW/XhsGrowthAgent/issues/646) | T1-3 fake sign | No `XHSSignature`; HTTP path raises `signature_unavailable`; `tests/unit/services/test_xhs_signature.py` | — |
| [#647](https://github.com/JameryW/XhsGrowthAgent/issues/647) | T2-1 publish audit | `publish_gate` writes `publish_confirmation` with `confirmer` / `source` / `confirmed_at`; refuse path emits `ACTION_PUBLISH_REFUSED`; `tests/unit/agents/nodes/test_dual_auto_and_commercial.py`, `test_publish_gate.py` | Receipt fields fulfill audit intent; action constant naming differs |
| [#648](https://github.com/JameryW/XhsGrowthAgent/issues/648) | T2-2 dual-auto | `compliance_policy.assert_not_dual_auto` → `dual_auto_publish_forbidden`; wired on start/CLI | Hard reject (no ack bypass) per locked MVP |
| [#649](https://github.com/JameryW/XhsGrowthAgent/issues/649) | T2-3 never auto high-risk | `review_gate._should_auto_approve` vetoes blocking / commercial / non-low risk | — |
| [#650](https://github.com/JameryW/XhsGrowthAgent/issues/650) | T3-1 daily quotas | `check_dm_quota` / `check_comment_reply_quota` in `xhs_risk_gate`; `tests/unit/services/test_engagement_quotas.py` | — |
| [#651](https://github.com/JameryW/XhsGrowthAgent/issues/651) | T3-2 inbound DM | `send_dm` + `is_inbound_peer` / `note_inbound_peers`; no 「新建私信」 for inbound replies | — |
| [#652](https://github.com/JameryW/XhsGrowthAgent/issues/652) | T3-3 risk pause | `note_engagement_risk_pause` on risk control; precheck blocks while paused | — |
| [#653](https://github.com/JameryW/XhsGrowthAgent/issues/653) | T4-1 lexicon | `backend/services/compliance/lexicon.py` + `backend/config/compliance/*.yaml` | Module path under `services/compliance` |
| [#654](https://github.com/JameryW/XhsGrowthAgent/issues/654) | T4-2 pre-LLM scan | `backend/agents/evaluator.py` runs `scan_state_content` before LLM; writes `lexicon_scan` / `compliance_scan` | — |
| [#655](https://github.com/JameryW/XhsGrowthAgent/issues/655) | T5-1 `is_commercial` | `state_is_commercial` / `commercial_disclosure_ok`; brief mode forces commercial; publish gate disclosure | — |
| [#656](https://github.com/JameryW/XhsGrowthAgent/issues/656) | T5-2 label blocking | Evaluator sets `disclosure_missing` blocking when commercial text lacks 合作/广告 markers via `text_has_disclosure` | — |

Verified against `main` @ closeout PR head. Closing via GitHub `Closes` keywords on merge (API issue-write unavailable to this agent).
