import { describe, expect, it, beforeEach } from 'vitest'
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
  store.workflowState = state
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
    expect(statuses[2]).toBe('completed')
    expect(statuses[3]).toBe('running')
    expect(statuses[4]).toBe('pending')
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
    expect(statuses[2]).toBe('completed')
    expect(statuses[3]).toBe('completed')
    expect(statuses[4]).toBe('running')
  })
})
