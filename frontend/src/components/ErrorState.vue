<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore, useToastStore } from '@/stores'
import type { ErrorType } from '@/types/error'

const { t, tm } = useI18n()

// Optional props enable presentational (store-free) mode for non-Dashboard callers.
// When `variant` is set, the component renders from props and emits retry/dismiss
// events instead of binding to the workflow store. When omitted, the legacy
// store-bound behavior used by Dashboard is preserved verbatim.
const props = defineProps<{
  variant?: ErrorType
  title?: string
  message?: string
  retryLabel?: string
  retryCount?: number
  dismissLabel?: string
  retrying?: boolean
  hideDismiss?: boolean
}>()

const emit = defineEmits<{
  retry: []
  dismiss: []
}>()

const isPresentational = computed(() => Boolean(props.variant))

// Class maps mirror ErrorCard.vue so presentational render matches the existing
// error surfaces across the app.
const ERROR_BG_CLASSES: Record<ErrorType, string> = {
  api: 'bg-rose-50/80 border-rose-200/50 dark:bg-rose-950/40 dark:border-rose-500/30 dark-explicit',
  timeout: 'bg-amber-50/80 border-amber-200/50 dark:bg-amber-950/40 dark:border-amber-500/30 dark-explicit',
  unknown: 'bg-violet-50/80 border-violet-200/50 dark:bg-violet-950/40 dark:border-violet-500/30 dark-explicit',
  retry_success: 'bg-green-50/80 border-green-200/50 dark:bg-emerald-950/40 dark:border-emerald-500/30 dark-explicit',
}
const ERROR_ICON_BG_CLASSES: Record<ErrorType, string> = {
  api: 'bg-rose-100 dark:bg-rose-900/50 dark-explicit',
  timeout: 'bg-amber-100 dark:bg-amber-900/50 dark-explicit',
  unknown: 'bg-violet-100 dark:bg-violet-900/50 dark-explicit',
  retry_success: 'bg-green-100 dark:bg-emerald-900/50 dark-explicit',
}
const ERROR_TITLE_CLASSES: Record<ErrorType, string> = {
  api: 'text-rose-700 dark:text-rose-300 dark-explicit',
  timeout: 'text-amber-700 dark:text-amber-300 dark-explicit',
  unknown: 'text-violet-700 dark:text-violet-300 dark-explicit',
  retry_success: 'text-green-700 dark:text-emerald-300 dark-explicit',
}
const ERROR_MESSAGE_CLASSES: Record<ErrorType, string> = {
  api: 'text-rose-600 dark:text-rose-300 dark-explicit',
  timeout: 'text-amber-600 dark:text-amber-300 dark-explicit',
  unknown: 'text-violet-600 dark:text-violet-300 dark-explicit',
  retry_success: 'text-green-600 dark:text-emerald-300 dark-explicit',
}
const ERROR_ICON_NAME: Record<ErrorType, string> = {
  api: 'AlertCircle',
  timeout: 'Clock',
  unknown: 'HelpCircle',
  retry_success: 'CheckCircle',
}
const ERROR_ICON_VARIANT: Record<ErrorType, 'pink' | 'peach' | 'purple' | 'cyan'> = {
  api: 'pink',
  timeout: 'peach',
  unknown: 'purple',
  retry_success: 'cyan',
}

// Presentational derived values
const presentationalTitle = computed(() => {
  if (props.title) return props.title
  switch (props.variant) {
    case 'api':
      return t('common.apiError')
    case 'timeout':
      return t('common.timeoutError')
    case 'unknown':
      return t('common.unknownError')
    case 'retry_success':
      return t('common.retrySuccess')
    default:
      return t('common.error')
  }
})
const presentationalMessage = computed(() => props.message || '')
const showRetryButton = computed(() => props.variant !== 'retry_success')
const presentationalRetryButtonText = computed(() => {
  if (props.retryLabel) return props.retryLabel
  if (props.retryCount && props.retryCount > 0) {
    return t('common.retryCount', { count: props.retryCount })
  }
  return t('common.retry')
})

// --- Legacy store-bound mode (Dashboard zero-change) ---
// ponytail: presentational mode (public pages) must not instantiate business
// stores — docs red line "公开页不引入业务 store". Legacy Dashboard mounts are
// the only callers of the branch below, and they never set `variant`.
const workflowStore = isPresentational.value ? null : useWorkflowStore()
const toastStore = isPresentational.value ? null : useToastStore()

const hasError = computed(() => Boolean(workflowStore?.error))
const currentPhase = computed(() => workflowStore?.currentPhase)

// Detect error type and provide recovery suggestions
const errorType = computed(() => {
  const error = workflowStore?.error || ''
  if (error.includes('network') || error.includes('Network') || error.includes('连接') || error.includes('timeout')) {
    return 'network'
  }
  if (error.includes('validation') || error.includes('Validation') || error.includes('参数') || error.includes('invalid')) {
    return 'validation'
  }
  if (error.includes('not found') || error.includes('404') || error.includes('不存在')) {
    return 'not_found'
  }
  if (error.includes('unauthorized') || error.includes('401') || error.includes('认证')) {
    return 'auth'
  }
  return 'general'
})

