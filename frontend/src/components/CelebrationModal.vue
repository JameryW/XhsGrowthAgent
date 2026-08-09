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
  copyCount?: number | null
  imageCount?: number | null
  /** Published post URL; the view CTA is omitted when the publisher has no link. */
  postUrl?: string | null
  /** Replay snapshots must never offer a live-workflow action. */
  canReplay?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  title: '',
  message: '',
  copyCount: null,
  imageCount: null,
  postUrl: null,
  canReplay: true,
})

const displayTitle = computed(() => props.title || t('celebration.title'))
const displayMessage = computed(() => props.message || t('celebration.message'))
const normalizedPostUrl = computed(() => {
  const url = props.postUrl?.trim()
  return url || null
})

// Focus management
const closeButtonRef = ref<HTMLButtonElement | null>(null)
const previousFocusElement = ref<HTMLElement | null>(null)

// DB-10: skip confetti generation entirely under prefers-reduced-motion.
const particles = ref<{ id: number; x: number; y: number; color: string; delay: number; size: number }[]>([])

// Generate confetti particles (unless reduced motion is requested). The
// watcher also removes already-rendered particles when the OS preference
// changes while the modal is open.
function generateParticles() {
  if (prefersReducedMotion.value) {
    particles.value = []
    return
  }

  const colors = ['#f43f5e', '#f97316', '#eab308', '#22c55e', '#06b6d4', '#8b5cf6', '#ec4899']
  const particleCount = 50

  particles.value = Array.from({ length: particleCount }, (_, id) => ({
    id,
    x: Math.random() * 100,
    y: -10 - Math.random() * 20,
    color: colors[Math.floor(Math.random() * colors.length)],
    delay: Math.random() * 0.5,
    size: 8 + Math.random() * 8,
  }))
}

onMounted(generateParticles)
watch(prefersReducedMotion, generateParticles)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'view-post'): void
  (e: 'replay'): void
}>()

const handleClose = () => emit('close')
const handleViewPost = () => {
  if (normalizedPostUrl.value) emit('view-post')
}
const handleReplay = () => {
  if (props.canReplay) emit('replay')
}

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
        :class="{ 'motion-reduced': prefersReducedMotion }"
        role="dialog"
        aria-modal="true"
        aria-labelledby="celebration-title"
        aria-describedby="celebration-message"
        @keydown="handleKeyDown"
      >
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-slate-900/30 backdrop-blur-sm" @click="handleClose" aria-hidden="true" />

        <!-- Confetti particles -->
        <div v-if="!prefersReducedMotion" class="absolute inset-0 overflow-hidden pointer-events-none" aria-hidden="true">
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
        <div class="celebration-card dark-explicit relative w-full max-w-md p-8 rounded-2xl bg-white/90 shadow-2xl border border-teal-200/50 text-center dark:bg-slate-900/95 dark:border-teal-500/30 dark:shadow-slate-950/50">
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
              <div class="text-rose-500 font-bold text-lg">{{ props.copyCount ?? '—' }}</div>
              <div class="text-xs text-slate-500">{{ t('celebration.copyCount') }}</div>
            </div>
            <div class="dark-explicit p-3 rounded-lg bg-teal-50 border border-teal-100 dark:bg-teal-950/40 dark:border-teal-500/30">
              <div class="text-teal-500 font-bold text-lg">{{ props.imageCount ?? '—' }}</div>
              <div class="text-xs text-slate-500">{{ t('celebration.imageCount') }}</div>
            </div>
          </div>

          <div class="mb-3 flex flex-col gap-2 sm:flex-row">
            <a
              v-if="normalizedPostUrl"
              data-testid="celebration-view-post"
              :href="normalizedPostUrl"
              target="_blank"
              rel="noopener noreferrer"
              class="inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-lg border border-teal-200 px-4 py-2 text-sm font-medium text-teal-700 transition-colors hover:bg-teal-50 dark:border-teal-500/40 dark:text-teal-200 dark:hover:bg-teal-950/40"
              @click="handleViewPost"
            >
              <AppIcon name="ExternalLink" size="sm" variant="cyan" aria-hidden="true" />
              {{ t('celebration.viewPost') }}
            </a>
            <span v-else class="flex min-h-11 flex-1 items-center justify-center rounded-lg border border-slate-200 px-4 py-2 text-xs text-slate-400 dark:border-slate-700 dark:text-slate-500">
              {{ t('celebration.postUnavailable') }}
            </span>
            <button
              v-if="canReplay"
              type="button"
              data-testid="celebration-replay"
              class="inline-flex min-h-11 flex-1 items-center justify-center gap-1.5 rounded-lg border border-rose-200 px-4 py-2 text-sm font-medium text-rose-600 transition-colors hover:bg-rose-50 dark:border-rose-500/40 dark:text-rose-200 dark:hover:bg-rose-950/40"
              @click="handleReplay"
            >
              <AppIcon name="Plus" size="sm" variant="pink" aria-hidden="true" />
              {{ t('celebration.createAnother') }}
            </button>
          </div>

          <!-- Close Button -->
          <button
            ref="closeButtonRef"
            class="min-h-11 w-full rounded-lg bg-gradient-to-r from-teal-500 to-teal-400 px-6 py-3 font-medium text-white shadow-sm transition-all hover:from-teal-600 hover:to-teal-500"
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

.celebration-enter-from .celebration-card {
  transform: scale(0.8);
}

.celebration-leave-to .celebration-card {
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

@media (prefers-reduced-motion: reduce) {
  .celebration-enter-active,
  .celebration-leave-active {
    transition: none;
  }

  .celebration-enter-from .celebration-card,
  .celebration-leave-to .celebration-card {
    transform: none;
  }

  .animate-confetti,
  .animate-bounce-slow {
    animation: none;
  }
}
</style>
