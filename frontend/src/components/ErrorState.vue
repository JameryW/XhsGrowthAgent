<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore, useToastStore } from '@/stores'

const workflowStore = useWorkflowStore()
const toastStore = useToastStore()

const hasError = computed(() => workflowStore.error !== null)
const currentPhase = computed(() => workflowStore.currentPhase)

const retryAction = () => {
  workflowStore.refreshStatus()
  toastStore.info('正在重试...', '重新获取工作流状态')
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
        <h3 class="text-lg font-semibold text-red-700 mb-1">工作流错误</h3>
        <p class="text-red-600 text-sm mb-2">{{ workflowStore.error }}</p>
        <p class="text-red-500/70 text-xs">当前阶段: {{ currentPhase }}</p>
      </div>

      <!-- Retry button -->
      <NeonButton variant="pink" size="sm" @click="retryAction" :loading="workflowStore.isLoading">
        <span class="inline-flex items-center gap-2">
          <AppIcon name="RefreshCw" size="sm" variant="white" />
          <span>重试</span>
        </span>
      </NeonButton>
    </div>
  </div>
</template>