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
import { syncAllCreatorStats } from '@/api/analytics'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import QrLoginModal from './QrLoginModal.vue'
import CreatorStatsPanel from './CreatorStatsPanel.vue'

const { t } = useI18n()
const store = useAccountsStore()
const toast = useToastStore()

const newAccountName = ref('')
const isCreating = ref(false)
const editingAccountId = ref<string | null>(null)
const showDeleteModal = ref(false)
const deleteTarget = ref<{ id: string; name: string } | null>(null)

// 手动触发同步（与定时任务同一通道：仅同步当前激活账号，有冷却/并发锁）。
const isSyncing = ref(false)
// 同步完成后重建 CreatorStatsPanel 以重新加载导入数据。
const statsPanelKey = ref(0)
const hasActiveAccount = computed(() => store.accounts.some(a => a.is_active))

async function syncNow() {
  if (isSyncing.value) return
  isSyncing.value = true
  try {
    const result = await syncAllCreatorStats({ period: '30d', analyze: true })
    if (result.status === 'cooldown') {
      const minutes = Math.max(1, Math.ceil((result.retry_after_seconds ?? 0) / 60))
      toast.warning(t('settings.xhsAccounts.syncNowCooldown', { minutes }))
      return
    }
    if (result.status === 'already_running') {
      toast.warning(t('settings.xhsAccounts.syncNowAlreadyRunning'))
      return
    }
    if (result.ok) {
      toast.success(t('settings.xhsAccounts.syncNowSuccess', { count: result.succeeded }))
      statsPanelKey.value += 1
      return
    }
    toast.error(result.error || t('settings.xhsAccounts.syncNowFailed'))
  } catch (e: any) {
    toast.error(e?.message || t('settings.xhsAccounts.syncNowFailed'))
  } finally {
    isSyncing.value = false
  }
}

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

/** Per-account anti-risk fuse: block re-scan after 300012 / cooldown. */
const qrRiskBlocks = ref<Record<string, { until: number; message: string; riskCode: string }>>({})
let riskTickTimer: ReturnType<typeof setInterval> | null = null
// Force recompute of remaining seconds every 1s while any block is active.
const riskTick = ref(0)

const qrLoginAccount = computed(() =>
  store.accounts.find(a => a.id === qrLoginAccountId.value)
)

function ensureRiskTicker() {
  if (riskTickTimer) return
  riskTickTimer = setInterval(() => {
    riskTick.value += 1
    const now = Date.now()
    let any = false
    for (const [id, block] of Object.entries(qrRiskBlocks.value)) {
      if (block.until <= now) {
        const next = { ...qrRiskBlocks.value }
        delete next[id]
        qrRiskBlocks.value = next
      } else {
        any = true
      }
    }
    if (!any && riskTickTimer) {
      clearInterval(riskTickTimer)
      riskTickTimer = null
    }
  }, 1000)
}

function qrRiskFor(accountId: string) {
  void riskTick.value
  const block = qrRiskBlocks.value[accountId]
  if (!block) return null
  const remaining = Math.max(0, Math.ceil((block.until - Date.now()) / 1000))
  if (remaining <= 0) return null
  return { ...block, remainingSeconds: remaining }
}

function onQrRiskBlock(payload: { riskCode: string; retryAfterSeconds: number; message: string }) {
  const id = qrLoginAccountId.value
  if (!id) return
  const seconds = Math.max(60, payload.retryAfterSeconds || 900)
  qrRiskBlocks.value = {
    ...qrRiskBlocks.value,
    [id]: {
      until: Date.now() + seconds * 1000,
      message: payload.message,
      riskCode: payload.riskCode,
    },
  }
  ensureRiskTicker()
  toast.warning(payload.message)
}

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
    await refreshAllLoginStatuses()
  } catch (e: any) {
    toast.error(e.message)
  }
}

function requestRemoveAccount(accountId: string, name: string) {
  deleteTarget.value = { id: accountId, name }
  showDeleteModal.value = true
}

async function confirmRemoveAccount() {
  if (!deleteTarget.value) return
  const { id: accountId, name } = deleteTarget.value
  try {
    await store.removeAccount(accountId)
    if (editingAccountId.value === accountId) editingAccountId.value = null
    toast.success(t('settings.toasts.accountDeleted', { name }))
    showDeleteModal.value = false
    deleteTarget.value = null
  } catch (e: any) {
    toast.error(e.message)
  }
}

function canScanLogin(account: Account): boolean {
  const status = loginStatusFor(account.id).status
  return Boolean(account.is_active && account.chrome_profile_path && account.cdp_port && status !== 'unavailable')
}

function setLoginStatus(accountId: string, status: LoginStatusView) {
  loginStatuses.value = { ...loginStatuses.value, [accountId]: status }
}

