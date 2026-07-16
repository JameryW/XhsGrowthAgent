import { describe, expect, it, beforeEach, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import Showcase from '@/views/Showcase.vue'

const routerMock = vi.hoisted(() => ({
  replace: vi.fn(() => Promise.resolve()),
  push: vi.fn(() => Promise.resolve()),
  resolve: vi.fn((to: { name?: string; params?: { threadId?: string } }) => ({ href: `/replay/${to.params?.threadId || ''}` })),
}))
const routeMock = vi.hoisted(() => ({ query: {} as Record<string, string> }))
const listWorkflowsMock = vi.hoisted(() => vi.fn())
const getWorkflowStatusMock = vi.hoisted(() => vi.fn())

vi.mock('vue-router', () => ({
  useRouter: () => routerMock,
  useRoute: () => routeMock,
}))
vi.mock('@/api/workflow', () => ({
  listWorkflows: listWorkflowsMock,
  getWorkflowStatus: getWorkflowStatusMock,
}))

function workflow(thread_id: string, status: 'running' | 'completed', updated_at: string) {
  return {
    thread_id,
    account_id: 'public',
    phase: status === 'completed' ? 'completed' : 'creating',
    status,
    dry_run: false,
    auto_publish: false,
    progress_percent: status === 'completed' ? 100 : 50,
    workflow_mode: 'trend',
    label: thread_id,
    created_at: updated_at,
    updated_at,
    error: null,
  }
}

describe('Showcase P0 interaction contract', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routeMock.query = {}
    listWorkflowsMock.mockResolvedValue({
      workflows: [workflow('featured-thread', 'completed', '2026-07-16T10:00:00Z'), workflow('other-thread', 'running', '2026-07-15T10:00:00Z')],
      total: 2,
      limit: 50,
      offset: 0,
    })
    getWorkflowStatusMock.mockResolvedValue({
      thread_id: 'featured-thread',
      phase: 'completed',
      status: 'completed',
      next_steps: [],
      progress_percent: 100,
      agent_timeline: [],
      content_plan: { selected_topic: '真实案例主题' },
      copy_content: { selected_title: '真实产出标题', hashtags: [] },
    })
  })

  it('renders the featured case once and leaves a semantic replay link for the list card', async () => {
    const wrapper = mount(Showcase, {
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a :href="typeof to === \'string\' ? to : `/replay/${to.params?.threadId}`"><slot /></a>',
          },
          AnimatedCounter: { template: '<span>0</span>' },
        },
      },
    })

    await flushPromises()
    expect(wrapper.findAll('.showcase-featured').length).toBe(1)
    expect(wrapper.findAll('.showcase-card').length).toBe(1)
    expect(wrapper.find('.showcase-card a').attributes('href')).toContain('/replay/other-thread')
    expect(wrapper.find('.showcase-featured-link').exists()).toBe(true)
  })

  it('normalizes URL filters and keeps them synchronized', async () => {
    routeMock.query = { status: 'invalid', mode: 'brief', sort: 'progress' }
    const wrapper = mount(Showcase, {
      global: {
        stubs: {
          RouterLink: { template: '<a><slot /></a>' },
          AnimatedCounter: { template: '<span>0</span>' },
        },
      },
    })
    await flushPromises()

    expect(routerMock.replace).toHaveBeenCalledWith({ query: { status: 'all', mode: 'brief', sort: 'progress' } })
    await wrapper.find('select').setValue('created')
    expect(routerMock.replace).toHaveBeenLastCalledWith({ query: { status: 'all', mode: 'brief', sort: 'created' } })
  })
})
