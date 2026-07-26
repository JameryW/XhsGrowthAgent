import { describe, it, expect, vi } from 'vitest'
import { ref } from 'vue'
import { useLocalAccountBrowse } from '@/composables/useLocalAccountBrowse'

describe('useLocalAccountBrowse', () => {
  it('builds chips and detects non-workspace browse', () => {
    const selectedAccountId = ref('acct-b')
    const accountsStore = {
      accounts: [
        { id: 'acct-a', name: 'Workspace', is_active: true, created_at: '' },
        { id: 'acct-b', name: 'Other', is_active: false, created_at: '' },
      ],
      activeAccountId: 'acct-a',
      activeAccount: { id: 'acct-a', name: 'Workspace', is_active: true, created_at: '' },
      setActiveAccount: vi.fn(),
    }
    const browse = useLocalAccountBrowse({
      accountsStore: accountsStore as any,
      selectedAccountId,
      locale: ref('zh-CN'),
    })
    expect(browse.hasMultipleAccounts.value).toBe(true)
    expect(browse.isViewingNonWorkspace.value).toBe(true)
    expect(browse.accountChips.value[0].isWorkspace).toBe(true)
    expect(browse.viewAccountName.value).toBe('Other')
  })

  it('promotes the browsed account to workspace', async () => {
    const selectedAccountId = ref('acct-b')
    const setActiveAccount = vi.fn().mockResolvedValue({})
    const accountsStore = {
      accounts: [
        { id: 'acct-a', name: 'Workspace', is_active: true, created_at: '' },
        { id: 'acct-b', name: 'Other', is_active: false, created_at: '' },
      ],
      activeAccountId: 'acct-a',
      activeAccount: { id: 'acct-a', name: 'Workspace', is_active: true, created_at: '' },
      setActiveAccount,
    }
    const onSelected = vi.fn()
    const browse = useLocalAccountBrowse({
      accountsStore: accountsStore as any,
      selectedAccountId,
      locale: ref('en'),
      onSelected,
    })
    const result = await browse.promoteToWorkspace()
    expect(result.ok).toBe(true)
    expect(setActiveAccount).toHaveBeenCalledWith('acct-b')
    expect(onSelected).toHaveBeenCalledWith('acct-b', { isWorkspace: true })
  })
})
