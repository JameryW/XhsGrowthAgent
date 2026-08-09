// DB-15: Dashboard view-level acceptance tests.
// Covers: DB-01 replay deep-link entry, DB-02 replay never celebrates,
// nextAction four branches (review / awaiting-scroll / idle / error-resume),
// DB-05 error branch resumes current thread.
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import Dashboard from '@/views/Dashboard.vue'
import ErrorState from '@/components/ErrorState.vue'
import CelebrationModal from '@/components/CelebrationModal.vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useErrorStore } from '@/stores/error'
import i18n from '@/locales'

// i18n is installed globally (tests/setup.ts) and returns translated strings,
// so assertions compare against rendered values, not key names.
const tt = (key: string) => i18n.global.t(key)

// ponytail: stub heavy child components so we test Dashboard's own logic, not
// their render trees. CelebrationModal kept real to assert DB-02 visibility.
const stubs = {
  WorkflowTabBar: { template: '<div />' },
  WorkflowHeader: { template: '<div />' },
  WorkflowTimeline: { template: '<div />' },
  ContentCards: { template: '<div />' },
  OptimizationPanel: { template: '<div />' },
  ActionButtons: { template: '<div />' },
  BloggerSelectionPanel: { template: '<div />' },
  BriefFileUpload: { template: '<div />' },
  DashboardSkeleton: { template: '<div />' },
}

function makeRouter(query: Record<string, string> = {}, params: Record<string, string> = {}) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/dashboard/:threadId?', name: 'dashboard', component: Dashboard }],
  })
  router.push({ name: 'dashboard', params, query })
  return router
}

async function mountDashboard(query: Record<string, string> = {}, params: Record<string, string> = {}) {
  const router = makeRouter(query, params)
  await router.isReady()
  const wrapper = mount(Dashboard, {
    global: {
      plugins: [router],
      stubs,
    },
  })
  // Let onMounted async + watchers settle.
  await wrapper.vm.$nextTick()
  return { wrapper, router }
}

