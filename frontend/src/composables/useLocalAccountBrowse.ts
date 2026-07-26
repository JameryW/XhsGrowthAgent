/**
 * Shared local multi-account browse helpers for Analytics / Evaluation pages.
 * Viewing may differ from workspace active; promote/back helpers flip only when asked.
 */
import { computed, type Ref } from 'vue'
import type { Account } from '@/api/accounts'

type AccountsLike = {
  accounts: Account[]
  activeAccountId: string | null
  activeAccount: Account | null
  setActiveAccount: (id: string) => Promise<unknown>
}

export function useLocalAccountBrowse(options: {
  accountsStore: AccountsLike
  selectedAccountId: Ref<string>
  locale: Ref<string> | { value: string }
  /** When true, selecting workspace account clears "user selected" style flags via return. */
  onSelected?: (accountId: string, meta: { isWorkspace: boolean }) => void
}) {
  const { accountsStore, selectedAccountId, locale, onSelected } = options

  const hasMultipleAccounts = computed(() => accountsStore.accounts.length > 1)

  const isViewingNonWorkspace = computed(
    () =>
      !!selectedAccountId.value
      && !!accountsStore.activeAccountId
      && selectedAccountId.value !== accountsStore.activeAccountId,
  )

  const viewAccountName = computed(() => {
    const id = selectedAccountId.value
    return (
      accountsStore.accounts.find(a => a.id === id)?.name?.trim()
      || accountsStore.activeAccount?.name?.trim()
      || ''
    )
  })

  const workspaceAccountName = computed(
    () => accountsStore.activeAccount?.name?.trim() || '',
  )

  const accountChips = computed(() => {
    const chips = accountsStore.accounts.map(acc => ({
      id: acc.id,
      name: acc.name,
      isViewing: acc.id === selectedAccountId.value,
      isWorkspace: acc.id === accountsStore.activeAccountId,
    }))
    const loc = typeof locale === 'object' && 'value' in locale ? locale.value : 'zh-CN'
    return chips.sort((a, b) => {
      if (a.isWorkspace !== b.isWorkspace) return a.isWorkspace ? -1 : 1
      return a.name.localeCompare(b.name, loc)
    })
  })

  function selectAccount(accountId: string): boolean {
    if (!accountId || accountId === selectedAccountId.value) return false
    if (!accountsStore.accounts.some(a => a.id === accountId)) return false
    selectedAccountId.value = accountId
    const isWorkspace = accountId === accountsStore.activeAccountId
    onSelected?.(accountId, { isWorkspace })
    return true
  }

  function backToWorkspace(): boolean {
    const id = accountsStore.activeAccountId
    if (!id) return false
    return selectAccount(id)
  }

  async function promoteToWorkspace(): Promise<{ ok: boolean; name: string; error?: string }> {
    const accountId = selectedAccountId.value
    const name =
      accountsStore.accounts.find(a => a.id === accountId)?.name?.trim() || accountId
    if (!accountId || accountId === accountsStore.activeAccountId) {
      return { ok: false, name, error: 'noop' }
    }
    try {
      await accountsStore.setActiveAccount(accountId)
      onSelected?.(accountId, { isWorkspace: true })
      return { ok: true, name }
    } catch (e: unknown) {
      return {
        ok: false,
        name,
        error: e instanceof Error ? e.message : String(e),
      }
    }
  }

  return {
    hasMultipleAccounts,
    isViewingNonWorkspace,
    viewAccountName,
    workspaceAccountName,
    accountChips,
    selectAccount,
    backToWorkspace,
    promoteToWorkspace,
  }
}
