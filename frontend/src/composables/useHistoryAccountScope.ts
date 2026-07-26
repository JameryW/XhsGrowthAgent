/**
 * Account-scoped history browsing helpers.
 *
 * History may view any owned account without flipping the workspace active
 * account. Selection is restored via ?account= + sessionStorage, and list
 * payloads are cached so A→B→A switches paint instantly then revalidate.
 */
import { computed, ref, type Ref } from 'vue'
import type { RouteLocationNormalizedLoaded, Router } from 'vue-router'
import type { Account } from '@/api/accounts'
import { listWorkflows } from '@/api/workflow'
import type { WorkflowListItem } from '@/types/workflow'
import {
  HISTORY_ACCOUNT_TOTALS_KEY,
  HISTORY_VIEW_ACCOUNT_KEY,
  readSessionString,
  readSessionTotals,
  writeSessionString,
  writeSessionTotals,
} from '@/utils/accountViewSession'

export { HISTORY_VIEW_ACCOUNT_KEY, HISTORY_ACCOUNT_TOTALS_KEY }

/** Soft max age before a cache entry is treated as stale (still shown, then revalidated). */
export const HISTORY_LIST_CACHE_TTL_MS = 30_000

export type HistoryListCacheEntry = {
  workflows: WorkflowListItem[]
  total: number
  fetchedAt: number
}

export type HistoryAccountChip = {
  id: string
  name: string
  total: number | undefined
  isViewing: boolean
  isWorkspace: boolean
}

type AccountsLike = {
  accounts: Account[]
  activeAccount: Account | null
  activeAccountId: string | null
}

export function readStoredViewAccount(): string | null {
  return readSessionString(HISTORY_VIEW_ACCOUNT_KEY)
}

export function persistViewAccount(accountId: string | null): void {
  writeSessionString(HISTORY_VIEW_ACCOUNT_KEY, accountId)
}

export function readStoredAccountTotals(): Record<string, number> {
  return readSessionTotals(HISTORY_ACCOUNT_TOTALS_KEY)
}

export function persistAccountTotals(totals: Record<string, number>): void {
  writeSessionTotals(HISTORY_ACCOUNT_TOTALS_KEY, totals)
}

export function queryAccountId(route: RouteLocationNormalizedLoaded): string | null {
  const raw = route.query.account
  if (typeof raw === 'string' && raw.trim()) return raw.trim()
  if (Array.isArray(raw) && typeof raw[0] === 'string' && raw[0].trim()) return raw[0].trim()
  return null
}

export function isOwnedAccount(
  accounts: Account[],
  accountId: string | null | undefined,
): accountId is string {
  if (!accountId) return false
  return accounts.some(a => a.id === accountId)
}

export function pickPreferredViewAccount(
  route: RouteLocationNormalizedLoaded,
  accounts: Account[],
  activeAccountId: string | null,
): string | null {
  const candidates = [queryAccountId(route), readStoredViewAccount(), activeAccountId]
  for (const id of candidates) {
    if (isOwnedAccount(accounts, id)) return id
  }
  return activeAccountId
}

