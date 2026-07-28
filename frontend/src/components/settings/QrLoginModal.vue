<script setup lang="ts">
import { ref, watch, onUnmounted, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import QRCode from 'qrcode'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import {
  startQrLogin,
  getQrLoginStatus,
  submitQrVerificationCode,
  stopQrLogin,
  type QrLoginStatus,
} from '@/api/accounts'
import { ApiError } from '@/api/client'
interface Props {
  accountId: string
  accountName: string
  isOpen: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'confirmed'): void
  (e: 'risk-block', payload: { riskCode: string; retryAfterSeconds: number; message: string }): void
}>()

const { t } = useI18n()

// ── State ──
const qrImgSrc = ref<string>('')
const status = ref<QrLoginStatus | null>(null)
const errorMsg = ref<string>('')
const isStarting = ref(false)
const verificationCode = ref('')
const verificationRequired = ref(false)
const isSubmittingVerificationCode = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null
// Guard: once set, in-flight async callbacks (pollOnce / startSession) treat
// the component as dead and skip all state writes + emits. Prevents races
// where a poll resolves after the modal closes, which would otherwise emit
// 'confirmed' on a torn-down component or write to refs the parent no longer
// renders.
let disposed = false

const POLL_INTERVAL_MS = 2000
const MAX_POLL_DURATION_MS = 4 * 60 * 1000 // 4 min overall guard (matches backend 240s)
let pollStartTs = 0

// ── Computed display ──
const statusText = computed(() => {
  switch (status.value) {
    case 'waiting': return t('settings.xhsAccounts.qrWaiting')
    case 'scanned':
      return verificationRequired.value
        ? t('settings.xhsAccounts.qrVerificationRequired')
        : t('settings.xhsAccounts.qrScanned')
    case 'confirmed': return t('settings.xhsAccounts.qrConfirmed')
    case 'expired': return t('settings.xhsAccounts.qrExpired')
    default: return t('settings.xhsAccounts.qrWaiting')
  }
})

const statusIconName = computed(() => {
  switch (status.value) {
    case 'scanned': return 'Smartphone'
    case 'confirmed': return 'CheckCircle'
    case 'expired': return 'RefreshCw'
    default: return 'Scan'
  }
})

const statusIconVariant = computed(() => {
  switch (status.value) {
    case 'scanned': return 'cyan' as const
    case 'confirmed': return 'cyan' as const
    case 'expired': return 'peach' as const
    default: return 'pink' as const
  }
})

const showQrImage = computed(() => status.value === 'waiting' || status.value === 'expired' || status.value === null)
const showSpinner = computed(() => isStarting.value && !qrImgSrc.value)
const showVerificationCodeInput = computed(() => Boolean(status.value && status.value !== 'confirmed'))

// ── QR rendering ──
async function renderQr(url: string) {
  if (url.startsWith('data:image/')) {
    qrImgSrc.value = url
    return
  }
  try {
    qrImgSrc.value = await QRCode.toDataURL(url, {
      width: 240,
      margin: 1,
      color: { dark: '#1e293b', light: '#ffffff' },
    })
  } catch {
    // toDataURL failure is unexpected; surface as expired-style error
    qrImgSrc.value = ''
    errorMsg.value = t('settings.xhsAccounts.qrRenderError')
  }
}

