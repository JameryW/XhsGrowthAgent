import { describe, expect, it, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import PublicUxTelemetryPanel from '@/components/settings/PublicUxTelemetryPanel.vue'

const getPublicTelemetrySummaryMock = vi.hoisted(() => vi.fn())

vi.mock('@/api/publicShowcase', () => ({
  getPublicTelemetrySummary: getPublicTelemetrySummaryMock,
}))

describe('PublicUxTelemetryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getPublicTelemetrySummaryMock.mockResolvedValue({
      days: 7,
      events: [
        {
          event_name: 'replay_first_result_visible',
          viewport: 'mobile',
          source: null,
          status: null,
          mode: 'key',
          phase: null,
          error_type: null,
          view_mode: 'key',
          event_count: 4,
          measured_count: 4,
          p50_duration_ms: 80,
          p75_duration_ms: 120,
        },
      ],
    })
  })

  it('renders aggregate counts and timing without raw identifiers', async () => {
    const wrapper = mount(PublicUxTelemetryPanel, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
        },
      },
    })
    await flushPromises()

    expect(getPublicTelemetrySummaryMock).toHaveBeenCalledWith(7, expect.objectContaining({
      suppressToast: true,
      signal: expect.any(AbortSignal),
    }))
    expect(wrapper.text()).toContain('事件总量')
    expect(wrapper.text()).toContain('Replay 首个结果可见')
    expect(wrapper.text()).toContain('120 ms')
    expect(wrapper.text()).not.toContain('case-demo')
  })

  it('reloads the selected reporting period', async () => {
    const wrapper = mount(PublicUxTelemetryPanel, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
        },
      },
    })
    await flushPromises()

    await wrapper.find('#public-telemetry-days').setValue('30')
    await flushPromises()
    expect(getPublicTelemetrySummaryMock).toHaveBeenLastCalledWith(30, expect.objectContaining({
      suppressToast: true,
    }))
  })

  it('shows a recoverable error state', async () => {
    getPublicTelemetrySummaryMock.mockRejectedValueOnce(new Error('network'))
    const wrapper = mount(PublicUxTelemetryPanel, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.attributes('role')).toBeUndefined()
    expect(wrapper.text()).toContain('监控数据暂时无法加载')
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
  })
})
