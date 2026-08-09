import { describe, expect, it, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import i18n from '@/locales'
import WorkflowTimeline from '@/components/dashboard/WorkflowTimeline.vue'
import { useWorkflowStore } from '@/stores'
import type { WorkflowStateResponse } from '@/types/workflow'

const baseState = (overrides: Partial<WorkflowStateResponse>): WorkflowStateResponse => ({
  thread_id: 'xhs_test_thread',
  phase: 'creating',
  status: 'running',
  current_agent: 'copywriter',
  next_steps: [],
  error: null,
  progress_percent: 40,
  agent_timeline: [],
  trend_data: { hot_topics: [] } as any,
  content_plan: {
    selected_topic: 'topic',
    content_angle: 'angle',
    content_type: 'carousel',
    target_audience: 'audience',
    key_points: [],
    suggested_timing: '',
    hashtags: [],
    urgency: 'medium',
  },
  copy_content: undefined,
  visual_plan: undefined,
  ...overrides,
})

const mountTimeline = (state: WorkflowStateResponse) => {
  const store = useWorkflowStore()
  store.workflowStates.set(state.thread_id, state)
  store.activeThreadId = state.thread_id
  store.progressPercent = state.progress_percent

  return mount(WorkflowTimeline, {
    global: {
      plugins: [i18n],
      stubs: {
        AppIcon: true,
        WorkflowNode: {
          props: ['label', 'status'],
          template: '<div class="workflow-node" :data-status="status">{{ label }}</div>',
        },
      },
    },
  })
}

const nodeStatuses = (wrapper: ReturnType<typeof mount>) =>
  wrapper.findAll('.workflow-node').map(node => node.attributes('data-status'))

const subStepStatus = (wrapper: ReturnType<typeof mount>, agent: string) =>
  wrapper.find(`[data-agent="${agent}"]`).attributes('data-status')

describe('WorkflowTimeline', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('does not mark visual design as running while waiting for draft input', () => {
    const wrapper = mountTimeline(baseState({
      status: 'awaiting_draft',
      current_agent: 'copywriter',
      next_steps: ['draft_gate'],
      copy_content: {
        title_candidates: [],
        selected_title: 'title',
        body_text: 'body',
        hashtags: [],
        cta: '',
        emoji_usage: [],
        tone: 'friendly',
      },
    }))

    const statuses = nodeStatuses(wrapper)
    expect(statuses[0]).toBe('completed')
    expect(statuses[1]).toBe('completed')
    expect(statuses[2]).toBe('running')
    expect(statuses[3]).toBe('pending')
    expect(subStepStatus(wrapper, 'draft_gate')).toBe('running')
    expect(subStepStatus(wrapper, 'visual_designer')).toBe('pending')
  })

  it('marks visual design as running only when the visual designer agent is active', () => {
    const wrapper = mountTimeline(baseState({
      current_agent: 'visual_designer',
      copy_content: {
        title_candidates: [],
        selected_title: 'title',
        body_text: 'body',
        hashtags: [],
        cta: '',
        emoji_usage: [],
        tone: 'friendly',
      },
    }))

    const statuses = nodeStatuses(wrapper)
    expect(statuses[0]).toBe('completed')
    expect(statuses[1]).toBe('completed')
    expect(statuses[2]).toBe('running')
    expect(statuses[3]).toBe('pending')
    expect(subStepStatus(wrapper, 'visual_designer')).toBe('running')
  })

  it('keeps total progress in the hero instead of rendering a duplicate fill', () => {
    const wrapper = mountTimeline(baseState({ progress_percent: 73 }))

    expect(wrapper.find('[data-testid="timeline-stage-line"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="timeline-progress-fill"]').exists()).toBe(false)
  })

  it('shows a live duration for the active agent timeline entry', async () => {
    vi.useFakeTimers()
    try {
      const startedAt = new Date(Date.now() - 5200).toISOString()
      const wrapper = mountTimeline(baseState({
        agent_timeline: [{
          agent: 'copywriter',
          started_at: startedAt,
          completed_at: undefined,
          duration_seconds: undefined,
          status: 'running',
        }],
      }))

      await wrapper.find('button').trigger('click')
      expect(wrapper.text()).toContain(i18n.global.t('dashboard.timeline.durationSeconds', { seconds: '5.2' }))
      vi.advanceTimersByTime(1000)
      await wrapper.vm.$nextTick()
      expect(wrapper.text()).toContain(i18n.global.t('dashboard.timeline.durationSeconds', { seconds: '6.2' }))
      wrapper.unmount()
    } finally {
      vi.useRealTimers()
    }
  })
})