const recoverySuggestions = computed(() => {
  const key = {
    network: 'errorState.networkSuggestions',
    validation: 'errorState.validationSuggestions',
    not_found: 'errorState.notFoundSuggestions',
    auth: 'errorState.authSuggestions',
    general: 'errorState.generalSuggestions',
  }[errorType.value] || 'errorState.generalSuggestions'
  // Suggestions are locale arrays; `tm` avoids treating an array as a string
  // translation and prevents false "missing key" warnings from vue-i18n.
  return tm(key) as string[]
})

const retryAction = async () => {
  if (!workflowStore || !toastStore) return
  if (workflowStore.currentStatus === 'error' && workflowStore.currentThreadId) {
    await workflowStore.resumeWorkflow()
  } else {
    await workflowStore.refreshStatus()
  }
  toastStore.info(t('errorState.retrying'), t('errorState.retryingMessage'))
}

const goBackAction = () => {
  if (!workflowStore || !toastStore) return
  if (workflowStore.activeThreadId) {
    workflowStore.closeTab(workflowStore.activeThreadId)
  }
  workflowStore.error = null
  toastStore.info(t('errorState.returned'), t('errorState.returnedMessage'))
}

// Render gate: presentational renders whenever variant is set; legacy renders
// only when the store reports an error.
const shouldRender = computed(() => (isPresentational.value ? true : hasError.value))
</script>

<template>
  <div v-if="shouldRender" class="rounded-2xl p-6 border" :class="isPresentational ? ERROR_BG_CLASSES[props.variant!] : 'bg-red-50/80 border-red-200/50'">
    <div class="flex items-start gap-4">
      <!-- Error icon -->
      <div class="w-12 h-12 rounded-xl flex items-center justify-center" :class="isPresentational ? ERROR_ICON_BG_CLASSES[props.variant!] : 'bg-red-100'">
        <AppIcon :name="isPresentational ? ERROR_ICON_NAME[props.variant!] : 'AlertCircle'" size="lg" :variant="isPresentational ? ERROR_ICON_VARIANT[props.variant!] : 'pink'" />
      </div>

      <!-- Error content -->
      <div class="flex-1">
        <h3 class="text-lg font-semibold mb-1" :class="isPresentational ? ERROR_TITLE_CLASSES[props.variant!] : 'text-red-700'">{{ isPresentational ? presentationalTitle : t('errorState.workflowError') }}</h3>
        <p class="text-sm mb-2" :class="isPresentational ? ERROR_MESSAGE_CLASSES[props.variant!] : 'text-red-600'">{{ isPresentational ? presentationalMessage : workflowStore?.error }}</p>
        <p v-if="isPresentational && props.retryCount && props.retryCount > 0" class="text-xs opacity-70" :class="ERROR_MESSAGE_CLASSES[props.variant!]">
          {{ t('common.retriedTimes', { count: props.retryCount }) }}
        </p>
        <p v-if="!isPresentational" class="text-red-500/70 text-xs mb-3">{{ t('errorState.currentPhase', { phase: currentPhase }) }}</p>

        <!-- Recovery suggestions (legacy mode only) -->
        <div v-if="!isPresentational" class="mt-3 p-3 rounded-lg bg-white/80 border border-red-100 dark:bg-slate-900/85 dark:border-slate-700/50 dark-explicit">
          <p class="text-xs text-red-600 font-medium mb-2">{{ t('errorState.suggestions') }}</p>
          <ul class="space-y-1">
            <li v-for="suggestion in recoverySuggestions" :key="suggestion" class="flex items-center gap-2 text-xs text-red-500">
              <AppIcon name="ChevronRight" size="sm" variant="pink" aria-hidden="true" />
              {{ suggestion }}
            </li>
          </ul>
        </div>
      </div>

      <!-- Actions -->
      <div class="flex flex-col gap-2">
        <NeonButton v-if="isPresentational ? showRetryButton : true" variant="pink" size="sm" :loading="isPresentational ? props.retrying : Boolean(workflowStore?.isLoading)" @click="isPresentational ? emit('retry') : retryAction()">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="RefreshCw" size="sm" variant="white" />
            <span>{{ isPresentational ? presentationalRetryButtonText : t('errorState.retry') }}</span>
          </span>
        </NeonButton>
        <NeonButton v-if="!(isPresentational && props.hideDismiss)" variant="ghost" size="sm" :class="isPresentational ? ERROR_MESSAGE_CLASSES[props.variant!] : 'text-red-500 hover:bg-red-50'" @click="isPresentational ? emit('dismiss') : goBackAction()">
          <span class="inline-flex items-center gap-2">
            <AppIcon :name="isPresentational ? 'X' : 'Home'" size="sm" :variant="isPresentational ? ERROR_ICON_VARIANT[props.variant!] : 'pink'" />
            <span>{{ isPresentational ? (props.dismissLabel || t('common.close')) : t('errorState.back') }}</span>
          </span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>
