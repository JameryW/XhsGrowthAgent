import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import WorkflowCardBody from '@/components/WorkflowCardBody.vue'
import type { WorkflowStateResponse } from '@/types/workflow'

function detail(overrides: Partial<WorkflowStateResponse> = {}): WorkflowStateResponse {
  return {
    thread_id: 'thread-card',
    phase: 'creating',
    status: 'running',
    next_steps: [],
    progress_percent: 60,
    agent_timeline: [],
    content_plan: {
      selected_topic: '夏日防晒实测',
      content_angle: '实用测评',
      content_type: 'note',
      target_audience: '通勤人群',
      key_points: [],
      suggested_timing: '',
      hashtags: [],
      urgency: 'medium',
    },
    copy_content: {
      title_candidates: [],
      selected_title: '通勤防晒不踩坑',
      body_text: '',
      hashtags: ['防晒', '通勤'],
      cta: '',
      emoji_usage: [],
      tone: 'friendly',
    },
    ...overrides,
  }
}

describe('WorkflowCardBody', () => {
  it('keeps the primary workflow output visible before metadata', () => {
    const wrapper = mount(WorkflowCardBody, { props: { detail: detail() } })

    expect(wrapper.find('[aria-label="workflow-output"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('夏日防晒实测')
    expect(wrapper.text()).toContain('通勤防晒不踩坑')
    expect(wrapper.find('[aria-label="workflow-output"]').classes()).toContain('min-h-[92px]')
  })

  it('preserves a publish link as an independent keyboard target', () => {
    const wrapper = mount(WorkflowCardBody, {
      props: {
        detail: detail({ publish_result: { status: 'published', post_url: 'https://example.com/post' } }),
      },
    })

    const link = wrapper.find('a[href="https://example.com/post"]')
    expect(link.exists()).toBe(true)
    expect(link.attributes('target')).toBe('_blank')
  })
})