// ── Session lifecycle ──
async function startSession() {
  isStarting.value = true
  errorMsg.value = ''
  qrImgSrc.value = ''
  status.value = null
  verificationRequired.value = false
  try {
    const res = await startQrLogin(props.accountId)
    if (disposed) return
    if (res.status === 'confirmed') {
      status.value = 'confirmed'
      verificationRequired.value = false
      qrImgSrc.value = ''
      stopPolling()
      emit('confirmed')
      // No stopQrLogin here: after confirmed the backend detaches itself and
      // keeps the logged-in tab open in the host Chrome (parked on creator
      // home). Calling stop would close that tab and undo the navigation.
      return
    }
    if (!res.url) {
      throw new Error(t('settings.xhsAccounts.qrStartError'))
    }
    await renderQr(res.url)
    if (disposed) return
    status.value = 'waiting'
    verificationRequired.value = false
    pollStartTs = Date.now()
    startPolling()
  } catch (e: any) {
    if (disposed) return
    errorMsg.value = e?.message || t('settings.xhsAccounts.qrStartError')
    status.value = null
    if (e instanceof ApiError) {
      const details = e.details || {}
      const riskCode = String(details.risk_code || '')
      const retryAfter = Number(details.retry_after_seconds || 0)
      if (
        riskCode === '300012'
        || riskCode === 'security_risk'
        || riskCode === 'qr_cooldown'
        || riskCode === 'qr_timeout'
        || e.code === 'ERROR_RATE_LIMIT'
        || /300012|安全限制|冷却|IP/i.test(e.message || '')
      ) {
        emit('risk-block', {
          riskCode: riskCode || 'security_risk',
          retryAfterSeconds: retryAfter > 0 ? retryAfter : 900,
          message: e.message,
        })
      }
    }
  } finally {
    if (!disposed) isStarting.value = false
  }
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(pollOnce, POLL_INTERVAL_MS)
}

