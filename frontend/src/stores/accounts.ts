import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Account } from '@/api/accounts'
import {
  listAccounts,
  getActiveAccount,
  createAccount as apiCreate,
  updateAccount as apiUpdate,
  deleteAccount as apiDelete,
} from '@/api/accounts'

/** Skip network when a recent successful fetch is still warm (page re-entry). */
const ACCOUNTS_FRESH_MS = 30_000

/** Console endpoints need a bearer token; a 401 for a guest is expected, not a
 *  failure to report. (The Navbar/tab bars call fetchAccounts on every page,
 *  including the public landing page, so an anonymous visitor used to get a
 *  "token expired or invalid" error banner on a site they never logged into.) */
const SESSION_GONE_CODES = new Set([
  'ERROR_AUTH_TOKEN_INVALID',
  'ERROR_AUTH_TOKEN_MISSING',
  'ERROR_AUTH_TOKEN_EXPIRED',
])

export const useAccountsStore = defineStore('accounts', () => {
  // ── State ──
  const accounts = ref<Account[]>([])
  const activeAccount = ref<Account | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  /** Timestamp of last successful fetch (0 = never). */
  const lastFetchedAt = ref(0)
  /** In-flight fetch so concurrent callers share one round-trip. */
  let inFlight: Promise<void> | null = null

  // ── Computed ──
  const activeAccountId = computed(() => activeAccount.value?.id ?? null)
  const accountOptions = computed(() =>
    accounts.value.map(a => ({ id: a.id, name: a.name, isActive: a.is_active }))
  )

  // ── Actions ──

  async function fetchAccounts(options?: { force?: boolean }) {
    const force = options?.force === true
    const fresh =
      !force
      && lastFetchedAt.value > 0
      && Date.now() - lastFetchedAt.value < ACCOUNTS_FRESH_MS
      && accounts.value.length > 0

    if (fresh) return
    if (inFlight) return inFlight

    isLoading.value = true
    error.value = null
    inFlight = (async () => {
      try {
        // Parallelize list + active (was sequential = 2 RTTs).
        const [list, active] = await Promise.all([listAccounts(), getActiveAccount()])
        accounts.value = list
        activeAccount.value = active
        lastFetchedAt.value = Date.now()
      } catch (e: any) {
        // A dead/absent console session is not a fetch failure worth shouting
        // about: api/client.ts already dropped the stale token and the router
        // guard sends protected pages to /login.
        error.value = SESSION_GONE_CODES.has(e?.code) ? null : e.message
      } finally {
        isLoading.value = false
        inFlight = null
      }
    })()
    return inFlight
  }

  async function createAccount(name: string) {
    const account = await apiCreate(name)
    accounts.value.push(account)
    return account
  }

  async function setActiveAccount(accountId: string) {
    const updated = await apiUpdate(accountId, { is_active: true })
    // Refresh list to reflect active state changes
    await fetchAccounts({ force: true })
    return updated
  }

  async function updateAccountName(accountId: string, name: string) {
    const updated = await apiUpdate(accountId, { name })
    const idx = accounts.value.findIndex(a => a.id === accountId)
    if (idx >= 0) accounts.value[idx] = { ...accounts.value[idx], name: updated.name }
    return updated
  }

  /** Apply a verified Creator Center display name to the local account cache. */
  function syncImportedAccountName(accountId: string, name: string) {
    const importedName = name.trim()
    if (!accountId || !importedName) return

    const idx = accounts.value.findIndex(a => a.id === accountId)
    if (idx >= 0 && accounts.value[idx].name !== importedName) {
      accounts.value[idx] = { ...accounts.value[idx], name: importedName }
    }
    if (activeAccount.value?.id === accountId && activeAccount.value.name !== importedName) {
      activeAccount.value = { ...activeAccount.value, name: importedName }
    }
  }

  async function updateAccountFields(
    accountId: string,
    data: { name?: string; is_active?: boolean; niche?: string; niche_source?: string }
  ) {
    const updated = await apiUpdate(accountId, data)
    const idx = accounts.value.findIndex(a => a.id === accountId)
    if (idx >= 0) {
      accounts.value[idx] = { ...accounts.value[idx], ...updated }
    }
    if (activeAccount.value?.id === accountId) {
      activeAccount.value = { ...activeAccount.value, ...updated }
    }
    return updated
  }

  async function removeAccount(accountId: string) {
    await apiDelete(accountId)
    accounts.value = accounts.value.filter(a => a.id !== accountId)
    // If deleted the active account, refresh active
    if (activeAccount.value?.id === accountId) {
      activeAccount.value = await getActiveAccount()
    }
  }

  return {
    accounts,
    activeAccount,
    isLoading,
    error,
    activeAccountId,
    accountOptions,
    fetchAccounts,
    createAccount,
    setActiveAccount,
    updateAccountName,
    syncImportedAccountName,
    updateAccountFields,
    removeAccount,
  }
})
