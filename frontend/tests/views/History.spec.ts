// History view: local view-account, URL/session persistence, workspace follow rules.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import History from '@/views/History.vue'
import i18n from '@/locales'
import { useAccountsStore } from '@/stores/accounts'

const tt = (key: string, params?: Record<string, unknown>) =>
  i18n.global.t(key, params as any)

const HISTORY_VIEW_ACCOUNT_KEY = 'xhs.history.viewAccountId'

vi.mock('@/api/workflow', () => ({
  listWorkflows: vi.fn(),
  deleteWorkflow: vi.fn(),
  getWorkflowAccountTotals: vi.fn().mockImplementation(async () => ({
    totals: { 'acct-a': 1, 'acct-b': 2 },
  })),
}))

vi.mock('@/api/publicShowcase', () => ({
  revokeShowcaseVisibility: vi.fn(),
  updateShowcaseVisibility: vi.fn(),
}))

vi.mock('@/api/free', () => ({
  listFreeDrafts: vi.fn(),
  deleteFreeDraft: vi.fn(),
}))

vi.mock('@/api/accounts', () => ({
  KNOWN_NICHES: [],
  listAccounts: vi.fn().mockResolvedValue([
    { id: 'acct-a', name: '麦当劳不要可乐', is_active: true, created_at: '' },
    { id: 'acct-b', name: 'Jamery的AI判断', is_active: false, created_at: '' },
  ]),
  getActiveAccount: vi.fn().mockResolvedValue({
    id: 'acct-a',
    name: '麦当劳不要可乐',
    is_active: true,
    created_at: '',
  }),
  createAccount: vi.fn(),
  updateAccount: vi.fn().mockImplementation(async (id: string, data: { is_active?: boolean }) => {
    if (data.is_active) {
      return {
        id,
        name: id === 'acct-b' ? 'Jamery的AI判断' : '麦当劳不要可乐',
        is_active: true,
        created_at: '',
      }
    }
    return { id, name: id, is_active: false, created_at: '' }
  }),
  deleteAccount: vi.fn(),
  resolveAccountNiche: vi.fn(),
  getAccountLoginStatus: vi.fn(),
  startQrLogin: vi.fn(),
  getQrLoginStatus: vi.fn(),
}))

async function resetAccountMocks() {
  const accountsApi = await import('@/api/accounts')
  ;(accountsApi.listAccounts as any).mockResolvedValue([
    { id: 'acct-a', name: '麦当劳不要可乐', is_active: true, created_at: '' },
    { id: 'acct-b', name: 'Jamery的AI判断', is_active: false, created_at: '' },
  ])
  ;(accountsApi.getActiveAccount as any).mockResolvedValue({
    id: 'acct-a',
    name: '麦当劳不要可乐',
    is_active: true,
    created_at: '',
  })
  ;(accountsApi.updateAccount as any).mockImplementation(
    async (id: string, data: { is_active?: boolean }) => {
      if (data.is_active) {
        return {
          id,
          name: id === 'acct-b' ? 'Jamery的AI判断' : '麦当劳不要可乐',
          is_active: true,
          created_at: '',
        }
      }
      return { id, name: id, is_active: false, created_at: '' }
    },
  )
}

function workflowItem(overrides: Record<string, unknown> = {}) {
  return {
    thread_id: 'xhs_acct-a_1',
    account_id: 'acct-a',
    phase: 'completed',
    status: 'completed',
    dry_run: false,
    auto_publish: false,
    progress_percent: 100,
    workflow_mode: 'trend',
    label: 'active-run',
    created_at: '2026-07-22T00:00:00Z',
    updated_at: '2026-07-22T00:00:00Z',
    error: null,
    ...overrides,
  }
}

function mockListByAccount() {
  return async (params: { account_id?: string; limit?: number }) => {
    if (params?.account_id === 'acct-b') {
      if (params.limit === 1) {
        return { workflows: [], total: 2, limit: 1, offset: 0 }
      }
      return {
        workflows: [
          workflowItem({
            thread_id: 'xhs_acct-b_abc',
            account_id: 'acct-b',
            label: 'sibling-run',
            dry_run: true,
          }),
        ],
        total: 2,
        limit: 50,
        offset: 0,
      }
    }
    if (params?.account_id === 'acct-a' || !params?.account_id) {
      if (params?.limit === 1) {
        return { workflows: [], total: 1, limit: 1, offset: 0 }
      }
      return {
        workflows: [workflowItem()],
        total: 1,
        limit: 50,
        offset: 0,
      }
    }
    return { workflows: [], total: 0, limit: 50, offset: 0 }
  }
}

