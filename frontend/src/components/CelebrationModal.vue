<script setup lang="ts">
import { computed, onMounted, ref, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import AppIcon from '@/components/AppIcon.vue'
import { prefersReducedMotion } from '@/composables/useReducedMotion'

const { t } = useI18n()

interface Props {
  show: boolean
  title?: string
  message?: string
  // DB-10: real artifact counts to show instead of ✓/🎉 decoration.
  copyCount?: number
  imageCount?: number
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  message: '',
  copyCount: 0,
  imageCount: 0,
})

const displayTitle = computed(() => props.title || t('celebration.title'))
const displayMessage = computed(() => props.message || t('celebration.message'))

// Focus management
const closeButtonRef = ref<HTMLButtonElement | null>(null)
const previousFocusElement = ref<HTMLElement | null>(null)

// DB-10: skip confetti generation entirely under prefers-reduced-motion.
const particles = ref<{ id: number; x: number; y: number; color: string; delay: number; size: number }[]>([])

// Generate confetti particles (unless reduced motion is requested)
onMounted(() => {
  if (prefersReducedMotion.value) return
  const colors = ['#f43f5e', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#8b5cf6', '#ec4899']
  const particleCount = 50

  for (let i = 0; i < particleCount; i++) {
    particles.value.push({
      id: i,
      x: Math.random() * 100,
      y: -10 - Math.random() * 20,
      color: colors[Math.floor(Math.random() * colors.length)],
      delay: Math.random() * 0.5,
      size: 8 + Math.random() * 8,
    })
  }
})

const emit = defineEmits<{
  (e: 'close'): void
}>()

const handleClose = () => emit('close')

// Focus management: save previous focus, set focus to close button when opened, restore on close
watch(() => props.show, async (isOpen) => {
  if (isOpen) {
    // Save the element that had focus before modal opened
    previousFocusElement.value = document.activeElement as HTMLElement
    // Wait for DOM update then focus the close button
    await nextTick()
    closeButtonRef.value?.focus()
  } else {
    // Restore focus to the previous element
    previousFocusElement.value?.focus()
  }
})

// Keyboard handling: Escape to close
const handleKeyDown = (e: KeyboardEvent) => {
  if (e.key === 'Escape') {
    handleClose()
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="celebration">
      <div
        v-if="show"
        class="fixed inset-0 z-modal flex items-center justify-center"
        role="dialog"
        aria-modal="true"
        aria-labelledby="celebration-title"
        aria-describedby="celebration-message"
        @keydown="handleKeyDown"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-slate-900/30 backdrop-blur-sm" @click="handleClose" aria-hidden="true" />

        <!-- Confetti particles -->
        <div class="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
          <div
            v-for="particle in particles"
            :key="particle.id"
            :class="[
              'absolute rounded-full animate-confetti',
            ]"
            :style="{
              left: `${particle.x}%`,
              top: `${particle.y}%`,
              width: `${particle.size}px`,
              height: `${particle.size}px`,
              background: particle.color,
              animationDelay: `${particle.delay}s`,
            }"
          />
        </div>

        <!-- Celebration Card -->
        <div class="dark-explicit relative w-full max-w-md p-8 rounded-2xl bg-white/90 shadow-2xl border border-teal-200/50 text-center dark:bg-slate-900/95 dark:border-teal-500/30 dark:shadow-slate-950/50">
          <!-- Success Icon with animation -->
          <div class="w-20 h-20 mx-auto rounded-full bg-gradient-to-br from-teal-400 to-teal-500 flex items-center justify-center shadow-lg animate-bounce-slow">
            <AppIcon name="CheckCircle" size="xl" variant="white" />
          </div>

          <!-- Title -->
          <h2 id="celebration-title" class="text-2xl font-bold text-slate-800 mt-6 mb-2">
            {{ displayTitle }}
          </h2>

          <!-- Message -->
          <p id="celebration-message" class="text-slate-600 mb-6">{{ displayMessage }}</p>

          <!-- Stats Preview — DB-10: real artifact counts (decorative 100% cell removed) -->
          <div class="grid grid-cols-2 gap-3 mb-6">
            <div class="dark-explicit p-3 rounded-lg bg-rose-50 border border-rose-100 dark:bg-rose-950/40 dark:border-rose-500/30">
              <div class="text-rose-500 font-bold text-lg">{{ props.copyCount || '—' }}</div>
              <div class="text-xs text-slate-500">{{ t('celebration.copyCount') }}</div>
            </div>
            <div class="dark-explicit p-3 rounded-lg bg-teal-50 border border-teal-100 dark:bg-teal-950/40 dark:border-teal-500/30">
              <div class="text-teal-500 font-bold text-lg">{{ props.imageCount || '—' }}</div>
              <div class="text-xs text-slate-500">{{ t('celebration.imageCount') }}</div>
            </div>
          </div>

          <!-- Close Button -->
          <button
            ref="closeButtonRef"
            class="w-full px-6 py-3 rounded-lg bg-gradient-to-r from-teal-500 to-teal-400 text-white font-medium hover:from-teal-600 hover:to-teal-500 transition-all shadow-sm"
            @click="handleClose"
          >
            {{ t('celebration.backToDashboard') }}
          </button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.celebration-enter-active {
  transition: all 0.5s ease-out;
}

.celebration-leave-active {
  transition: all 0.3s ease-in;
}

.celebration-enter-from {
  opacity: 0;
}

.celebration-leave-to {
  opacity: 0;
}

.celebration-enter-from > div:last-child {
  transform: scale(0.8);
}

.celebration-leave-to > div:last-child {
  transform: scale(0.9);
}

.animate-confetti {
  animation: confetti-fall 3s ease-out forwards;
}

@keyframes confetti-fall {
  0% {
    transform: translateY(0) rotate(0deg);
    opacity: 1;
  }
  100% {
    transform: translateY(100vh) rotate(720deg);
    opacity: 0;
  }
}

.animate-bounce-slow {
  animation: bounce-slow 2s ease-in-out infinite;
}

@keyframes bounce-slow {
  0%, 100% {
    transform: translateY(0);
  }
  50% {
    transform: translateY(-10px);
  }
}
</style>