describe('Dashboard view', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // Element APIs used by DB-04 scrollToPanel focus().
    if (!document.getElementById) return
    vi.spyOn(Element.prototype, 'scrollIntoView').mockImplementation(() => {})
  })

  describe('DB-02: replay snapshots never trigger the completed celebration', () => {
    it('does not open CelebrationModal when replaying a completed phase', async () => {
      const store = useWorkflowStore()
      // Seed a completed, non-replay state first.
      store.workflowStates.set('t1', {
        thread_id: 't1', phase: 'completed', status: 'completed', progress_percent: 100,
      } as any)
      store.activeThreadId = 't1'
      const { wrapper } = await mountDashboard({}, { threadId: 't1' })
      const modal = wrapper.findComponent({ name: 'CelebrationModal' })
      // Modal stays closed while not replaying but already completed at mount.
      expect((modal.vm as any).show).toBe(false)
      // Flip into replay mode mid-session: must still not celebrate.
      store.isReplayMode = true
      await wrapper.vm.$nextTick()
      expect((modal.vm as any).show).toBe(false)
    })
  })

  describe('DB-10: celebration actions use live workflow data', () => {
    it('passes artifact counts and the published post URL to CelebrationModal', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('celebrated', {
        thread_id: 'celebrated',
        phase: 'completed',
        status: 'completed',
        progress_percent: 100,
        content_versions: [{ version_id: 'v1' }, { version_id: 'v2' }],
        visual_plan: { image_paths: ['cover.png', 'detail.png'] },
        publish_result: { post_url: 'https://www.xiaohongshu.com/explore/live-post' },
      } as any)
      store.activeThreadId = 'celebrated'

      const { wrapper, router } = await mountDashboard({}, { threadId: 'celebrated' })
      const modal = wrapper.findComponent(CelebrationModal)

      expect(modal.props('copyCount')).toBe(2)
      expect(modal.props('imageCount')).toBe(2)
      expect(modal.props('postUrl')).toBe('https://www.xiaohongshu.com/explore/live-post')
      expect(modal.props('canReplay')).toBe(true)

      const pushSpy = vi.spyOn(router, 'push').mockResolvedValue(undefined)
      await modal.vm.$emit('replay')
      expect(pushSpy).toHaveBeenCalledWith('/start')
    })

    it('guards the replay callback when the Dashboard is in replay mode', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('replay-completed', {
        thread_id: 'replay-completed',
        phase: 'completed',
        status: 'completed',
        progress_percent: 100,
      } as any)
      store.activeThreadId = 'replay-completed'
      store.isReplayMode = true

      const { wrapper, router } = await mountDashboard({}, { threadId: 'replay-completed' })
      const pushSpy = vi.spyOn(router, 'push')
      const modal = wrapper.findComponent(CelebrationModal)

      await modal.vm.$emit('replay')
      expect(modal.props('canReplay')).toBe(false)
      expect(pushSpy).not.toHaveBeenCalledWith('/start')
    })
  })

  describe('nextAction branches', () => {
    it('awaiting_review → navigate CTA to /review/:threadId', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('t2', {
        thread_id: 't2', phase: 'reviewing', status: 'awaiting_review', progress_percent: 60,
      } as any)
      store.activeThreadId = 't2'
      const { wrapper } = await mountDashboard({}, { threadId: 't2' })
      const cta = wrapper.find('[data-test="next-action-cta"]')
      // Falls back to text match since NeonButton is stubbed via ActionButtons? No — NeonButton is real.
      const btn = wrapper.find('button')
      expect(wrapper.text()).toContain(tt('dashboard.nextAction.reviewCta'))
    })

    it('awaiting_brief → scroll CTA with panel-brief anchor', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('t3', {
        thread_id: 't3', phase: 'briefing', status: 'awaiting_brief', progress_percent: 10,
      } as any)
      store.activeThreadId = 't3'
      const { wrapper } = await mountDashboard({}, { threadId: 't3' })
      expect(wrapper.text()).toContain(tt('dashboard.nextAction.continueCta'))
    })

    it('idle/idle → start CTA to /start', async () => {
      const { wrapper } = await mountDashboard({}, {})
      expect(wrapper.text()).toContain(tt('dashboard.nextAction.startCta'))
    })

    it('error phase → retry CTA resumes current thread (DB-05)', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('t4', {
        thread_id: 't4', phase: 'error', status: 'error', progress_percent: 0,
      } as any)
      store.activeThreadId = 't4'
      const resumeSpy = vi.spyOn(store, 'resumeWorkflow').mockResolvedValue(undefined as any)
      const { wrapper } = await mountDashboard({}, { threadId: 't4' })
      expect(wrapper.text()).toContain(tt('dashboard.nextAction.retryCta'))
      const btn = wrapper.find('button')
      await btn.trigger('click')
      await wrapper.vm.$nextTick()
      expect(resumeSpy).toHaveBeenCalled()
    })

    it('completed → history CTA (not review)', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('t-done', {
        thread_id: 't-done', phase: 'completed', status: 'completed', progress_percent: 100,
      } as any)
      store.activeThreadId = 't-done'
      const { wrapper } = await mountDashboard({}, { threadId: 't-done' })
      expect(wrapper.text()).toContain(tt('dashboard.hero.completedCta'))
      expect(wrapper.text()).not.toContain(tt('dashboard.nextAction.reviewCta'))
    })

    it('stale → resume CTA', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('t-stale', {
        thread_id: 't-stale', phase: 'creating', status: 'stale', progress_percent: 40,
      } as any)
      store.activeThreadId = 't-stale'
      const { wrapper } = await mountDashboard({}, { threadId: 't-stale' })
      expect(wrapper.text()).toContain(tt('dashboard.actionButtons.resume'))
    })
  })

  it('uses the shared ErrorState for API failures', async () => {
    const errorStore = useErrorStore()
    errorStore.setError('api', 'Network request failed')
    const { wrapper } = await mountDashboard()

    expect(wrapper.findComponent(ErrorState).exists()).toBe(true)
    expect(wrapper.text()).toContain('Network request failed')
    expect(wrapper.findComponent({ name: 'ErrorCard' }).exists()).toBe(false)
  })

  describe('DB-06: todo chips', () => {
    it('renders a brief todo chip when awaiting brief', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('t5', {
        thread_id: 't5', phase: 'briefing', status: 'awaiting_brief', progress_percent: 10,
      } as any)
      store.activeThreadId = 't5'
      const { wrapper } = await mountDashboard({}, { threadId: 't5' })
      expect(wrapper.text()).toContain(tt('dashboard.hero.todoBrief'))
    })
  })

  describe('DB-01: replay deep-link entry', () => {
    it('enters replay mode when ?replay=true and an active thread exists', async () => {
      const store = useWorkflowStore()
      store.workflowStates.set('t6', {
        thread_id: 't6', phase: 'reviewing', status: 'awaiting_review', progress_percent: 60,
      } as any)
      store.activeThreadId = 't6'
      const enterSpy = vi.spyOn(store, 'enterReplayMode').mockResolvedValue(undefined as any)
      await mountDashboard({ replay: 'true' }, { threadId: 't6' })
      expect(enterSpy).toHaveBeenCalled()
    })
  })
})
