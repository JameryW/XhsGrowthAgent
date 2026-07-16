<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore, useToastStore } from '@/stores'

const { t } = useI18n()

const workflowStore = useWorkflowStore()
const toastStore = useToastStore()

const hasError = computed(() => workflowStore.error !== null)
const currentPhase = computed(() => workflowStore.currentPhase)

// Detect error type and provide recovery suggestions
const errorType = computed(() => {
  const error = workflowStore.error || ''
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
  return t(key) as unknown as string[]
})

const retryAction = async () => {
  if (workflowStore.currentStatus === 'error' && workflowStore.currentThreadId) {
    await workflowStore.resumeWorkflow()
  } else {
    await workflowStore.refreshStatus()
  }
  toastStore.info(t('errorState.retrying'), t('errorState.retryingMessage'))
}

const goBackAction = () => {
  if (workflowStore.activeThreadId) {
    workflowStore.closeTab(workflowStore.activeThreadId)
  }
  workflowStore.error = null
  toastStore.info(t('errorState.returned'), t('errorState.returnedMessage'))
}
</script>

<template>
  <div v-if="hasError" class="rounded-2xl p-6 bg-red-50/80 border border-red-200/50">
    <div class="flex items-start gap-4">
      <!-- Error icon -->
      <div class="w-12 h-12 rounded-xl bg-red-100 flex items-center justify-center">
        <AppIcon name="AlertCircle" size="lg" variant="pink" />
      </div>

      <!-- Error content -->
      <div class="flex-1">
        <h3 class="text-lg font-semibold text-red-700 mb-1">{{ t('errorState.workflowError') }}</h3>
        <p class="text-red-600 text-sm mb-2">{{ workflowStore.error }}</p>
        <p class="text-red-500/70 text-xs mb-3">{{ t('errorState.currentPhase', { phase: currentPhase }) }}</p>

        <!-- Recovery suggestions -->
        <div class="mt-3 p-3 rounded-lg bg-white/80 border border-red-100 dark:bg-slate-900/85 dark:border-slate-700/50">
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
        <NeonButton variant="pink" size="sm" @click="retryAction" :loading="workflowStore.isLoading">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="RefreshCw" size="sm" variant="white" />
            <span>{{ t('errorState.retry') }}</span>
          </span>
        </NeonButton>
        <NeonButton variant="ghost" size="sm" class="text-red-500 hover:bg-red-50" @click="goBackAction">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="Home" size="sm" variant="pink" />
            <span>{{ t('errorState.back') }}</span>
          </span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>
