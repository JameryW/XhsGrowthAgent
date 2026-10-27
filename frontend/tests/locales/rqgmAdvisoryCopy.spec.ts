// Locale contract: RQGM residual is advisory (human-decision fail-closed CTAs).
import { describe, it, expect } from 'vitest'
import en from '@/locales/en.json'
import zh from '@/locales/zh-CN.json'

describe('RQGM advisory locale copy', () => {
  const enGate = en.dashboard.actionButtons
  const zhGate = zh.dashboard.actionButtons

  it('evaluatorGate* uses human-decision tone (en + zh)', () => {
    expect(enGate.evaluatorGateApprove).toMatch(/approve|continue publish/i)
    expect(enGate.evaluatorGateRevise).toMatch(/revision|revise/i)
    expect(enGate.evaluatorGateHint.toLowerCase()).toMatch(/advisory|for reference|eligibility/)
    expect(enGate.evaluatorGateApprove.toLowerCase()).not.toContain('override')
    expect(enGate.evaluatorGateHint.toLowerCase()).not.toContain('quality gate')

    expect(zhGate.evaluatorGateApprove).toContain('批准继续发布')
    expect(zhGate.evaluatorGateRevise).toContain('要求修订')
    expect(zhGate.evaluatorGateHint).toContain('仅供参考')
    expect(zhGate.evaluatorGateApprove).not.toContain('质量门')
    expect(zhGate.evaluatorGateApproveDesc).not.toContain('质量门')
    expect(zhGate.evaluatorGateHint).not.toContain('质量门')
  })

  it('Review + Evaluation decision badges are suggestions', () => {
    expect(en.review.evaluation.decision.approved).toMatch(/suggest/i)
    expect(en.review.evaluation.decision.needs_revision).toMatch(/suggest/i)
    expect(en.review.evaluation.decision.rejected).toMatch(/suggest|do not publish/i)
    expect(en.review.evaluation.forReference).toMatch(/reference/i)

    expect(zh.review.evaluation.decision.approved).toBe('建议通过')
    expect(zh.review.evaluation.decision.needs_revision).toBe('建议修订')
    expect(zh.review.evaluation.decision.rejected).toBe('建议不发')
    expect(zh.review.evaluation.forReference).toBe('仅供参考')

    expect(en.evaluation.decision.approved).toMatch(/suggest/i)
    expect(en.evaluation.forReference).toMatch(/reference/i)
    expect(en.evaluation.advisoryHint.toLowerCase()).toMatch(/advisory|human/)
    expect(zh.evaluation.decision.approved).toBe('建议通过')
    expect(zh.evaluation.decision.needs_revision).toBe('建议修订')
    expect(zh.evaluation.decision.rejected).toBe('建议不发')
    expect(zh.evaluation.forReference).toBe('仅供参考')
    expect(zh.evaluation.advisoryHint).toContain('仅供参考')
  })
})
