<script setup lang="ts">
import { computed, ref, watch, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { cn } from '@/utils/cn'

const { t } = useI18n()

interface Props {
  variant?: 'pink' | 'cyan' | 'purple' | 'peach' | 'ghost'
  size?: 'sm' | 'md' | 'lg'
  disabled?: boolean
  loading?: boolean
  success?: boolean
  ariaLabel?: string
  title?: string // Tooltip text
}

const props = withDefaults(defineProps<Props>(), {
  variant: 'pink',
  size: 'md',
  disabled: false,
  loading: false,
  success: false,
  ariaLabel: '',
  title: '',
})

const emit = defineEmits<{
  click: [event: MouseEvent]
}>()

// Ripple effect state
const rippleActive = ref(false)

// Success animation state
const showSuccessAnimation = ref(false)

// Watch success prop for animation trigger
watch(
  () => props.success,
  (newSuccess, oldSuccess) => {
    if (newSuccess && !oldSuccess) {
      showSuccessAnimation.value = true
      setTimeout(() => {
        showSuccessAnimation.value = false
      }, 600)
    }
  }
)

// Cleanup on unmount
onUnmounted(() => {
  showSuccessAnimation.value = false
})

const variantClasses = computed(() => {
  const variants = {
    pink: 'bg-gradient-to-r from-neon-pink via-neon-pinkLight to-neon-peach border-transparent shadow-neon-pink-sm hover:shadow-neon-pink hover:brightness-110 hover:scale-[1.03]',
    cyan: 'bg-gradient-to-r from-neon-cyan via-neon-cyanLight to-neon-green border-transparent shadow-neon-cyan-sm hover:shadow-neon-cyan hover:brightness-110 hover:scale-[1.03]',
    purple: 'bg-gradient-to-r from-neon-purple via-neon-purpleLight to-neon-blue border-transparent shadow-neon-purple-sm hover:shadow-neon-purple hover:brightness-110 hover:scale-[1.03]',
    peach: 'bg-gradient-to-r from-neon-peach via-neon-peachLight to-neon-yellow border-transparent shadow-neon-peach hover:shadow-neon-peach hover:brightness-110 hover:scale-[1.03]',
    ghost: 'bg-white/80 border-gray-200 hover:bg-white hover:border-gray-300 hover:scale-[1.02]',
  }
  return variants[props.variant]
})

const sizeClasses = computed(() => {
  const sizes = {
    sm: 'px-4 py-2 text-sm rounded-lg',
    md: 'px-6 py-3 text-base rounded-xl',
    lg: 'px-8 py-4 text-lg rounded-xl',
  }
  return sizes[props.size]
})

const handleClick = (e: MouseEvent) => {
  if (!props.disabled && !props.loading) {
    // Trigger ripple effect
    rippleActive.value = true
    setTimeout(() => {
      rippleActive.value = false
    }, 600)
    emit('click', e)
  }
}
</script>

<template>
  <button
    @click="handleClick"
    :disabled="disabled || loading"
    :aria-label="ariaLabel || undefined"
    :aria-busy="loading"
    :title="title || undefined"
    :class="[
      'relative rounded-xl border font-semibold overflow-hidden',
      'transition-all duration-200 ease-out',
      'transform hover:scale-[1.02] active:scale-[0.98]',
      'disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:scale-100',
      'focus:outline-none focus-visible:ring-2 focus-visible:ring-slate-400/30 focus-visible:ring-offset-2 focus-visible:ring-offset-white',
      variant === 'ghost' ? 'text-slate-700' : 'text-white',
      variantClasses,
      sizeClasses,
      { 'scale-bounce-animation': showSuccessAnimation },
    ]"
  >
    <!-- Content -->
    <span :class="cn('relative z-10 flex items-center justify-center gap-2', loading && 'opacity-80')">
      <span v-if="loading" class="inline-flex items-center gap-2">
        <AppIcon name="Loader2" size="sm" variant="white" animate :aria-label="t('common.loading')" />
        <span>{{ t('common.loading') }}</span>
      </span>
      <span v-else-if="success" class="inline-flex items-center gap-2">
        <AppIcon name="Check" size="sm" variant="white" :aria-label="t('common.success')" />
        <slot />
      </span>
      <slot v-else />
    </span>
  </button>
</template>

<style scoped>
.scale-bounce-animation {
  animation: scale-bounce 600ms ease-out;
}

@keyframes scale-bounce {
  0% {
    transform: scale(1);
  }
  30% {
    transform: scale(1.1);
  }
  50% {
    transform: scale(0.95);
  }
  70% {
    transform: scale(1.05);
  }
  100% {
    transform: scale(1);
  }
}
</style>