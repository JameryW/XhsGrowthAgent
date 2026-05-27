<script setup lang="ts">
import { computed } from 'vue'
import type { ErrorType } from '@/types/error'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

/**
 * Color mapping for error types
 */
const ERROR_COLORS: Record<ErrorType, string> = {
  api: '#f43f5e',        // rose-500
  timeout: '#f59e0b',    // amber-500
  unknown: '#8b5cf6',    // violet-500
  retry_success: '#22c55e' // green-500
}

/**
 * Tailwind class mapping for error types
 */
const ERROR_BG_CLASSES: Record<ErrorType, string> = {
  api: 'bg-rose-50/80 border-rose-200/50',
  timeout: 'bg-amber-50/80 border-amber-200/50',
  unknown: 'bg-violet-50/80 border-violet-200/50',
  retry_success: 'bg-green-50/80 border-green-200/50'
}

const ERROR_ICON_BG_CLASSES: Record<ErrorType, string> = {
  api: 'bg-rose-100',
  timeout: 'bg-amber-100',
  unknown: 'bg-violet-100',
  retry_success: 'bg-green-100'
}

const ERROR_TEXT_CLASSES: Record<ErrorType, { title: string; message: string }> = {
  api: { title: 'text-rose-700', message: 'text-rose-600' },
  timeout: { title: 'text-amber-700', message: 'text-amber-600' },
  unknown: { title: 'text-violet-700', message: 'text-violet-600' },
  retry_success: { title: 'text-green-700', message: 'text-green-600' }
}

// Props
const props = defineProps<{
  type: ErrorType
  message: string
  retryCount?: number
}>()

// Emits
const emit = defineEmits<{
  retry: []
  dismiss: []
}>()

// Computed
const bgColor = computed(() => ERROR_COLORS[props.type])
const bgClasses = computed(() => ERROR_BG_CLASSES[props.type])
const iconBgClasses = computed(() => ERROR_ICON_BG_CLASSES[props.type])
const textClasses = computed(() => ERROR_TEXT_CLASSES[props.type])
const iconName = computed(() => {
  switch (props.type) {
    case 'api':
      return 'AlertCircle'
    case 'timeout':
      return 'Clock'
    case 'unknown':
      return 'HelpCircle'
    case 'retry_success':
      return 'CheckCircle'
    default:
      return 'AlertCircle'
  }
})
const iconVariant = computed(() => {
  switch (props.type) {
    case 'api':
      return 'pink'
    case 'timeout':
      return 'yellow'
    case 'unknown':
      return 'purple'
    case 'retry_success':
      return 'green'
    default:
      return 'pink'
  }
})
const title = computed(() => {
  switch (props.type) {
    case 'api':
      return 'API错误'
    case 'timeout':
      return '请求超时'
    case 'unknown':
      return '未知错误'
    case 'retry_success':
      return '重试成功'
    default:
      return '错误'
  }
})
const showRetryButton = computed(() => props.type !== 'retry_success')
const retryButtonText = computed(() => {
  if (props.retryCount && props.retryCount > 0) {
    return `重试 (${props.retryCount})`
  }
  return '重试'
})
</script>

<template>
  <div class="rounded-2xl p-6 border" :class="bgClasses">
    <div class="flex items-start gap-4">
      <!-- Error icon -->
      <div class="w-12 h-12 rounded-xl flex items-center justify-center" :class="iconBgClasses">
        <AppIcon :name="iconName" size="lg" :variant="iconVariant" />
      </div>

      <!-- Error content -->
      <div class="flex-1">
        <h3 class="text-lg font-semibold mb-1" :class="textClasses.title">
          {{ title }}
        </h3>
        <p class="text-sm mb-2" :class="textClasses.message">
          {{ message }}
        </p>
        <p v-if="retryCount && retryCount > 0" class="text-xs opacity-70" :class="textClasses.message">
          已重试 {{ retryCount }} 次
        </p>
      </div>

      <!-- Actions -->
      <div class="flex flex-col gap-2">
        <NeonButton
          v-if="showRetryButton"
          variant="pink"
          size="sm"
          @click="emit('retry')"
        >
          <span class="inline-flex items-center gap-2">
            <AppIcon name="RefreshCw" size="sm" variant="white" />
            <span>{{ retryButtonText }}</span>
          </span>
        </NeonButton>
        <NeonButton
          variant="ghost"
          size="sm"
          :class="textClasses.message"
          @click="emit('dismiss')"
        >
          <span class="inline-flex items-center gap-2">
            <AppIcon name="X" size="sm" :variant="iconVariant" />
            <span>关闭</span>
          </span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>