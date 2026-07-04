<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useAccountsStore } from '@/stores/accounts'
import { useToastStore } from '@/stores/toast'
import {
  getAccountLoginStatus,
  type Account,
  type AccountLoginStatus,
  type AccountLoginStatusValue,
} from '@/api/accounts'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import QrLoginModal from './QrLoginModal.vue'

const { t } = useI18n()
const store = useAccountsStore()
const toast = useToastStore()

const newAccountName = ref('')
const isCreating = ref(false)
const editingAccountId = ref<string | null>(null)

type LoginStatusValue = AccountLoginStatusValue | 'checking'
type LoginStatusView = AccountLoginStatus | {
  account_id: string
  status: 'checking'
  is_logged_in: false
  reason?: string
}

const loginStatuses = ref<Record<string, LoginStatusView>>({})
const isRefreshingLoginStatuses = ref(false)

// ── Scan-login (QR) modal state ──
const qrLoginOpen = ref(false)
const qrLoginAccountId = ref<string>('')
const qrLoginAccountName = ref<string>('')

const qrLoginAccount = computed(() =>
  store.accounts.find(a => a.id === qrLoginAccountId.value)
)

onMounted(async () => {
  await store.fetchAccounts()
  if (store.activeAccountId) {
    editingAccountId.value = store.activeAccountId
  }
  await refreshAllLoginStatuses()
})

async function createAccount() {
  if (!newAccountName.value.trim()) return
  isCreating.value = true
  try {
    const account = await store.createAccount(newAccountName.value.trim())
    newAccountName.value = ''
    toast.success(t('settings.toasts.accountCreated', { name: account.name }))
    editingAccountId.value = account.id
    await refreshLoginStatus(account.id)
  } catch (e: any) {
    toast.error(e.message)
  } finally {
    isCreating.value = false
  }
}

async function activateAccount(accountId: string) {
  try {
    await store.setActiveAccount(accountId)
    toast.success(t('settings.toasts.activeSwitched'))
  } catch (e: any) {
    toast.error(e.message)
  }
}

async function removeAccount(accountId: string, name: string) {
  if (!confirm(t('settings.confirm.delete', { name }))) return
  try {
    await store.removeAccount(accountId)
    if (editingAccountId.value === accountId) editingAccountId.value = null
    toast.success(t('settings.toasts.accountDeleted', { name }))
  } catch (e: any) {
    toast.error(e.message)
  }
}

function canScanLogin(account: Account): boolean {
  const status = loginStatusFor(account.id).status
  return Boolean(account.chrome_profile_path && account.cdp_port && status !== 'unavailable')
}

function setLoginStatus(accountId: string, status: LoginStatusView) {
  loginStatuses.value = { ...loginStatuses.value, [accountId]: status }
}

async function refreshLoginStatus(accountId: string) {
  setLoginStatus(accountId, {
    account_id: accountId,
    status: 'checking',
    is_logged_in: false,
  })
  try {
    setLoginStatus(accountId, await getAccountLoginStatus(accountId))
  } catch (e: any) {
    setLoginStatus(accountId, {
      account_id: accountId,
      status: 'unknown',
      is_logged_in: false,
      reason: 'request_failed',
      message: e?.message,
    })
  }
}

async function refreshAllLoginStatuses() {
  if (store.accounts.length === 0) return
  isRefreshingLoginStatuses.value = true
  try {
    await Promise.allSettled(store.accounts.map(account => refreshLoginStatus(account.id)))
  } finally {
    isRefreshingLoginStatuses.value = false
  }
}

function loginStatusFor(accountId: string): LoginStatusView {
  return loginStatuses.value[accountId] ?? {
    account_id: accountId,
    status: 'checking',
    is_logged_in: false,
  }
}

function loginStatusText(accountId: string): string {
  const status = loginStatusFor(accountId)
  switch (status.status) {
    case 'logged_in': return t('settings.xhsAccounts.loginStatusLoggedIn')
    case 'logged_out': return t('settings.xhsAccounts.loginStatusLoggedOut')
    case 'unavailable':
      if (status.reason === 'missing_profile') return t('settings.xhsAccounts.loginStatusMissingProfile')
      if (status.reason === 'cdp_port_down') return t('settings.xhsAccounts.loginStatusBrowserDown')
      if (status.reason === 'cdp_unreachable') return t('settings.xhsAccounts.loginStatusCdpUnreachable')
      return t('settings.xhsAccounts.loginStatusUnavailable')
    case 'unknown': return t('settings.xhsAccounts.loginStatusUnknown')
    case 'checking': return t('settings.xhsAccounts.loginStatusChecking')
  }
}

function loginStatusIcon(accountId: string): string {
  const value: LoginStatusValue = loginStatusFor(accountId).status
  switch (value) {
    case 'logged_in': return 'CheckCircle'
    case 'logged_out': return 'LogOut'
    case 'unavailable': return 'WifiOff'
    case 'unknown': return 'AlertCircle'
    case 'checking': return 'Loader2'
  }
}

function loginStatusClass(accountId: string): string {
  const value: LoginStatusValue = loginStatusFor(accountId).status
  switch (value) {
    case 'logged_in': return 'text-emerald-600'
    case 'logged_out': return 'text-slate-400'
    case 'unavailable': return 'text-amber-600'
    case 'unknown': return 'text-rose-500'
    case 'checking': return 'text-slate-400'
  }
}

