// DB-13: content cards keep the no-artifact state informative and use shared
// theme surfaces for user drafts and version variants.
import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import ContentCards from '@/components/dashboard/ContentCards.vue'
import { useWorkflowStore } from '@/stores/workflow'
import i18n from '@/locales'

const tt = (key: string) => i18n.global.t(key)

function mountCards(state: Record<string, unknown>) {
  const store = useWorkflowStore()
  store.workflowStates.set('content-test', state as any)
  store.activeThreadId = 'content-test'
  return mount(ContentCards, {
    global: {
      stubs: {
        RipplePanel: { template: '<div />' },
      },
    },
  })
}

describe('ContentCards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('explains the active phase while waiting for the first artifact', () => {
    const wrapper = mountCards({
      thread_id: 'content-test',
      phase: 'planning',
      status: 'running',
      progress_percent: 20,
    })

    expect(wrapper.text()).toContain(tt('dashboard.contentCards.loading'))
    expect(wrapper.text()).toContain(tt('dashboard.timeline.planning'))
    expect(wrapper.text()).toContain(tt('dashboard.timeline.planningDesc'))
  })

  it('uses theme surfaces for drafts and content version B', () => {
    const wrapper = mountCards({
      thread_id: 'content-test',
      phase: 'creating',
      status: 'running',
      progress_percent: 50,
      copy_content: { selected_title: 'Generated title' },
      draft_content: { title: 'Draft title', text: 'Draft body', hashtags: ['tag'] },
      content_versions: [{ version_id: 'b', version_type: 'B', title: 'Version B', body: 'Body', hashtags: [] }],
    })

    expect(wrapper.find('.liquid-glass-teal').exists()).toBe(true)
    expect(wrapper.html()).not.toContain('bg-blue-')
  })
})
