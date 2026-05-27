<script setup lang="ts">
import { computed } from 'vue'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'
import { useWorkflowStore, useToastStore } from '@/stores'

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
  switch (errorType.value) {
    case 'network':
      return [
        '检查网络连接是否正常',
        '尝试刷新页面',
        '等待片刻后重试',
      ]
    case 'validation':
      return [
        '检查输入参数是否正确',
        '确认账号ID有效',
        '查看API文档了解参数要求',
      ]
    case 'not_found':
      return [
        '确认工作流ID存在',
        '检查是否已删除的工作流',
        '返回仪表盘重新开始',
      ]
    case 'auth':
      return [
        '检查登录状态',
        '重新登录系统',
        '联系管理员获取权限',
      ]
    default:
      return [
        '点击重试按钮重新尝试',
        '返回仪表盘查看状态',
        '联系技术支持获取帮助',
      ]
  }
})

const retryAction = () => {
  workflowStore.refreshStatus()
  toastStore.info('正在重试...', '重新获取工作流状态')
}

const goBackAction = () => {
  workflowStore.setThreadId('')
  workflowStore.workflowState = null
  workflowStore.error = null
  toastStore.info('已返回', '请重新开始工作流')
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
        <p class="text-red-500/70 text-xs mb-3">当前阶段: {{ currentPhase }}</p>

        <!-- Recovery suggestions -->
        <div class="mt-3 p-3 rounded-lg bg-white/80 border border-red-100">
          <p class="text-xs text-red-600 font-medium mb-2">建议解决方案:</p>
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
            <span>重试</span>
          </span>
        </NeonButton>
        <NeonButton variant="ghost" size="sm" class="text-red-500 hover:bg-red-50" @click="goBackAction">
          <span class="inline-flex items-center gap-2">
            <AppIcon name="Home" size="sm" variant="pink" />
            <span>返回</span>
          </span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>