function stopPolling() {
  if (pollTimer !== null) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function pollOnce() {
  if (disposed) return
  // Overall timeout guard — stop polling after MAX_POLL_DURATION_MS
  if (pollStartTs && Date.now() - pollStartTs > MAX_POLL_DURATION_MS) {
    stopPolling()
    status.value = 'expired'
    errorMsg.value = t('settings.xhsAccounts.qrTimeout')
    return
  }
  try {
    const res = await getQrLoginStatus(props.accountId)
    if (disposed) return
    // Successful response — clear transient error from a previous failed poll.
    errorMsg.value = ''
    // expired → backend already refreshed, render new url then transition
    // back to waiting so the UI doesn't linger on the "expired" styling.
    if (res.status === 'expired' && res.url) {
      await renderQr(res.url)
      if (disposed) return
      status.value = 'waiting'
      verificationRequired.value = false
      // The backend refreshed the QR; reset the overall timeout window so
      // the user gets a fresh full poll budget on the new QR.
      pollStartTs = Date.now()
    } else {
      status.value = res.status
      verificationRequired.value = Boolean(res.verification_required)
      if (res.status === 'confirmed') {
        verificationRequired.value = false
        stopPolling()
        emit('confirmed')
        // No stopQrLogin: backend keeps the logged-in tab open in host Chrome
        // (see startSession confirmed branch) and self-detaches the session.
      }
    }
  } catch (e: any) {
    if (disposed) return
    // Transient poll error — keep polling, but surface after repeated failures
    // to avoid silently stuck UI. Single failure is tolerated (network blip).
    errorMsg.value = e?.message || t('settings.xhsAccounts.qrPollError')
  }
}

async function submitVerificationCode() {
  if (disposed) return
  const code = verificationCode.value.trim()
  if (!/^\d{4,8}$/.test(code)) {
    errorMsg.value = t('settings.xhsAccounts.verificationCodeInvalid')
    return
  }
  isSubmittingVerificationCode.value = true
  errorMsg.value = ''
  try {
    const res = await submitQrVerificationCode(props.accountId, code)
    if (disposed) return
    verificationCode.value = ''
    if (!res.submitted) {
      errorMsg.value = t('settings.xhsAccounts.verificationCodeNotFound')
      status.value = res.status
      verificationRequired.value = Boolean(res.verification_required)
      return
    }
    status.value = res.status
    verificationRequired.value = Boolean(res.verification_required)
    if (res.status === 'confirmed') {
      verificationRequired.value = false
      stopPolling()
      emit('confirmed')
      // No stopQrLogin: keep the logged-in tab open in host Chrome.
    } else {
      await pollOnce()
    }
  } catch (e: any) {
    if (disposed) return
    errorMsg.value = e?.message || t('settings.xhsAccounts.verificationCodeSubmitError')
  } finally {
    if (!disposed) isSubmittingVerificationCode.value = false
  }
}

// ── Close / cleanup ──
function handleClose() {
  cleanup()
  emit('close')
}

async function cleanup() {
  // Mark disposed first so any in-flight pollOnce/startSession callback
  // skips its state writes + emits after the next await resumes.
  disposed = true
  stopPolling()
  // If not confirmed, tell backend to release the headless Chrome session.
  if (status.value !== 'confirmed') {
    await stopQrLogin(props.accountId).catch(() => {})
  }
  qrImgSrc.value = ''
  status.value = null
  errorMsg.value = ''
  verificationCode.value = ''
  verificationRequired.value = false
}

// Reset/refresh QR on manual retry
async function refreshQr() {
  await startSession()
}

// ── React to isOpen ──
// immediate: true is required because the parent mounts this component with
// v-if="qrLoginOpen" — so on first mount isOpen is already true and a plain
// watch wouldn't fire, leaving the QR never generated.
watch(() => props.isOpen, async (open) => {
  if (open) {
    // Reset the disposed guard for a fresh open (a prior close set it).
    disposed = false
    await startSession()
  } else {
    await cleanup()
  }
}, { immediate: true })

onUnmounted(() => {
  cleanup()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-50 flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="qr-modal-title"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-slate-900/50 backdrop-blur-sm"
          @click="handleClose"
          aria-hidden="true"
        />

        <!-- Modal -->
        <div class="relative w-full max-w-md p-6 rounded-2xl liquid-glass-elevated">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <div class="flex items-center gap-3">
              <div class="w-10 h-10 rounded-xl flex items-center justify-center bg-rose-100">
                <AppIcon name="LogIn" size="md" variant="pink" />
              </div>
              <div>
                <h2 id="qr-modal-title" class="text-lg font-semibold text-slate-800">
                  {{ t('settings.xhsAccounts.qrLoginTitle') }}
                </h2>
                <p class="text-xs text-slate-400">{{ accountName }}</p>
              </div>
            </div>
            <button
              type="button"
              class="min-h-11 min-w-11 p-1.5 rounded-lg hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors dark:hover:bg-slate-800 dark:hover:text-slate-200"
              :aria-label="t('common.cancel')"
              @click="handleClose"
            >
              <AppIcon name="X" size="sm" variant="pink" />
            </button>
          </div>

          <!-- QR display area -->
          <div class="flex flex-col items-center justify-center py-4">
            <!-- Loading spinner while starting -->
            <div v-if="showSpinner" class="flex flex-col items-center gap-3 py-8">
              <AppIcon name="Loader2" size="lg" variant="cyan" animate />
              <p class="text-sm text-slate-500">{{ t('settings.xhsAccounts.qrStarting') }}</p>
            </div>

            <!-- QR image -->
            <template v-else-if="showQrImage">
              <div class="p-3 bg-white rounded-xl shadow-sm border border-slate-100 dark:bg-slate-900 dark:border-slate-700">
                <img v-if="qrImgSrc" :src="qrImgSrc" alt="QR Code" class="w-60 h-60" />
                <div v-else class="w-60 h-60 flex items-center justify-center text-slate-300">
                  <AppIcon name="Scan" size="xl" variant="pink" />
                </div>
              </div>
              <p class="mt-3 text-sm text-slate-500 text-center max-w-xs">
                {{ t('settings.xhsAccounts.qrScanTip') }}
              </p>
            </template>

            <!-- Scanned (waiting for phone confirm) -->
            <div v-else-if="status === 'scanned'" class="flex flex-col items-center gap-3 py-8">
              <div class="w-16 h-16 rounded-full bg-cyan-100 flex items-center justify-center">
                <AppIcon name="Smartphone" size="xl" variant="cyan" />
              </div>
              <p class="text-sm text-cyan-700 font-medium text-center">{{ statusText }}</p>
            </div>

            <!-- Confirmed -->
            <div v-else-if="status === 'confirmed'" class="flex flex-col items-center gap-3 py-8">
              <div class="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center">
                <AppIcon name="CheckCircle" size="xl" variant="cyan" />
              </div>
              <p class="text-sm text-emerald-700 font-medium">{{ statusText }}</p>
            </div>
          </div>

          <!-- Status line -->
          <div v-if="status && status !== 'confirmed'" class="flex items-center justify-center gap-2 mb-3">
            <AppIcon :name="statusIconName" size="sm" :variant="statusIconVariant" />
            <span class="text-sm text-slate-600">{{ statusText }}</span>
          </div>

          <!-- Numeric verification code forwarding -->
          <div
            v-if="showVerificationCodeInput"
            class="mb-3 p-3 rounded-lg border"
            :class="verificationRequired
              ? 'bg-cyan-50/80 border-cyan-100'
              : 'bg-slate-50/80 border-slate-100 dark:bg-slate-800/70 dark:border-slate-700/50'"
          >
            <label class="block text-xs font-medium text-slate-500 mb-2">
              {{ verificationRequired
                ? t('settings.xhsAccounts.verificationCodeRequiredLabel')
                : t('settings.xhsAccounts.verificationCodeLabel') }}
            </label>
            <div class="flex items-center gap-2">
              <input
                v-model="verificationCode"
                type="text"
                inputmode="numeric"
                autocomplete="one-time-code"
                maxlength="8"
                :placeholder="t('settings.xhsAccounts.verificationCodePlaceholder')"
                class="flex-1 min-w-0 px-3 py-2 text-sm rounded-lg border border-slate-200 bg-white focus:border-cyan-400 focus:ring-2 focus:ring-cyan-400/20 outline-none dark:border-slate-600 dark:bg-slate-900 dark:text-slate-200"
                @keydown.enter.prevent="submitVerificationCode"
              />
              <NeonButton
                variant="cyan"
                size="sm"
                :loading="isSubmittingVerificationCode"
                :disabled="!verificationCode.trim()"
                @click="submitVerificationCode"
              >
                <AppIcon name="Check" size="xs" variant="white" />
                <span class="ml-1">{{ t('settings.xhsAccounts.verificationCodeSubmit') }}</span>
              </NeonButton>
            </div>
            <p class="mt-2 text-[11px] leading-relaxed text-slate-400">
              {{ verificationRequired
                ? t('settings.xhsAccounts.verificationCodeRequiredHint')
                : t('settings.xhsAccounts.verificationCodeHint') }}
            </p>
          </div>

          <!-- Error -->
          <div v-if="errorMsg" class="mb-3 p-3 rounded-lg bg-rose-50 border border-rose-100">
            <p class="text-sm text-rose-600">{{ errorMsg }}</p>
          </div>

          <!-- Footer actions -->
          <div class="flex gap-3 justify-end">
            <NeonButton
              v-if="status === 'expired' || errorMsg"
              variant="cyan"
              size="sm"
              :loading="isStarting"
              @click="refreshQr"
            >
              <AppIcon name="RefreshCw" size="xs" variant="white" />
              <span class="ml-1">{{ t('settings.xhsAccounts.qrRefresh') }}</span>
            </NeonButton>
            <NeonButton variant="ghost" size="sm" @click="handleClose">
              {{ t('common.cancel') }}
            </NeonButton>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-enter-active {
  transition: all 0.3s ease-out;
}

.modal-leave-active {
  transition: all 0.2s ease-in;
}

.modal-enter-from {
  opacity: 0;
}

.modal-leave-to {
  opacity: 0;
}

.modal-enter-from > div:last-child {
  transform: scale(0.95) translateY(10px);
}

.modal-leave-to > div:last-child {
  transform: scale(0.95) translateY(-10px);
}
</style>
