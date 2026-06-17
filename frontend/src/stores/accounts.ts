import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Account, Credential } from '@/api/accounts'
import {
  listAccounts,
  getActiveAccount,
  createAccount as apiCreate,
  updateAccount as apiUpdate,
  deleteAccount as apiDelete,
  listCredentials as apiListCreds,
  setCredentials as apiSetCreds,
  deleteCredential as apiDeleteCred,
} from '@/api/accounts'

export const useAccountsStore = defineStore('accounts', () => {
  // ── State ──
  const accounts = ref<Account[]>([])
  const activeAccount = ref<Account | null>(null)
  const credentials = ref<Credential[]>([])
  const isLoading = ref(false)
  const error = ref<string | null>(null)

  // ── Computed ──
  const activeAccountId = computed(() => activeAccount.value?.id ?? null)
  const accountOptions = computed(() =>
    accounts.value.map(a => ({ id: a.id, name: a.name, isActive: a.is_active }))
  )

  // ── Actions ──

  async function fetchAccounts() {
    isLoading.value = true
    error.value = null
    try {
      accounts.value = await listAccounts()
      // Also fetch active account
      activeAccount.value = await getActiveAccount()
    } catch (e: any) {
      error.value = e.message
    } finally {
      isLoading.value = false
    }
  }

  async function createAccount(name: string) {
    const account = await apiCreate(name)
    accounts.value.push(account)
    return account
  }

  async function setActiveAccount(accountId: string) {
    const updated = await apiUpdate(accountId, { is_active: true })
    // Refresh list to reflect active state changes
    await fetchAccounts()
    // Also reload credentials for the new active account
    if (updated) {
      await fetchCredentials(accountId)
    }
    return updated
  }

  async function updateAccountName(accountId: string, name: string) {
    const updated = await apiUpdate(accountId, { name })
    const idx = accounts.value.findIndex(a => a.id === accountId)
    if (idx >= 0) accounts.value[idx] = { ...accounts.value[idx], name: updated.name }
    return updated
  }

  async function removeAccount(accountId: string) {
    await apiDelete(accountId)
    accounts.value = accounts.value.filter(a => a.id !== accountId)
    // If deleted the active account, refresh active
    if (activeAccount.value?.id === accountId) {
      activeAccount.value = await getActiveAccount()
      credentials.value = []
    }
  }

  async function fetchCredentials(accountId: string) {
    try {
      credentials.value = await apiListCreds(accountId)
    } catch (e: any) {
      error.value = e.message
      credentials.value = []
    }
  }

  async function saveCredentials(accountId: string, creds: Record<string, string>) {
    const result = await apiSetCreds(accountId, creds)
    // Refresh credentials display
    await fetchCredentials(accountId)
    return result
  }

  async function removeCredential(accountId: string, keyName: string) {
    await apiDeleteCred(accountId, keyName)
    credentials.value = credentials.value.filter(c => c.key_name !== keyName)
  }

  return {
    accounts,
    activeAccount,
    credentials,
    isLoading,
    error,
    activeAccountId,
    accountOptions,
    fetchAccounts,
    createAccount,
    setActiveAccount,
    updateAccountName,
    removeAccount,
    fetchCredentials,
    saveCredentials,
    removeCredential,
  }
})
