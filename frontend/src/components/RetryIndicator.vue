<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import AppIcon from '@/components/AppIcon.vue'

// Props
const props = defineProps<{
  retryCount: number
  nextRetryIn: number // seconds
}>()

// Emits
const emit = defineEmits<{
  cancel: []
}>()

// Internal countdown state
const countdown = ref(props.nextRetryIn)

// Computed
const progressPercent = computed(() => {
  if (props.nextRetryIn <= 0) return 100
  return ((props.nextRetryIn - countdown.value) / props.nextRetryIn) * 100
})

const formattedTime = computed(() => {
  const seconds = countdown.value
  if (seconds <= 0) return '0秒'
  if (seconds < 60) return `${seconds}秒`
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (remainingSeconds === 0) return `${minutes}分钟`
  return `${minutes}分${remainingSeconds}秒`
})

const retryText = computed(() => {
  return `第${props.retryCount}次重试`
})

// Countdown timer
let timer: ReturnType<typeof setInterval> | null = null

const startTimer = () => {
  countdown.value = props.nextRetryIn
  if (timer) clearInterval(timer)

  timer = setInterval(() => {
    if (countdown.value > 0) {
      countdown.value -= 1
    } else {
      if (timer) clearInterval(timer)
      timer = null
    }
  }, 1000)
}

// Watch for prop changes to restart timer
watch(() => props.nextRetryIn, (newValue) => {
  countdown.value = newValue
  startTimer()
})

// Start timer on mount
startTimer()

// Cleanup on unmount
onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div
    class="bg-amber-50/80 border border-amber-200/50 rounded-xl p-4"
    role="status"
    aria-live="polite"
    aria-label="重试状态"
  >
    <div class="flex items-center gap-3 mb-3">
      <!-- Retry icon with animation -->
      <div class="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center">
        <AppIcon name="RefreshCw" size="sm" variant="yellow" animate />
      </div>

      <!-- Retry count text -->
      <span class="text-amber-700 font-medium">
        {{ retryText }}
      </span>

      <!-- Countdown timer -->
      <span class="text-amber-600 text-sm">
        {{ formattedTime }}后重试
      </span>
    </div>

    <!-- Progress bar -->
    <div class="h-2 bg-amber-100 rounded-full overflow-hidden">
      <div
        class="h-full bg-gradient-to-r from-amber-400 to-amber-500 rounded-full transition-all duration-1000 ease-linear"
        :style="{ width: `${progressPercent}%` }"
      />
    </div>

    <!-- Cancel button -->
    <button
      class="mt-3 text-sm text-amber-600 hover:text-amber-700 transition-colors underline"
      @click="emit('cancel')"
    >
      取消重试
    </button>
  </div>
</template>