async function mountHistory(options?: { query?: Record<string, string> }) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/history', name: 'history', component: History },
      { path: '/start', name: 'start', component: { template: '<div />' } },
      { path: '/dashboard', name: 'dashboard', component: { template: '<div />' } },
    ],
  })
  await router.push({ name: 'history', query: options?.query })
  await router.isReady()
  const wrapper = mount(History, {
    global: {
      plugins: [router],
      stubs: {
        AppIcon: true,
        NeonButton: {
          props: ['loading', 'variant', 'size'],
          template: '<button type="button" @click="$emit(\'click\')"><slot /></button>',
        },
        PageHeader: {
          template: '<div><slot name="meta" /><slot name="actions" /></div>',
        },
        ConfirmModal: true,
      },
    },
  })
  await flushPromises()
  await flushPromises()
  return { wrapper, router }
}

describe('History view', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    sessionStorage.clear()
    await resetAccountMocks()
  })

  afterEach(() => {
    sessionStorage.clear()
  })

  it('scopes the list request to the workspace account and shows viewing label', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())

    const { wrapper } = await mountHistory()
    expect(listWorkflows).toHaveBeenCalledWith(
      expect.objectContaining({ account_id: 'acct-a', limit: 50 }),
      expect.anything(),
    )
    expect(wrapper.text()).toContain(tt('history.scopedTo', { name: '麦当劳不要可乐' }))
    expect(wrapper.text()).toContain(tt('history.workspaceBadge'))
  })

  it('opens the free drafts tab from its deep link and keeps the selected account scope', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    const { listFreeDrafts } = await import('@/api/free')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())
    ;(listFreeDrafts as any).mockResolvedValue({
      account_id: 'acct-b',
      drafts: [{
        draft_id: 'draft-b',
        title: '账号 B 的草稿',
        hashtags: [],
        created_at: '2026-08-22T00:00:00Z',
        updated_at: '2026-08-22T00:00:00Z',
        published: false,
        last_evaluation: null,
      }],
      count: 1,
    })

    const { wrapper, router } = await mountHistory({ query: { account: 'acct-b', tab: 'free-drafts' } })

    expect(wrapper.find('[data-testid="history-tab-free-drafts"]').attributes('aria-selected')).toBe('true')
    expect(wrapper.text()).toContain('账号 B 的草稿')
    expect(listFreeDrafts).toHaveBeenCalledWith('acct-b', { status: 'all' }, expect.objectContaining({ suppressToast: true }))

    await wrapper.find('[data-testid="history-tab-workflows"]').trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.query.tab).toBeUndefined()
    expect(wrapper.text()).toContain('sibling-run')

    await router.back()
    await flushPromises()
    expect(router.currentRoute.value.query.tab).toBe('free-drafts')
    expect(wrapper.find('[data-testid="history-tab-free-drafts"]').attributes('aria-selected')).toBe('true')

    await router.forward()
    await flushPromises()
    expect(router.currentRoute.value.query.tab).toBeUndefined()
    expect(wrapper.find('[data-testid="history-tab-workflows"]').attributes('aria-selected')).toBe('true')

    await router.replace({ query: { account: 'acct-b', tab: 'free-drafts' } })
    await flushPromises()
    expect(wrapper.find('[data-testid="history-tab-free-drafts"]').attributes('aria-selected')).toBe('true')
  })

  it('prefers ?account= query over the workspace active account', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())

    const { wrapper, router } = await mountHistory({ query: { account: 'acct-b' } })

    expect(listWorkflows).toHaveBeenCalledWith(
      expect.objectContaining({ account_id: 'acct-b', limit: 50 }),
      expect.anything(),
    )
    expect(wrapper.text()).toContain('sibling-run')
    expect(wrapper.text()).toContain(
      tt('history.viewOnlyBanner', {
        view: 'Jamery的AI判断',
        workspace: '麦当劳不要可乐',
      }),
    )
    expect(router.currentRoute.value.query.account).toBe('acct-b')
    expect(sessionStorage.getItem(HISTORY_VIEW_ACCOUNT_KEY)).toBe('acct-b')
  })

  it('prefers sessionStorage browse target when query is absent', async () => {
    sessionStorage.setItem(HISTORY_VIEW_ACCOUNT_KEY, 'acct-b')
    const { listWorkflows } = await import('@/api/workflow')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())

    const { wrapper } = await mountHistory()
    expect(listWorkflows).toHaveBeenCalledWith(
      expect.objectContaining({ account_id: 'acct-b', limit: 50 }),
      expect.anything(),
    )
    expect(wrapper.text()).toContain('sibling-run')
  })

  it('browses another account locally without changing workspace active account', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    const { updateAccount } = await import('@/api/accounts')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())

    const { wrapper, router } = await mountHistory()
    // Wait for sibling totals probe.
    await flushPromises()

    const browseBtn = wrapper
      .findAll('button')
      .find(b => b.text().includes('Jamery的AI判断') && /\b2\b/.test(b.text()))
    expect(browseBtn).toBeTruthy()
    await browseBtn!.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(updateAccount).not.toHaveBeenCalled()
    expect(useAccountsStore().activeAccountId).toBe('acct-a')
    expect(wrapper.text()).toContain('sibling-run')
    expect(router.currentRoute.value.query.account).toBe('acct-b')
    expect(sessionStorage.getItem(HISTORY_VIEW_ACCOUNT_KEY)).toBe('acct-b')
  })

  it('does not yank intentional browse when workspace account changes', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())

    const { wrapper } = await mountHistory()
    await flushPromises()

    const browseBtn = wrapper
      .findAll('button')
      .find(b => b.text().includes('Jamery的AI判断') && /\b2\b/.test(b.text()))
    await browseBtn!.trigger('click')
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('sibling-run')

    const callsBefore = (listWorkflows as any).mock.calls.length
    // Simulate navbar flipping workspace to a third owned account without leaving browse of B.
    // accounts store only has a/b in this test — flip active to a is no-op for view.
    // Re-set active to a while viewing b: should keep b.
    const store = useAccountsStore()
    // Force a workspace change A → (still A doesn't fire). Use setActiveAccount mock path:
    // Manually mutate as if another page changed active to acct-a while viewing b — already a.
    // Switch workspace via store fields to simulate external change without promote.
    store.activeAccount = {
      id: 'acct-a',
      name: '麦当劳不要可乐',
      is_active: true,
      created_at: '',
    } as any
    // Now set activeAccount to something different: inject B as workspace while already viewing B.
    // Better: start viewing B with workspace A, then change workspace to A is same.
    // Change workspace by assigning activeAccount to a fake re-fetch cycle:
    ;(store as any).activeAccount = {
      id: 'acct-a',
      name: '麦当劳不要可乐',
      is_active: true,
      created_at: '',
    }

    // Directly invoke the intended contract: viewing B, workspace changes from A to A — no-op.
    // Simulate prev workspace A → new workspace stays A but we need prev !== next.
    // Use accounts API to set active B as workspace while viewing B would align them.
    // Contract under test: viewing B (workspace A). Workspace becomes A still.
    // Instead patch store.activeAccountId by replacing activeAccount with a clone that
    // triggers watch: Vue watch on activeAccountId computed needs actual change.
    store.activeAccount = {
      id: 'acct-c-not-owned',
      name: 'ghost',
      is_active: true,
      created_at: '',
    } as any
    await flushPromises()

    // Still viewing sibling-run (B); did not auto-jump to ghost.
    expect(wrapper.text()).toContain('sibling-run')
    // No new full list for the ghost id.
    const newAccountCalls = (listWorkflows as any).mock.calls
      .slice(callsBefore)
      .filter((c: any[]) => c[0]?.account_id === 'acct-c-not-owned')
    expect(newAccountCalls).toHaveLength(0)
  })

  it('follows workspace change when user was viewing the previous workspace account', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    const { updateAccount, listAccounts, getActiveAccount } = await import('@/api/accounts')

    let activeId = 'acct-a'
    const accountsByActive = () => [
      { id: 'acct-a', name: '麦当劳不要可乐', is_active: activeId === 'acct-a', created_at: '' },
      { id: 'acct-b', name: 'Jamery的AI判断', is_active: activeId === 'acct-b', created_at: '' },
    ]
    ;(listWorkflows as any).mockImplementation(mockListByAccount())
    ;(listAccounts as any).mockImplementation(async () => accountsByActive())
    ;(getActiveAccount as any).mockImplementation(
      async () => accountsByActive().find(a => a.id === activeId) ?? null,
    )
    ;(updateAccount as any).mockImplementation(async (id: string, data: { is_active?: boolean }) => {
      if (data.is_active) activeId = id
      return accountsByActive().find(a => a.id === id)!
    })

    const { wrapper } = await mountHistory()
    expect(wrapper.text()).toContain('active-run')

    // Viewing workspace A; promote/switch workspace to B via store API.
    await useAccountsStore().setActiveAccount('acct-b')
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('sibling-run')
    expect(wrapper.text()).toContain(tt('history.scopedTo', { name: 'Jamery的AI判断' }))
  })

  it('promotes the viewed account to workspace when requested', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    const { updateAccount, listAccounts, getActiveAccount } = await import('@/api/accounts')

    let activeId = 'acct-a'
    const accountsByActive = () => [
      { id: 'acct-a', name: '麦当劳不要可乐', is_active: activeId === 'acct-a', created_at: '' },
      { id: 'acct-b', name: 'Jamery的AI判断', is_active: activeId === 'acct-b', created_at: '' },
    ]
    ;(listWorkflows as any).mockImplementation(mockListByAccount())
    ;(listAccounts as any).mockImplementation(async () => accountsByActive())
    ;(getActiveAccount as any).mockImplementation(
      async () => accountsByActive().find(a => a.id === activeId) ?? null,
    )
    ;(updateAccount as any).mockImplementation(async (id: string, data: { is_active?: boolean }) => {
      if (data.is_active) activeId = id
      return accountsByActive().find(a => a.id === id)!
    })

    const { wrapper } = await mountHistory()
    await flushPromises()

    const browseBtn = wrapper
      .findAll('button')
      .find(b => b.text().includes('Jamery的AI判断') && /\b2\b/.test(b.text()))
    await browseBtn!.trigger('click')
    await flushPromises()
    await flushPromises()

    const promoteBtn = wrapper
      .findAll('button')
      .find(b => b.text().includes(tt('history.useAsWorkspace', { name: 'Jamery的AI判断' })))
    expect(promoteBtn).toBeTruthy()
    await promoteBtn!.trigger('click')
    await flushPromises()
    await flushPromises()

    expect(updateAccount).toHaveBeenCalledWith('acct-b', { is_active: true })
    expect(useAccountsStore().activeAccountId).toBe('acct-b')
  })

  it('loads sibling totals via bulk account-totals for chip badges', async () => {
    const { listWorkflows, getWorkflowAccountTotals } = await import('@/api/workflow')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())
    ;(getWorkflowAccountTotals as any).mockResolvedValue({
      totals: { 'acct-a': 1, 'acct-b': 2 },
    })

    const { wrapper } = await mountHistory()
    await flushPromises()

    expect(wrapper.text()).toContain('active-run')
    expect(getWorkflowAccountTotals).toHaveBeenCalled()
    // Bulk path should not fall back to N× limit=1 probes for sibling badges.
    expect(listWorkflows).not.toHaveBeenCalledWith(
      expect.objectContaining({ account_id: 'acct-b', limit: 1 }),
      expect.anything(),
    )
    expect(wrapper.text()).toMatch(/Jamery的AI判断[\s\S]*2|2[\s\S]*Jamery的AI判断/)
  })

  it('syncs status filter into the URL query', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    ;(listWorkflows as any).mockImplementation(async (params: { account_id?: string }) => {
      if (params?.account_id === 'acct-a' || !params?.account_id) {
        return {
          workflows: [
            workflowItem({ status: 'completed', label: 'done-run' }),
            workflowItem({
              thread_id: 'xhs_acct-a_2',
              status: 'running',
              label: 'run-run',
              progress_percent: 40,
              phase: 'creating',
            }),
          ],
          total: 2,
          limit: 50,
          offset: 0,
        }
      }
      return { workflows: [], total: 0, limit: 50, offset: 0 }
    })

    const { wrapper, router } = await mountHistory()
    await flushPromises()

    const runningBtn = wrapper.findAll('button').find(b => b.text().includes(tt('history.status.running')))
    expect(runningBtn).toBeTruthy()
    await runningBtn!.trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.query.status).toBe('running')
    expect(wrapper.text()).toContain('run-run')
    expect(wrapper.text()).not.toContain('done-run')
  })

  it('auto-browses to a sibling account when the preferred account is empty', async () => {
    const { listWorkflows, getWorkflowAccountTotals } = await import('@/api/workflow')
    ;(getWorkflowAccountTotals as any).mockResolvedValue({
      totals: { 'acct-a': 0, 'acct-b': 2 },
    })
    ;(listWorkflows as any).mockImplementation(async (params: { account_id?: string; limit?: number }) => {
      if (params?.account_id === 'acct-b' && params.limit !== 1) {
        return {
          workflows: [
            workflowItem({
              thread_id: 'xhs_acct-b_abc',
              account_id: 'acct-b',
              label: 'sibling-run',
            }),
          ],
          total: 2,
          limit: 50,
          offset: 0,
        }
      }
      // Workspace A is empty.
      return { workflows: [], total: 0, limit: 50, offset: 0 }
    })

    const { wrapper } = await mountHistory()
    await flushPromises()
    await flushPromises()

    expect(wrapper.text()).toContain('sibling-run')
    expect(wrapper.text()).toContain(tt('history.autoBrowseNotice', {
      from: '麦当劳不要可乐',
      to: 'Jamery的AI判断',
      count: 2,
    }))
    // Workspace active account must stay on A.
    expect(useAccountsStore().activeAccountId).toBe('acct-a')
  })

  it('skips revalidate when switching back to a still-fresh cached account', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())

    const { wrapper } = await mountHistory()
    await flushPromises()

    const bChip = wrapper
      .findAll('button')
      .find(b => b.text().includes('Jamery的AI判断') && /\b2\b/.test(b.text()))
    await bChip!.trigger('click')
    await flushPromises()
    await flushPromises()

    const callsAfterB = (listWorkflows as any).mock.calls.length
    const aChip = wrapper.findAll('button').find(b => b.text().includes('麦当劳不要可乐'))
    await aChip!.trigger('click')
    await flushPromises()
    // Fresh TTL: paint from cache without another full list for A.
    const aListCalls = (listWorkflows as any).mock.calls
      .slice(callsAfterB)
      .filter((c: any[]) => c[0]?.account_id === 'acct-a' && c[0]?.limit === 50)
    expect(aListCalls).toHaveLength(0)
    expect(wrapper.text()).toContain('active-run')
  })

  it('paints from cache instantly when switching back to a visited account', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())

    const { wrapper } = await mountHistory()
    await flushPromises()

    // Visit B (full list cached), then back to A — A should still show active-run
    // even before the revalidate round-trip settles.
    const bChip = wrapper
      .findAll('button')
      .find(b => b.text().includes('Jamery的AI判断') && /\b2\b/.test(b.text()))
    await bChip!.trigger('click')
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('sibling-run')

    const aChip = wrapper
      .findAll('button')
      .find(b => b.text().includes('麦当劳不要可乐'))
    await aChip!.trigger('click')
    // Immediate paint from cache (before network revalidate).
    expect(wrapper.text()).toContain('active-run')
    await flushPromises()
    await flushPromises()
    expect(wrapper.text()).toContain('active-run')
  })

  it('offers back-to-workspace history without promoting the workspace account', async () => {
    const { listWorkflows } = await import('@/api/workflow')
    const { updateAccount } = await import('@/api/accounts')
    ;(listWorkflows as any).mockImplementation(mockListByAccount())

    const { wrapper } = await mountHistory()
    await flushPromises()

    const bChip = wrapper
      .findAll('button')
      .find(b => b.text().includes('Jamery的AI判断') && /\b2\b/.test(b.text()))
    await bChip!.trigger('click')
    await flushPromises()
    await flushPromises()

    const backBtn = wrapper
      .findAll('button')
      .find(b => b.text().includes(tt('history.backToWorkspaceHistory', { name: '麦当劳不要可乐' })))
    expect(backBtn).toBeTruthy()
    await backBtn!.trigger('click')
    await flushPromises()

    expect(updateAccount).not.toHaveBeenCalled()
    expect(useAccountsStore().activeAccountId).toBe('acct-a')
    expect(wrapper.text()).toContain('active-run')
  })
})
