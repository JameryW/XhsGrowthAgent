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
          cached: false,
        },
        {
          event_name: 'replay_select_to_render',
          viewport: 'mobile',
          source: null,
          status: null,
          mode: 'key',
          phase: null,
          error_type: null,
          view_mode: 'key',
          event_count: 2,
          measured_count: 2,
          p50_duration_ms: 20,
          p75_duration_ms: 40,
          cached: true,
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
    expect(wrapper.text()).toContain('40 ms')
    expect(wrapper.text()).toContain('通过')
    expect(wrapper.text()).not.toContain('case-demo')
  })

  it('does not mix network selections into the cached budget', async () => {
    getPublicTelemetrySummaryMock.mockResolvedValueOnce({
      days: 7,
      events: [{
        event_name: 'replay_select_to_render',
        viewport: 'desktop',
        source: null,
        status: null,
        mode: 'key',
        phase: null,
        error_type: null,
        view_mode: 'key',
        event_count: 1,
        measured_count: 1,
        p50_duration_ms: 800,
        p75_duration_ms: 900,
        cached: false,
      }],
    })
    const wrapper = mount(PublicUxTelemetryPanel, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('暂无数据')
    expect(wrapper.find('[data-testid="cached-select-budget-card"]').text()).toContain('暂无数据')
    expect(wrapper.find('[data-testid="cached-select-budget-card"]').text()).not.toContain('900 ms')
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

    await wrapper.find('[role="alert"] button').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('事件总量')
  })

  it('keeps a late response from an older period from replacing the latest period', async () => {
    let resolveInitial: ((value: unknown) => void) | undefined
    const initial = new Promise(resolve => {
      resolveInitial = resolve
    })
    getPublicTelemetrySummaryMock
      .mockReset()
      .mockReturnValueOnce(initial)
      .mockResolvedValueOnce({ days: 30, events: [] })

    const wrapper = mount(PublicUxTelemetryPanel, {
      global: {
        stubs: {
          AppIcon: { template: '<span />' },
        },
      },
    })
    await wrapper.find('#public-telemetry-days').setValue('30')
    await flushPromises()
    resolveInitial?.({
      days: 7,
      events: [{
        event_name: 'replay_first_result_visible',
        viewport: 'mobile',
        source: null,
        status: null,
        mode: 'key',
        phase: null,
        error_type: null,
        view_mode: 'key',
        event_count: 1,
        measured_count: 1,
        p50_duration_ms: 999,
        p75_duration_ms: 999,
        cached: false,
      }],
    })
    await flushPromises()

    expect(getPublicTelemetrySummaryMock).toHaveBeenLastCalledWith(30, expect.anything())
    expect(wrapper.text()).toContain('暂无公开页埋点')
    expect(wrapper.text()).not.toContain('999 ms')
  })
})