async function refreshLoginStatus(accountId: string) {
  const account = store.accounts.find(a => a.id === accountId)
  if (account && !account.is_active) {
    setLoginStatus(accountId, {
      account_id: accountId,
      status: 'unavailable',
      is_logged_in: false,
      reason: 'account_inactive',
    })
    return
  }

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
    case 'logged_out':
      // www cookies without creator token used to show a false green "已登录".
      if (status.reason === 'www_only' || status.reason === 'missing_creator_token') {
        return t('settings.xhsAccounts.loginStatusWwwOnly')
      }
      if (status.reason === 'stale_id_token') {
        return t('settings.xhsAccounts.loginStatusStaleSession')
      }
      return t('settings.xhsAccounts.loginStatusLoggedOut')
    case 'unavailable':
      if (status.reason === 'account_inactive') return t('settings.xhsAccounts.loginStatusInactive')
      if (status.reason === 'missing_profile') return t('settings.xhsAccounts.loginStatusMissingProfile')
      if (status.reason === 'cdp_port_down') return t('settings.xhsAccounts.loginStatusBrowserDown')
      if (status.reason === 'cdp_unreachable') return t('settings.xhsAccounts.loginStatusCdpUnreachable')
      return t('settings.xhsAccounts.loginStatusUnavailable')
    case 'unknown': return t('settings.xhsAccounts.loginStatusUnknown')
    case 'checking': return t('settings.xhsAccounts.loginStatusChecking')
  }
}

function loginStatusIcon(accountId: string): string {
  const status = loginStatusFor(accountId)
  const value: LoginStatusValue = status.status
  if (
    value === 'logged_out'
    && (status.reason === 'www_only'
      || status.reason === 'missing_creator_token'
      || status.reason === 'stale_id_token')
  ) {
    return 'AlertCircle'
  }
  switch (value) {
    case 'logged_in': return 'CheckCircle'
    case 'logged_out': return 'LogOut'
    case 'unavailable': return 'WifiOff'
    case 'unknown': return 'AlertCircle'
    case 'checking': return 'Loader2'
  }
}

function loginStatusClass(accountId: string): string {
  const status = loginStatusFor(accountId)
  const value: LoginStatusValue = status.status
  if (status.reason === 'account_inactive') return 'text-slate-400'
  // Partial www session or stale token — warn, do not look fully logged-out gray.
  if (
    value === 'logged_out'
    && (status.reason === 'www_only'
      || status.reason === 'missing_creator_token'
      || status.reason === 'stale_id_token')
  ) {
    return 'text-amber-600'
  }
  switch (value) {
    case 'logged_in': return 'text-emerald-600'
    case 'logged_out': return 'text-slate-400'
    case 'unavailable': return 'text-amber-600'
    case 'unknown': return 'text-rose-500'
    case 'checking': return 'text-slate-400'
  }
}

function openQrLogin(account: Account) {
  if (!account.is_active) {
    toast.error(t('settings.xhsAccounts.loginStatusInactive'))
    return
  }
  if (!canScanLogin(account)) {
    toast.error(t('settings.xhsAccounts.loginStatusUnavailable'))
    return
  }
  const risk = qrRiskFor(account.id)
  if (risk) {
    const minutes = Math.max(1, Math.ceil(risk.remainingSeconds / 60))
    toast.warning(
      risk.message || t('settings.xhsAccounts.qrRiskCooldown', { minutes }),
    )
    return
  }
  qrLoginAccountId.value = account.id
  qrLoginAccountName.value = account.name
  qrLoginOpen.value = true
}