export function useHistoryAccountScope(options: {
  route: RouteLocationNormalizedLoaded
  router: Router
  accountsStore: AccountsLike
  locale: Ref<string> | { value: string }
}) {
  const { route, router, accountsStore, locale } = options

  const historyAccountId = ref<string | null>(null)
  // Hydrate chip badges from the last session so multi-account UI isn't empty
  // for one network round-trip on every History remount.
  const accountTotals = ref<Record<string, number>>(readStoredAccountTotals())
  const listCache = ref<Record<string, HistoryListCacheEntry>>({})
  const prefetchingIds = ref<Set<string>>(new Set())
  /** Debounce timers for hover/focus prefetch (avoids burst on rapid chip scan). */
  const prefetchTimers = new Map<string, ReturnType<typeof setTimeout>>()

  let suppressQueryWatch = false
  const isSuppressingQueryWatch = () => suppressQueryWatch

  const viewAccountName = computed(() => {
    const id = historyAccountId.value
    const named = accountsStore.accounts.find(a => a.id === id)?.name?.trim()
    if (named) return named
    if (id && accountsStore.activeAccount?.id === id) {
      return accountsStore.activeAccount.name?.trim() || ''
    }
    return accountsStore.activeAccount?.name?.trim() || ''
  })

  const workspaceAccountName = computed(
    () => accountsStore.activeAccount?.name?.trim() || '',
  )

  const hasMultipleAccounts = computed(() => accountsStore.accounts.length > 1)

  const isViewingNonWorkspace = computed(
    () =>
      !!historyAccountId.value
      && !!accountsStore.activeAccountId
      && historyAccountId.value !== accountsStore.activeAccountId,
  )

  const accountChips = computed<HistoryAccountChip[]>(() => {
    const chips = accountsStore.accounts.map(acc => ({
      id: acc.id,
      name: acc.name,
      total: accountTotals.value[acc.id] as number | undefined,
      isViewing: acc.id === historyAccountId.value,
      isWorkspace: acc.id === accountsStore.activeAccountId,
    }))
    const loc = typeof locale === 'object' && 'value' in locale ? locale.value : 'zh-CN'
    return chips.sort((a, b) => {
      if (a.isWorkspace !== b.isWorkspace) return a.isWorkspace ? -1 : 1
      const ta = typeof a.total === 'number' ? a.total : -1
      const tb = typeof b.total === 'number' ? b.total : -1
      if (ta !== tb) return tb - ta
      return a.name.localeCompare(b.name, loc)
    })
  })

  const siblingHints = computed(() =>
    accountChips.value
      .filter(c => !c.isViewing && typeof c.total === 'number' && c.total > 0)
      .map(c => ({ id: c.id, name: c.name, total: c.total as number }))
      .sort((a, b) => b.total - a.total),
  )

  function setAccountTotal(accountId: string, count: number) {
    accountTotals.value = { ...accountTotals.value, [accountId]: count }
    persistAccountTotals(accountTotals.value)
  }

  function getCachedList(accountId: string): HistoryListCacheEntry | null {
    return listCache.value[accountId] ?? null
  }

  function setCachedList(accountId: string, workflows: WorkflowListItem[], total: number) {
    listCache.value = {
      ...listCache.value,
      [accountId]: {
        workflows: [...workflows],
        total,
        fetchedAt: Date.now(),
      },
    }
    setAccountTotal(accountId, total)
  }

  function invalidateCachedList(accountId: string) {
    if (!listCache.value[accountId]) return
    const next = { ...listCache.value }
    delete next[accountId]
    listCache.value = next
  }

  function isCacheFresh(entry: HistoryListCacheEntry | null | undefined): boolean {
    if (!entry) return false
    return Date.now() - entry.fetchedAt < HISTORY_LIST_CACHE_TTL_MS
  }

  function syncAccountQuery(accountId: string | null) {
    const current = queryAccountId(route)
    if ((accountId || null) === (current || null)) return
    const nextQuery: Record<string, string | string[]> = {
      ...(route.query as Record<string, string | string[]>),
    }
    if (accountId) nextQuery.account = accountId
    else delete nextQuery.account
    suppressQueryWatch = true
    void router.replace({ query: nextQuery }).finally(() => {
      suppressQueryWatch = false
    })
  }

  function applyViewAccount(accountId: string, { syncUrl = true }: { syncUrl?: boolean } = {}) {
    historyAccountId.value = accountId
    persistViewAccount(accountId)
    if (syncUrl) syncAccountQuery(accountId)
  }

  function resolveOwned(accountId: string | null | undefined): accountId is string {
    return isOwnedAccount(accountsStore.accounts, accountId)
  }

  function pickPreferred(): string | null {
    return pickPreferredViewAccount(route, accountsStore.accounts, accountsStore.activeAccountId)
  }

  /** Warm cache for a non-viewing account (hover / focus). */
  async function prefetchAccount(accountId: string): Promise<void> {
    if (!accountId || !resolveOwned(accountId)) return
    if (listCache.value[accountId] || prefetchingIds.value.has(accountId)) return
    if (accountId === historyAccountId.value) return

    const next = new Set(prefetchingIds.value)
    next.add(accountId)
    prefetchingIds.value = next
    try {
      const res = await listWorkflows(
        { account_id: accountId, limit: 50 },
        { suppressToast: true },
      )
      // Don't overwrite a fresher entry filled by a concurrent full fetch.
      if (!listCache.value[accountId]) {
        setCachedList(accountId, res.workflows ?? [], res.total ?? 0)
      }
    } catch {
      // ignore prefetch failures — click path will surface errors
    } finally {
      const done = new Set(prefetchingIds.value)
      done.delete(accountId)
      prefetchingIds.value = done
    }
  }

  /** Debounced prefetch — used on mouseenter/focus to avoid N parallel on rapid scan. */
  function schedulePrefetch(accountId: string, delayMs = 140): void {
    if (!accountId || accountId === historyAccountId.value) return
    if (listCache.value[accountId]) return
    const existing = prefetchTimers.get(accountId)
    if (existing) clearTimeout(existing)
    prefetchTimers.set(
      accountId,
      setTimeout(() => {
        prefetchTimers.delete(accountId)
        void prefetchAccount(accountId)
      }, delayMs),
    )
  }

  function cancelScheduledPrefetch(accountId?: string): void {
    if (accountId) {
      const t = prefetchTimers.get(accountId)
      if (t) clearTimeout(t)
      prefetchTimers.delete(accountId)
      return
    }
    for (const t of prefetchTimers.values()) clearTimeout(t)
    prefetchTimers.clear()
  }

  function applyAccountTotals(totals: Record<string, number>): void {
    const next = { ...accountTotals.value }
    for (const [id, count] of Object.entries(totals)) {
      if (typeof count === 'number' && Number.isFinite(count)) {
        next[id] = count
      }
    }
    accountTotals.value = next
    persistAccountTotals(next)
  }

  /** Best sibling with history for empty-account auto-browse (excludes viewing). */
  function bestSiblingWithHistory(exceptAccountId: string | null): {
    id: string
    name: string
    total: number
  } | null {
    const hints = accountsStore.accounts
      .filter(a => a.id !== exceptAccountId)
      .map(a => ({
        id: a.id,
        name: a.name,
        total: accountTotals.value[a.id] ?? 0,
      }))
      .filter(h => h.total > 0)
      .sort((a, b) => b.total - a.total)
    return hints[0] ?? null
  }

  return {
    historyAccountId,
    accountTotals,
    listCache,
    prefetchingIds,
    viewAccountName,
    workspaceAccountName,
    hasMultipleAccounts,
    isViewingNonWorkspace,
    accountChips,
    siblingHints,
    setAccountTotal,
    applyAccountTotals,
    bestSiblingWithHistory,
    getCachedList,
    setCachedList,
    invalidateCachedList,
    isCacheFresh,
    applyViewAccount,
    resolveOwned,
    pickPreferred,
    queryAccountId: () => queryAccountId(route),
    isSuppressingQueryWatch,
    prefetchAccount,
    schedulePrefetch,
    cancelScheduledPrefetch,
  }
}
