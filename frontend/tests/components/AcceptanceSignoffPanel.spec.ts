import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import AcceptanceSignoffPanel from '@/components/settings/AcceptanceSignoffPanel.vue'
import { getAcceptanceSignoff } from '@/api/system'

vi.mock('@/api/system', () => ({
  getAcceptanceSignoff: vi.fn(),
}))

const mockedGetAcceptanceSignoff = vi.mocked(getAcceptanceSignoff)

describe('AcceptanceSignoffPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedGetAcceptanceSignoff.mockResolvedValue({
      ok: true,
      version: 1,
      source_doc: 'docs/acceptance/signoff-request-2026-09-22.md',
      chase_checklist: 'docs/acceptance/signoff-chase-checklist.md',
      disclaimer:
        'waived_risk_accepted means residual risk was accepted — it is NOT a pass. CI green must never count as signoff.',
      updated_at: '2026-10-16',
      replaces_human_signoff: false,
      waiver: {
        recorded_at: '2026-09-22',
        summary: 'Risk accepted; waived_risk_accepted ≠ passed.',
        replaces_signoff: false,
        next_global_review_at: '2027-01-14',
      },
      gates: [
        {
          id: 'G1',
          title: '三档走查',
          task: 't',
          owner_role: 'release owner',
          status: 'waived_risk_accepted',
          conclusion: '',
          signed_by: '',
          signed_at: '',
          next_review_at: '2027-01-14',
          chase_action: '复审或续豁免',
          is_passed: false,
          is_waived: true,
        },
        {
          id: 'G2',
          title: '严格空态',
          task: 't',
          owner_role: '发布方',
          status: 'waived_risk_accepted',
          conclusion: '',
          signed_by: '',
          signed_at: '',
          next_review_at: '2027-01-14',
          chase_action: '空态复审',
          is_passed: false,
          is_waived: true,
        },
      ],
    })
  })

  it('renders waived gates without success/passed styling and shows next_review_at', async () => {
    const wrapper = mount(AcceptanceSignoffPanel, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
        },
      },
    })
    await flushPromises()

    expect(mockedGetAcceptanceSignoff).toHaveBeenCalled()
    expect(wrapper.text()).toContain('2027-01-14')
    expect(wrapper.text()).toContain('复审或续豁免')
    expect(wrapper.text()).toMatch(/风险接受|risk accepted|Waiver|豁免/i)
    // Read-only: no approve/pass action controls (copy may mention “一键通过” in disclaimer).
    expect(wrapper.findAll('button').length).toBe(0)
    expect(wrapper.findAll('input[type="checkbox"]').length).toBe(0)

    const badges = wrapper.findAll('[data-status="waived_risk_accepted"]')
    expect(badges.length).toBe(2)
    for (const badge of badges) {
      expect(badge.attributes('data-passed')).toBe('false')
      expect(badge.attributes('data-waived')).toBe('true')
      expect(badge.classes().join(' ')).not.toContain('bg-emerald')
      expect(badge.classes().join(' ')).toContain('bg-slate')
    }
  })

  it('never treats waived as passed even if is_passed is wrongly true', async () => {
    mockedGetAcceptanceSignoff.mockResolvedValueOnce({
      ok: true,
      disclaimer: 'mirror only',
      gates: [
        {
          id: 'G1',
          title: 't',
          task: 't',
          owner_role: 'r',
          status: 'waived_risk_accepted',
          conclusion: '',
          signed_by: '',
          signed_at: '',
          next_review_at: '2027-01-14',
          // Malicious / buggy payload — UI must still refuse success styling.
          is_passed: true,
          is_waived: true,
        },
      ],
      replaces_human_signoff: false,
    })

    const wrapper = mount(AcceptanceSignoffPanel, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
        },
      },
    })
    await flushPromises()

    const badge = wrapper.find('[data-status="waived_risk_accepted"]')
    expect(badge.exists()).toBe(true)
    expect(badge.attributes('data-passed')).toBe('false')
    expect(badge.attributes('data-waived')).toBe('true')
    expect(badge.classes().join(' ')).not.toContain('bg-emerald')
  })
})