function canOpenQrLogin(account: Account): boolean {
  return canScanLogin(account) && !qrRiskFor(account.id)
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
    <div class="dark-explicit rounded-xl border border-slate-200/50 bg-white/90 backdrop-blur-sm p-4 space-y-3 dark:bg-slate-900/90 dark:border-slate-700/55">
      <div class="flex flex-wrap items-center justify-between gap-2">
        <div class="flex items-center gap-2">
          <h3 class="text-xs font-semibold text-slate-500 uppercase tracking-wider">{{ t('settings.accounts') }}</h3>
          <button
            type="button"
            class="dark-explicit min-h-11 min-w-11 p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors dark:hover:bg-slate-800 dark:hover:text-slate-200"
            :title="t('settings.xhsAccounts.refreshLoginStatus')"
            @click="refreshAllLoginStatuses"
          >
            <AppIcon name="RefreshCw" size="xs" variant="cyan" :animate="isRefreshingLoginStatuses" />
          </button>
          <NeonButton
            variant="purple"
            size="sm"
            :loading="isSyncing"
            :disabled="isSyncing || !hasActiveAccount"
            :title="t('settings.xhsAccounts.syncNowHint')"
            @click="syncNow"
          >
            <AppIcon name="Zap" size="xs" variant="white" />
            <span class="ml-1">{{ t('settings.xhsAccounts.syncNow') }}</span>
          </NeonButton>
        </div>
        <form @submit.prevent="createAccount" class="flex items-center gap-2">
          <input
            v-model="newAccountName"
            type="text"
            :placeholder="t('settings.accountNamePlaceholder')"
            class="dark-explicit px-3 py-1.5 text-sm rounded-lg border border-slate-200 bg-white focus:border-rose-400 focus:ring-2 focus:ring-rose-400/20 outline-none w-40 dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
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
        class="dark-explicit rounded-lg border p-3 flex items-center gap-3 transition-all cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-rose-400/60"
        :class="editingAccountId === account.id
          ? 'border-rose-200 bg-rose-50/50 shadow-sm dark:border-rose-400/40 dark:bg-rose-900/50'
          : 'border-slate-100 hover:border-slate-200 hover:bg-slate-50/50 dark:border-slate-700 dark:hover:border-slate-600 dark:hover:bg-slate-800/50'"
        role="button"
        tabindex="0"
        @click="editingAccountId = account.id"
        @keydown.enter="editingAccountId = account.id"
        @keydown.space.prevent="editingAccountId = account.id"
      >
        <div class="w-2 h-2 rounded-full shrink-0" :class="account.is_active ? 'bg-emerald-500' : 'bg-slate-300'" />
        <div class="flex-1 min-w-0">
          <div class="text-sm font-medium truncate" :class="account.is_active ? 'text-slate-800' : 'text-slate-500'">
            {{ account.name }}
          </div>
          <div class="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5">
            <div class="flex items-center gap-1 text-[11px]" :class="loginStatusClass(account.id)">
              <AppIcon
                :name="loginStatusIcon(account.id)"
                size="xs"
                :variant="loginStatusFor(account.id).status === 'logged_in' ? 'cyan' : 'pink'"
                :animate="loginStatusFor(account.id).status === 'checking'"
              />
              <span>{{ loginStatusText(account.id) }}</span>
            </div>
            <span
              v-if="account.niche"
              class="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-600 font-medium"
              :title="account.niche_source || ''"
            >
              {{ account.niche }}
            </span>
            <span
              v-else
              class="text-[10px] text-slate-400"
            >
              {{ t('creatorStats.nicheUnbound') }}
            </span>
            <span
              v-if="qrRiskFor(account.id)"
              class="text-[10px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 font-medium"
              :title="qrRiskFor(account.id)?.message"
            >
              {{ t('settings.xhsAccounts.qrRiskBadge', {
                minutes: Math.max(1, Math.ceil((qrRiskFor(account.id)?.remainingSeconds || 60) / 60)),
              }) }}
            </span>
          </div>
        </div>
        <span v-if="account.is_active"
          class="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-600 font-medium"
        >
          {{ t('settings.active') }}
        </span>
        <div class="flex items-center gap-1" @click.stop>
          <button type="button" @click="openQrLogin(account)"
            class="min-h-11 px-2 py-1 rounded transition-colors flex items-center gap-1"
            :class="canOpenQrLogin(account)
              ? 'text-rose-500 hover:text-rose-600 hover:bg-rose-50'
              : 'text-slate-300 cursor-not-allowed'"
            :disabled="!canOpenQrLogin(account)"
            :title="qrRiskFor(account.id)
              ? t('settings.xhsAccounts.qrRiskCooldown', {
                  minutes: Math.max(1, Math.ceil((qrRiskFor(account.id)?.remainingSeconds || 60) / 60)),
                })
              : canScanLogin(account)
                ? t('settings.xhsAccounts.qrLogin')
                : account.is_active
                  ? t('settings.xhsAccounts.loginStatusUnavailable')
                  : t('settings.xhsAccounts.loginStatusInactive')"
          >
            <AppIcon name="LogIn" size="xs" variant="pink" />
            <span>{{ t('settings.xhsAccounts.qrLogin') }}</span>
          </button>
          <button type="button" v-if="!account.is_active" @click="activateAccount(account.id)"
            class="min-h-11 text-xs text-teal-600 hover:text-teal-700 px-2 py-1 rounded hover:bg-teal-50 transition-colors"
          >
            {{ t('settings.activate') }}
          </button>
          <button type="button" @click="requestRemoveAccount(account.id, account.name)"
            class="min-h-11 min-w-11 text-xs text-rose-400 hover:text-rose-500 px-1 py-1 rounded hover:bg-rose-50 transition-colors"
            :aria-label="t('settings.delete')"
          >
            <AppIcon name="Trash2" size="xs" variant="pink" />
          </button>
        </div>
      </div>
    </div>

    <!-- Selected account: import stats + niche bind -->
    <CreatorStatsPanel
      v-if="editingAccountId"
      :key="`${editingAccountId}-${statsPanelKey}`"
      :account-id="editingAccountId"
      :account-name="store.accounts.find(a => a.id === editingAccountId)?.name"
      @updated="store.fetchAccounts()"
    />

    <!-- Scan-login (QR) modal -->
    <QrLoginModal
      v-if="qrLoginOpen && qrLoginAccount"
      :account-id="qrLoginAccountId"
      :account-name="qrLoginAccountName"
      :is-open="qrLoginOpen"
      @close="closeQrLogin"
      @confirmed="onQrConfirmed"
      @risk-block="onQrRiskBlock"
    />

    <ConfirmModal
      :is-open="showDeleteModal"
      :title="t('settings.delete')"
      :message="deleteTarget ? t('settings.confirm.delete', { name: deleteTarget.name }) : ''"
      variant="danger"
      @confirm="confirmRemoveAccount"
      @cancel="showDeleteModal = false; deleteTarget = null"
    />
  </div>
</template>
