# Deterministic publish judgers + hard-delete stealth

## Goal

能否发布只由**确定性规则 + 审计记录**决定，不交给 LLM 自评；每种失败模式单独判定器，阈值按业务成本可调。优先**硬删除**防检测伪装与逆向签名残留（完成 #644 原验收，不再保留 opt-in stealth）。

## Decision (ADR-lite)

### Publish authority
**Decision**: Publish eligibility is the conjunction of named deterministic judgers. Each judger emits one audit verdict. The RQGM LLM panel remains a **quality / revision** signal only — its scores must not alone grant a publish route.

### Per-failure-mode judgers
**Decision**: One judger per failure mode (lexicon, commercial disclosure, blocking compliance, dual-auto, high-risk auto). Thresholds live in one config object (env-overridable) tuned by business cost (stricter for irreversible publish).

### Stealth / fake sign
**Decision**: Hard-delete `playwright-stealth`, `_apply_stealth`, opt-in env, and AutomationControlled camouflage args on login launch paths. Keep `XHSCookieParser` + `signature_unavailable` fail-closed. CI gate asserts absence, not opt-in.

## Requirements

1. Remove stealth injection code, `playwright-stealth` / `fake-useragent` deps, mypy override, and related tests; replace with “no init-script camouflage” assertions.
2. Strengthen CI gate: no `_apply_stealth`, no `playwright_stealth`, no `navigator.webdriver` hide scripts in `backend/`.
3. Add `backend/services/compliance/judgers.py` with separate judgers + `decide_publish_eligibility(state) → report` including audit payload.
4. Evaluator writes `evaluation_result.publish_eligibility` from judgers; router uses eligibility for fail-closed / publish path; LLM `decision` only drives quality revise loop.
5. Update compliance / browser-safety specs and `docs/security.md`.

## Acceptance Criteria

* [ ] `rg -n "playwright_stealth|_apply_stealth|XHS_BROWSER_STEALTH" backend/` → no production hits (comments/docs about removal OK in docs/)
* [ ] `pip install -e ".[browser]"` does not install `playwright-stealth`
* [ ] CI gate fails if stealth/camouflage or `XHSSignature` reappear
* [ ] Each failure mode has an isolated judger with configurable threshold / cost
* [ ] Publish route consults eligibility audit, not LLM overall self-score alone
* [ ] Unit tests green for judgers + stealth absence + router

## Out of Scope

* Removing the LLM quality panel entirely (it stays for revision hints)
* Rewriting creator_agent Action Policy Engine
* Legal sign-off board
