<script setup lang="ts">
import { computed, ref, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ErrorType } from '@/types/error'
import AppIcon from '@/components/AppIcon.vue'
import NeonButton from '@/components/NeonButton.vue'

const { t } = useI18n()

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

// Shake animation state
const isShaking = ref(false)

// Trigger shake animation on mount
onMounted(() => {
  isShaking.value = true
  setTimeout(() => {
    isShaking.value = false
  }, 300)
})

// Computed
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
      return 'peach'
    case 'unknown':
      return 'purple'
    case 'retry_success':
      return 'cyan'
    default:
      return 'pink'
  }
})
const title = computed(() => {
  switch (props.type) {
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
const showRetryButton = computed(() => props.type !== 'retry_success')
const retryButtonText = computed(() => {
  if (props.retryCount && props.retryCount > 0) {
    return t('common.retryCount', { count: props.retryCount })
  }
  return t('common.retry')
})
</script>

<template>
  <div class="rounded-2xl p-6 border" :class="[bgClasses, { 'shake-animation': isShaking }]">
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
          {{ t('common.retriedTimes', { count: retryCount }) }}
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
            <span>{{ t('common.close') }}</span>
          </span>
        </NeonButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.shake-animation {
  animation: shake 300ms ease-in-out;
}

@keyframes shake {
  0%, 100% {
    transform: translateX(0);
  }
  10%, 30%, 50%, 70%, 90% {
    transform: translateX(-4px);
  }
  20%, 40%, 60%, 80% {
    transform: translateX(4px);
  }
}
</style>