function openQrLogin(account: Account) {
  if (!canScanLogin(account)) {
    toast.error(t('settings.xhsAccounts.loginStatusUnavailable'))
    return
  }
  qrLoginAccountId.value = account.id
  qrLoginAccountName.value = account.name
  qrLoginOpen.value = true
}

function closeQrLogin() {
  qrLoginOpen.value = false
}

function onQrConfirmed() {
  toast.success(t('settings.toasts.qrLoginSuccess', { name: qrLoginAccountName.value }))
  setLoginStatus(qrLoginAccountId.value, {
    account_id: qrLoginAccountId.value,
    status: 'logged_in',
    is_logged_in: true,
    reason: 'qr_confirmed',
  })
  qrLoginOpen.value = false
}
</script>

<template>
  <div class="space-y-6">
    <div>
      <h2 class="text-lg font-semibold text-slate-800">{{ t('settings.xhsAccounts.title') }}</h2>
      <p class="text-xs text-slate-400 mt-0.5">{{ t('settings.xhsAccounts.subtitle') }}</p>
    </div>

    <!-- Account list + creation -->
    <div class="rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 space-y-3">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wider">{{ t('settings.accounts') }}</h3>
          <button
            type="button"
            class="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
            :title="t('settings.xhsAccounts.refreshLoginStatus')"
            @click="refreshAllLoginStatuses"
          >
            <AppIcon name="RefreshCw" size="xs" variant="cyan" :animate="isRefreshingLoginStatuses" />
          </button>
        </div>
        <form @submit.prevent="createAccount" class="flex items-center gap-2">
          <input
            v-model="newAccountName"
            type="text"
            :placeholder="t('settings.accountNamePlaceholder')"
            class="px-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none w-40"
          />
          <NeonButton variant="pink" size="sm" :loading="isCreating" type="submit">
            <AppIcon name="Plus" size="xs" variant="white" />
            <span class="ml-1">{{ t('settings.addAccount') }}</span>
          </NeonButton>
        </form>
      </div>

      <div v-if="store.accounts.length === 0" class="text-center py-8 text-slate-400 text-sm">
        {{ t('settings.noAccounts') }}
      </div>

      <div v-for="account in store.accounts" :key="account.id"
        class="rounded-lg border p-3 flex items-center gap-3 transition-all cursor-pointer"
        :class="editingAccountId === account.id
          ? 'border-rose-200 bg-rose-50/50 shadow-sm'
          : 'border-slate-100 hover:border-slate-200 hover:bg-slate-50/50'"
        @click="editingAccountId = account.id"
      >
        <div class="w-2 h-2 rounded-full shrink-0" :class="account.is_active ? 'bg-emerald-500' : 'bg-slate-300'" />
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium truncate" :class="account.is_active ? 'text-slate-800' : 'text-slate-500'">
            {{ account.name }}
          </div>
          <div class="mt-1 flex items-center gap-1 text-[11px]" :class="loginStatusClass(account.id)">
            <AppIcon
              :name="loginStatusIcon(account.id)"
              size="xs"
              :variant="loginStatusFor(account.id).status === 'logged_in' ? 'cyan' : 'pink'"
              :animate="loginStatusFor(account.id).status === 'checking'"
            />
            <span>{{ loginStatusText(account.id) }}</span>
          </div>
        </div>
        <span v-if="account.is_active"
          class="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-600 font-medium"
        >
          {{ t('settings.active') }}
        </span>
        <div class="flex items-center gap-1" @click.stop>
          <button @click="openQrLogin(account)"
            class="text-xs px-2 py-1 rounded transition-colors flex items-center gap-1"
            :class="canScanLogin(account)
              ? 'text-rose-500 hover:text-rose-600 hover:bg-rose-50'
              : 'text-slate-300 cursor-not-allowed'"
            :disabled="!canScanLogin(account)"
            :title="canScanLogin(account) ? t('settings.xhsAccounts.qrLogin') : t('settings.xhsAccounts.loginStatusUnavailable')"
          >
            <AppIcon name="LogIn" size="xs" variant="pink" />
            <span>{{ t('settings.xhsAccounts.qrLogin') }}</span>
          </button>
          <button v-if="!account.is_active" @click="activateAccount(account.id)"
            class="text-xs text-teal-600 hover:text-teal-700 px-2 py-1 rounded hover:bg-teal-50 transition-colors"
          >
            {{ t('settings.activate') }}
          </button>
          <button @click="removeAccount(account.id, account.name)"
            class="text-xs text-rose-400 hover:text-rose-500 px-1 py-1 rounded hover:bg-rose-50 transition-colors"
          >
            <AppIcon name="Trash2" size="xs" variant="pink" />
          </button>
        </div>
      </div>
    </div>

    <!-- Scan-login (QR) modal -->
    <QrLoginModal
      v-if="qrLoginOpen && qrLoginAccount"
      :account-id="qrLoginAccountId"
      :account-name="qrLoginAccountName"
      :is-open="qrLoginOpen"
      @close="closeQrLogin"
      @confirmed="onQrConfirmed"
    />
  </div>
</template>
