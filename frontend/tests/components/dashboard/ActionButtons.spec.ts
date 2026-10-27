// Fail-closed pause CTAs: human-decision wording (no quality-gate / Override).
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import ActionButtons from '@/components/dashboard/ActionButtons.vue'
import { useWorkflowStore } from '@/stores/workflow'
import i18n from '@/locales'

const tt = (key: string) => String(i18n.global.t(key))

vi.mock('@/utils/routePrefetch', () => ({
  prefetchStartWorkspace: vi.fn(),
}))

function seedFailClosed(store: ReturnType<typeof useWorkflowStore>) {
  store.workflowStates.set('thr-eval', {
    thread_id: 'thr-eval',
    phase: 'paused',
    status: 'paused',
    pause_reason: 'evaluator_fail_closed',
    progress_percent: 85,
    next_steps: [],
    agent_timeline: [],
  } as any)
  store.activeThreadId = 'thr-eval'
}

async function mountButtons() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/start', component: { template: '<div />' } },
      { path: '/review/:threadId?', name: 'review', component: { template: '<div />' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  return mount(ActionButtons, {
    global: {
      plugins: [router],
      stubs: {
        AppIcon: true,
        NeonButton: {
          props: ['loading', 'disabled', 'title', 'ariaLabel'],
          emits: ['click'],
          template: '<button type="button" :aria-label="ariaLabel" :title="title" @click="$emit(\'click\')"><slot /></button>',
        },
      },
    },
  })
}

describe('ActionButtons evaluator fail-closed CTAs', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('uses human-decision copy, not quality-gate / Override language', async () => {
    seedFailClosed(useWorkflowStore())
    const wrapper = await mountButtons()

    const text = wrapper.text()
    expect(text).toContain(tt('dashboard.actionButtons.evaluatorGateHint'))
    expect(text).toContain(tt('dashboard.actionButtons.evaluatorGateApprove'))
    expect(text).toContain(tt('dashboard.actionButtons.evaluatorGateRevise'))

    // Locked PRD: no gate / Override framing on the primary path.
    expect(text.toLowerCase()).not.toContain('override')
    expect(text).not.toContain('质量门')
    expect(tt('dashboard.actionButtons.evaluatorGateApprove')).not.toMatch(/override/i)
    expect(tt('dashboard.actionButtons.evaluatorGateHint')).toMatch(/advisory|仅供参考|for reference|eligibility|合规/i)
  })

  it('calls resumeWorkflow with the human decision on approve', async () => {
    const store = useWorkflowStore()
    seedFailClosed(store)
    const spy = vi.spyOn(store, 'resumeWorkflow').mockResolvedValue(undefined as any)
    const wrapper = await mountButtons()

    const approve = wrapper.findAll('button').find((b) =>
      b.text().includes(tt('dashboard.actionButtons.evaluatorGateApprove')),
    )
    expect(approve).toBeTruthy()
    await approve!.trigger('click')
    expect(spy).toHaveBeenCalledWith(undefined, 'approve')
  })
})
